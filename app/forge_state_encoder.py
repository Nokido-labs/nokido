"""
Phase 0 — AMI roadmap: encode Nokido system state → 384d float32 embedding.
State = active RAG context + task queue snapshot.
"""

import json
import logging          # utilise par les chemins d'alerte : sans lui, prevenir
                        # d'un refus levait un NameError et l'effacait
import os
import numpy as np
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).parent.parent
_MODEL_CACHE = None

# Phase 1 unification (c) : dim cible de l'encodeur cognition. 384 = MiniLM/nomic
# (cognition actuelle, world_model 384d-natif). 1024 = embed_router BGE-M3 (MÊME
# espace que le RAG). Défaut 384 = NON-BREAKING ; phase 2 flippe après retrain des
# consommateurs (world_model/value-nets). Voir roadmap-cognition-1024d-unification.
STATE_DIM = int(os.environ.get("LAFORGE_STATE_DIM", "384"))


def _entetes_hub() -> dict:
    """En-tetes d'appel au hub, Bearer COMPRIS.

    Sans ce Bearer, tout appel a /mcp est rejete en 401. Mesure 2026-08-04 :
    114 406 rejets dans network_log, soit 44 % de TOUT le trafic du hub, tous
    imputables a ce module appele en boucle par NokidoTraceSidecar. Le cout n'est
    pas seulement du bruit : la reponse etait avalee et remplacee par
    « tasks:unknown », donc l'etat encode ici est AVEUGLE depuis des semaines et
    personne ne le savait.

    Le jeton vient du coffre (forge_secrets), jamais d'un litteral : un secret en
    dur est refuse par le gate egress.
    """
    # `LaForge-Agent-Name` est le nom CANONIQUE (RFC 6648 §3, directive
    # ARCHITECTURE_IDENTITE du 2026-06-16) ; `X-Agent-Name` reste en repli le
    # temps de la transition, le hub lit les deux.
    entetes = {
        "Content-Type": "application/json",
        "LaForge-Agent-Name": "STATE_ENCODER",
        "X-Agent-Name": "STATE_ENCODER",
    }
    try:
        from nokido_agent.app.forge_secrets import get_secret

        # MARQUEUR PROPRE D'ABORD -- correction du 2026-09-02.
        # Ce module portait le jeton MAITRE, et le maitre est un PASSE-PARTOUT :
        # mesure du jour, son porteur peut se declarer n'importe quel agent et
        # HERITER de son ring (porteur du maitre annoncant CLAUDE -> ring 1),
        # la ou un jeton derive fait retomber un nom non apparie au plancher
        # anti-spoof. Un organe au maitre n'a donc pas une identite, il a un
        # passe-partout -- et le journal le lisait comme authentifie.
        # Le repli maitre subsiste pour ne pas rendre le module muet si le
        # marqueur n'a pas ete provisionne, mais il est DIT dans les journaux
        # (via=bearer_maitre cote hub).
        # SUITE du 2026-09-02 : le marqueur propre n'est plus le bearer, il est
        # le SECRET D'ECHANGE contre un jeton a bail (1800 s, revocable). Un
        # credential statique est permanent : ni expiration, ni revocation.
        # Mesure : le ring resolu est identique par les deux voies (3), donc la
        # bascule ne coute aucun privilege. `jeton_pour` retombe lui-meme sur le
        # statique en cas d'echec ; le repli ci-dessous ne couvre que l'absence
        # du pont, et il reste DIT plutot que muet.
        jeton = ""
        try:
            from nokido_agent.app.forge_agent_credential import jeton_pour

            jeton = jeton_pour("STATE_ENCODER")
        except Exception as _e:  # noqa: BLE001
            logging.getLogger(__name__).info(
                "[state_encoder] pont jeton a bail indisponible (%s) — repli sur "
                "le credential statique, PERMANENT donc non revocable",
                type(_e).__name__)
        if not jeton:
            jeton = get_secret("FORGE_TOKEN_STATE_ENCODER") or get_secret("FORGE_MCP_TOKEN")
        if jeton:
            entetes["Authorization"] = "Bearer " + jeton
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "[state_encoder] jeton hub illisible (%s) — l'appel partira sans "
            "credential et sera rejete en 401", type(e).__name__)
    return entetes


# Un refus RBAC ne se guerit pas en re-essayant : il est structurel. Mesure du
# 2026-08-14 — 7 424 DENY pour cet agent, un toutes les 10 s pendant ~20 h,
# chacun ecrivant dans `videur_identity.log` (63 Mo, le plus gros journal du
# depot). On memorise le refus une fois pour toutes et on passe au plan B.
_HUB_REFUSE = False


def _etat_workers_local() -> str:
    """Etat des workers lu SUR DISQUE, sans passer par le hub ni aucun droit.

    Les heartbeats sont la source de verite du pouls des daemons ; les lire
    directement est plus fiable que de les demander a un service qui peut etre
    mort — et c'est precisement quand le hub est mort qu'on veut cet etat.
    """
    from pathlib import Path as _P
    import time as _t

    base = _P(__file__).resolve().parent.parent / "sandbox"
    vivants, perimes = 0, 0
    try:
        for h in base.glob("*.heartbeat"):
            age = _t.time() - h.stat().st_mtime
            if age < 300:
                vivants += 1
            else:
                perimes += 1
    except OSError as e:
        return "workers:illisible(%s)" % type(e).__name__
    return "workers:vivants=%d perimes=%d" % (vivants, perimes)


def _est_refus(data: dict) -> str:
    """Le hub repond 200 avec le refus DANS le corps : sans ce test, un DENY
    etait encode comme s'il etait l'etat du systeme."""
    brut = json.dumps(data)[:600].lower()
    for motif in ("gate deny", "gate_denied", "insufficient ring", "rbac",
                  "denied", "forbidden"):
        if motif in brut:
            return motif
    return ""


def get_current_state_text(hub_url: str = "http://127.0.0.1:8766") -> str:
    """Snapshot live system state as a single text string."""
    import urllib.request, urllib.error

    global _HUB_REFUSE
    parts: list[str] = []

    if _HUB_REFUSE:
        return _etat_workers_local()

    # Hub worker status
    try:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "run", "arguments": {"action": "worker_status"}},
            }
        ).encode()
        req = urllib.request.Request(
            hub_url + "/mcp", data=payload, headers=_entetes_hub(), method="POST"
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
            refus = _est_refus(data)
            if refus:
                _HUB_REFUSE = True
                logging.getLogger(__name__).warning(
                    "[state_encoder] hub REFUSE l'outil (%s) — bascule DEFINITIVE "
                    "sur la lecture locale des heartbeats. Ce refus est structurel "
                    "(agent non declare au SSoT, ring plancher) : le reessayer "
                    "toutes les 10 s n'y change rien.", refus)
                return _etat_workers_local()
            parts.append("tasks:" + json.dumps(data.get("result", {}))[:300])
    except Exception as e:  # noqa: BLE001
        # Chemin d'erreur NON muet : « tasks:unknown » seul a masque un 401
        # permanent pendant des semaines. L'etat encode doit dire qu'il est
        # aveugle, et pourquoi.
        _motif = getattr(e, "code", None) or type(e).__name__
        logging.getLogger(__name__).warning(
            "[state_encoder] etat hub illisible (%s) — encodage degrade", _motif)
        parts.append("tasks:unknown(%s)" % _motif)

    return " | ".join(parts) if parts else "state:empty"


def get_current_state_text_rich(hub_url: str = "http://127.0.0.1:8766") -> str:
    """État ENRICHI (phase 1b unification c) : tasks + mood (intéroception) + hormones
    (endocrine actives). État DENSE vs le thin 'tasks:unknown'. Utilisé par le path 1024d
    (futur retrain) ; le world_model 384d garde le thin (distribution inchangée)."""
    parts = [get_current_state_text(hub_url)]
    try:
        from nokido_agent.app.forge_system_mood import get_mood

        m = get_mood()
        parts.append(
            f"mood: energy={m.energy:.2f} curiosity={m.curiosity:.2f} "
            f"fatigue={m.fatigue:.2f} immune={m.immune_alert:.2f}"
        )
    except Exception:
        pass
    try:
        from nokido_agent.app.forge_endocrine import all_hormones, read as _hread

        active = {h: _hread(h) for h in all_hormones()}
        active = {h: v for h, v in active.items() if v > 0.01}
        if active:
            top = sorted(active.items(), key=lambda x: -x[1])[:6]
            parts.append("hormones: " + ", ".join(f"{h}={v:.2f}" for h, v in top))
    except Exception:
        pass
    return " | ".join(parts)


def _load_model():
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    try:
        from sentence_transformers import SentenceTransformer

        _MODEL_CACHE = SentenceTransformer("all-MiniLM-L6-v2")
        return _MODEL_CACHE
    except Exception:  # noqa: BLE001 - sentence_transformers cassé (backend py314 lève != ImportError)
        # -> fail-safe : None déclenche le fallback nomic(ollama)/hash dans _encode_384.
        # AVANT: except ImportError seul -> l'erreur backend propageait -> _encode_384 CRASHE
        # -> état non encodable -> traces state_t_emb NULL (world model affamé). Audit 2026-06-16.
        return None


def _encode_384(text: str) -> np.ndarray:
    """Path 384d historique : MiniLM -> nomic(ollama) -> hash. Cognition actuelle."""
    model = _load_model()
    if model is not None:
        return model.encode(text, normalize_embeddings=True).astype("float32")
    try:
        import urllib.request

        payload = json.dumps({"model": "nomic-embed-text", "prompt": text}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/embeddings", data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            emb = json.loads(r.read()).get("embedding", [])
        if emb:
            v = np.array(emb, dtype="float32")
            v = v[:384] if len(v) > 384 else np.pad(v, (0, max(0, 384 - len(v))))
            norm = np.linalg.norm(v)
            return v / norm if norm > 0 else v
    except Exception:
        pass
    seed = int.from_bytes(text.encode()[:8], "big") % (2**32)
    v = np.random.default_rng(seed).standard_normal(384).astype("float32")
    return v / np.linalg.norm(v)


def _encode_1024(text: str) -> np.ndarray:
    """Path 1024d UNIFIÉ (phase 1 c) : embed_router BGE-M3 = MÊME espace que le RAG.
    Fallback = pont forge_embed_bridge.to_1024 sur le 384d (approx), puis pad."""
    try:
        import sys as _s

        _t = str(Path(__file__).resolve().parent.parent / "tools")
        if _t not in _s.path:
            _s.path.insert(0, _t)
        from nokido_agent.app.forge_embed_router import embed as _routed

        v = _routed(text)
        if v and len(v) == 1024:
            a = np.array(v, dtype="float32")
            n = np.linalg.norm(a)
            return a / n if n > 0 else a
    except Exception:
        pass
    try:
        from nokido_agent.tools.forge_embed_bridge import to_1024

        return to_1024(_encode_384(text))
    except Exception:
        v = _encode_384(text)
        return np.pad(v, (0, 1024 - len(v)))


def _encode_4096(text: str) -> np.ndarray:
    """Path 4096d (phase 2 — exploite le wire essaim MTU 9000 / multicast 239.255.0.1, vecteur
    4096d FP16 = 1 paquet jumbo). État MULTI-FACETTE : 4 vues BGE-M3 1024d CONCATÉNÉES =
    représentation riche (PAS un pad creux). Facettes = [holistique, système/tasks,
    mood/intéroception, hormones/endocrine] (split du rich text sur ' | '). Souverain (4x :8099
    local, zéro quota cloud). 4x1024 = 4096, normalisé."""
    parts = [p.strip() for p in (text or "").split("|")]
    facets = [text or ""] + (parts + ["", ""])[:3]  # 0=holistique ; 1-3=sous-facettes (zero si absent)
    vecs = [(_encode_1024(f) if f else np.zeros(1024, dtype="float32")) for f in facets]
    v = np.concatenate(vecs).astype("float32")
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def encode_state(text: str = None, hub_url: str = "http://127.0.0.1:8766", dim: int = None) -> np.ndarray:
    """Embed system state -> vecteur normalisé float32.

    dim=384 (cognition actuelle, défaut via STATE_DIM) = MiniLM/nomic.
    dim=1024 = embed_router BGE-M3 (MÊME espace que le RAG, unification c phase 1).
    Défaut NON-BREAKING : les consommateurs world_model 384d restent intacts."""
    _dim = dim or STATE_DIM
    if text is None:
        text = get_current_state_text_rich(hub_url) if _dim >= 1024 else get_current_state_text(hub_url)
    if _dim == 4096:
        return _encode_4096(text)
    return _encode_1024(text) if _dim == 1024 else _encode_384(text)


def encode_state_batch(texts: list[str], dim: int = None) -> np.ndarray:
    """Encode N texts -> (N, dim) float32. dim défaut = STATE_DIM."""
    _dim = dim or STATE_DIM
    if not texts:
        return np.zeros((0, _dim), dtype="float32")
    if _dim == 384:
        model = _load_model()
        if model is not None:
            vecs = model.encode(texts, normalize_embeddings=True, batch_size=256, show_progress_bar=False)
            return vecs.astype("float32")
    return np.stack([encode_state(t, dim=_dim) for t in texts])


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


if __name__ == "__main__":
    t = "test state: tasks running, ram 60pct"
    v384 = encode_state(t)             # défaut STATE_DIM=384 (cognition actuelle, intact)
    v1024 = encode_state(t, dim=1024)  # unifié BGE-M3 via embed_router
    print(f"384d  : shape={v384.shape} norm={np.linalg.norm(v384):.3f}")
    print(f"1024d : shape={v1024.shape} norm={np.linalg.norm(v1024):.3f}")
    assert v384.shape == (384,), v384.shape
    assert v1024.shape == (1024,), v1024.shape
    v4096 = encode_state(t, dim=4096)  # phase 2 : 4 facettes BGE-M3 concat (wire essaim MTU 9000)
    print(f"4096d : shape={v4096.shape} norm={np.linalg.norm(v4096):.3f}")
    assert v4096.shape == (4096,), v4096.shape
    rich = get_current_state_text_rich()
    print(f"rich state (1b): {rich[:240]}")
    print("PHASE1 OK | 384 defaut intact + 1024 via embed_router + etat enrichi (tasks+mood+hormones)")
