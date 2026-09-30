"""
app/forge_anatomy_state.py — Snapshot état anatomique Nokido pour Deno WebHub.
Lit sandbox/*.heartbeat + RAG/embeddings.db stats + hormones actives.

Format compatible avec anatomy.html (champs x/y/r/color/activity/health/note).
Layout : silhouette body sur canvas 1000x600 centre. Biomimetique mapping
issu de CLAUDE.md section 10.
"""

import glob
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

_ROOT = Path(__file__).resolve().parent.parent
_SANDBOX = _ROOT / "sandbox"
_RAG_DB = _ROOT / "RAG" / "embeddings.db"
_LESSONS = _ROOT / "logs" / "lessons_learned.md"


# ─── Biomimetic anatomy layout ─────────────────────────────────────────────
# (x, y, r, color_base, biological_name, technical_label, port_or_module)
_ORGAN_LAYOUT: dict[str, dict] = {
    # SNC — Cortex préfrontal / Hub / Cervelet
    "hub": {"x": 500, "y": 120, "r": 38, "label": "Hub MCP", "bio": "Cerveau (cortex)", "port": 8766},
    "cortex": {
        "x": 500,
        "y": 75,
        "r": 26,
        "label": "Cortex",
        "bio": "Cortex prefrontal",
        "module": "forge_cognitive_router",
    },
    "cerebellum": {
        "x": 580,
        "y": 140,
        "r": 22,
        "label": "Cervelet",
        "bio": "Cervelet SNN",
        "module": "forge_spike_router",
    },
    "thalamus": {"x": 420, "y": 140, "r": 22, "label": "Thalamus", "bio": "NLU triage", "module": "forge_nlu"},
    # Memoire — Hippocampe / RAG / Brain worker
    "hippocampus": {
        "x": 360,
        "y": 220,
        "r": 26,
        "label": "Hippocampe",
        "bio": "Consolidation",
        "module": "forge_self_correction",
    },
    "rag_cortex": {"x": 260, "y": 280, "r": 32, "label": "RAG", "bio": "Cortex sensoriel", "port": "embeddings.db"},
    "brain_worker": {"x": 360, "y": 340, "r": 22, "label": "BrainWorker", "bio": "Synapses BGE-M3", "port": 5557},
    # Immunitaire — SemanticFirewall / Membrane / Guardian
    "firewall": {
        "x": 640,
        "y": 220,
        "r": 26,
        "label": "SemanticFW",
        "bio": "Barriere hemato-encephalique",
        "module": "forge_semantic_firewall",
    },
    "membrane": {
        "x": 720,
        "y": 280,
        "r": 22,
        "label": "Membrane",
        "bio": "Membrane cellulaire",
        "module": "forge_sovereign_membrane",
    },
    "guardian": {
        "x": 640,
        "y": 340,
        "r": 22,
        "label": "SkillGuard",
        "bio": "Macrophage",
        "module": "forge_clawhub_bridge",
    },
    # SN Vegetatif — Inspector / Idle watchdog
    "inspector": {
        "x": 200,
        "y": 420,
        "r": 18,
        "label": "Inspector",
        "bio": "Bulbe rachidien",
        "module": "forge_inspector",
    },
    "watchdog": {
        "x": 800,
        "y": 420,
        "r": 18,
        "label": "Watchdog",
        "bio": "Sympathique",
        "module": "forge_idle_watchdog",
    },
    # Digestif — Ingest pipeline
    "ingest": {
        "x": 140,
        "y": 360,
        "r": 22,
        "label": "Ingest",
        "bio": "Estomac (broyage)",
        "module": "forge_ingest_self",
    },
    "rag_qualify": {
        "x": 140,
        "y": 280,
        "r": 18,
        "label": "Qualify",
        "bio": "Intestin grele",
        "module": "forge_rag_qualify",
    },
    # Locomoteur — 7 Silos
    "silo_code": {
        "x": 460,
        "y": 460,
        "r": 18,
        "label": "SiloCode",
        "bio": "Muscles (code)",
        "module": "forge_silo_engine",
    },
    "silo_security": {
        "x": 540,
        "y": 460,
        "r": 18,
        "label": "SiloSecu",
        "bio": "Muscles (security)",
        "module": "forge_silo_engine",
    },
    "silo_recon": {
        "x": 380,
        "y": 460,
        "r": 18,
        "label": "SiloRecon",
        "bio": "Muscles (recon)",
        "module": "forge_silo_engine",
    },
    # Sens — Browser / Netcfg / Android
    "browser": {"x": 880, "y": 280, "r": 18, "label": "Browser", "bio": "Vision", "module": "forge_browser_tool"},
    "netcfg": {"x": 880, "y": 360, "r": 22, "label": "NetCfg", "bio": "Toucher (SSH PTY)", "port": 7500},
    # Metabolisme — LLM router + Ollama
    "llm_router": {
        "x": 500,
        "y": 540,
        "r": 26,
        "label": "LLMRouter",
        "bio": "Metabolisme energetique",
        "module": "forge_llm_router",
    },
    "ollama": {"x": 600, "y": 540, "r": 22, "label": "Ollama", "bio": "Foie (local LLM)", "port": 11434},
    # Coeur — Deno WebHub (event bus)
    "deno_hub": {"x": 320, "y": 540, "r": 22, "label": "DenoHub", "bio": "Coeur (event bus)", "port": 7401},
}

# Flows (animations data-flow entre organes pertinents)
_BASE_FLOWS = [
    {"from": "hub", "to": "thalamus", "msg": "request", "effect": "triage"},
    {"from": "thalamus", "to": "cortex", "msg": "intent", "effect": "decide"},
    {"from": "cortex", "to": "cerebellum", "msg": "plan", "effect": "execute"},
    {"from": "cortex", "to": "hippocampus", "msg": "anchor", "effect": "consolidate"},
    {"from": "hippocampus", "to": "rag_cortex", "msg": "store", "effect": "persist"},
    {"from": "rag_cortex", "to": "brain_worker", "msg": "embed", "effect": "vectorize"},
    {"from": "firewall", "to": "hub", "msg": "shield", "effect": "filter"},
    {"from": "ingest", "to": "rag_qualify", "msg": "chunk", "effect": "score"},
    {"from": "rag_qualify", "to": "rag_cortex", "msg": "trust", "effect": "weight"},
    {"from": "llm_router", "to": "ollama", "msg": "local", "effect": "infer"},
    {"from": "llm_router", "to": "membrane", "msg": "wrap", "effect": "sanitize"},
    {"from": "membrane", "to": "browser", "msg": "egress", "effect": "send"},
]


def _read_heartbeats(window_seconds: int) -> list:
    now = time.time()
    results = []
    for fp in glob.glob(str(_SANDBOX / "*.heartbeat")):
        try:
            data = json.loads(Path(fp).read_text(encoding="utf-8", errors="replace"))
            ts = data.get("timestamp") or data.get("ts_unix") or data.get("ts") or 0
            if isinstance(ts, str):  # ISO format possible
                try:
                    from datetime import datetime

                    ts = datetime.fromisoformat(ts).timestamp()
                except Exception:
                    ts = 0
            age = now - ts if ts else 99999
            results.append(
                {
                    "name": Path(fp).stem,
                    "age_s": round(age, 1),
                    "alive": age < window_seconds,
                    "errors": data.get("session_errors", 0),
                    "embedded": data.get("session_embedded", 0),
                }
            )
        except Exception:
            results.append({"name": Path(fp).stem, "age_s": -1, "alive": False})
    return results


def _rag_stats() -> dict:
    """Derniers compteurs RAG CONNUS. Ne compte JAMAIS lui-meme.

    CE QUE CA REPARE, mesure le 2026-09-17 par le veilleur de gel du webhub.
    Cette fonction faisait DEUX balayages complets de `rag_chunks` -- une base
    de 24,9 Go -- a CHAQUE appel :

        SELECT COUNT(*) FROM rag_chunks
        SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL

    Le `timeout=3` ne protegeait rien : c'est un delai d'attente de VERROU, pas
    une echeance de requete ; un balayage lance n'est jamais interrompu par lui.
    Or l'appelant est la route `/vitals` (`vital_api`), declaree `def`, donc
    SYNCHRONE : chaque requete occupe un ouvrier du threadpool anyio pour toute
    la duree du balayage. Deux piles prises en flagrant delit dans le meme dump
    (`webhub_vie.log`, 21:32:20) -- et `/health`, lui aussi synchrone, se met en
    FILE derriere. Resultat lu de l'exterieur : port LISTENING, process vivant,
    sonde muette. La campagne UI a conclu SERVICE MORT EN COURS DE PASSE.

    C'est la maladie que les regles du depot nomment deja : un organe qui
    RECOMPTE ce que son producteur connait. Le remede etait prescrit et non
    applique ici -- lire le snapshot de `forge_memory_availability`, ecrit hors
    du chemin chaud.

    ET ON NE REND PLUS DE ZEROS. L'ancienne version rendait `{0, 0, 0}` sur
    absence de base ET sur exception : un echec de lecture devenait donc « base
    vide », c'est-a-dire une MESURE, alors que c'est une CECITE. Ici l'inconnu
    se dit : les compteurs valent `None` et `raison` porte le motif.
    """
    try:
        from nokido_agent.app.forge_memory_availability import snapshot
    except ImportError:
        try:
            from forge_memory_availability import snapshot
        except ImportError as exc:
            return {"chunks": None, "embedded": None, "pending": None,
                    "mesure": "INCONNU", "age_s": None,
                    "raison": "producteur illisible (%s)" % type(exc).__name__}
    try:
        snap = snapshot()
    except Exception as exc:  # noqa: BLE001
        return {"chunks": None, "embedded": None, "pending": None,
                "mesure": "INCONNU", "age_s": None,
                "raison": "snapshot illisible (%s)" % type(exc).__name__}

    total = snap.get("total")
    pending = snap.get("vector_pending")   # None des que le snapshot n'est pas frais
    if not snap.get("frais") or total is None or pending is None:
        return {"chunks": total, "embedded": None, "pending": pending,
                "mesure": "INCONNU", "age_s": snap.get("age_s"),
                "raison": snap.get("raison") or "snapshot non frais"}
    return {"chunks": total, "embedded": total - pending, "pending": pending,
            "mesure": "SNAPSHOT", "age_s": snap.get("age_s"), "raison": ""}


def _recent_lessons(n: int = 5) -> list:
    if not _LESSONS.exists():
        return []
    try:
        lines = _LESSONS.read_text(encoding="utf-8", errors="replace").splitlines()
        headers = [l[4:].strip() for l in lines if l.startswith("### ")]
        return headers[-n:]
    except Exception:
        return []


def _hormones_active() -> dict[str, float]:
    """Niveaux d hormones (adrenaline/cortisol/dopamine/oxytocin) actuelles."""
    try:
        import sys

        sys.path.insert(0, str(_ROOT))
        from nokido_agent.app.forge_hormones import active  # type: ignore

        out: dict[str, float] = {}
        for h in ("adrenaline", "cortisol", "dopamine", "oxytocin"):
            try:
                state = active(h)
                if isinstance(state, dict):
                    out[h] = float(state.get("level", 0.0))
                else:
                    out[h] = 0.0
            except Exception:
                out[h] = 0.0
        return out
    except Exception:
        return {}


def _trafic_par_organe(window_seconds: int, organs: dict) -> dict[str, int]:
    """Nombre de requetes observees PAR ORGANE dans la fenetre.

    POURQUOI (mesure du 2026-09-18) : la carte etait FIGEE -- sur cinq secondes,
    zero organe sur vingt-deux changeait d'activite, de couleur ou de sante. La
    raison n'etait pas le rendu : `_organ_activity` partait d'une base constante
    de 0.3 et n'ajoutait que des bonus HORMONAUX, or les hormones etaient a zero.
    Tous les organes valaient donc 0.3, en permanence.

    Le trafic, lui, existe et ne cesse pas : huit cents evenements d'audit frais,
    dont sept cent soixante-treize requetes HTTP, le plus recent a zero seconde.
    C'est une mesure REELLE, disponible, et qui bouge -- il suffisait de la lire.

    Rend un dictionnaire VIDE si la source est illisible : l'appelant doit alors
    s'abstenir d'ajouter quoi que ce soit, et surtout pas supposer une activite
    nulle. Une source muette n'est pas une absence de trafic.
    """
    try:
        import sys as _s

        _s.path.insert(0, str(_ROOT / "app"))
        from nokido_agent.app.forge_audit_log import query_recent
    except Exception:
        return {}
    try:
        spans = query_recent(limit=800)
    except Exception:
        return {}
    now = time.time()
    compte: dict[str, int] = {}
    _non_mappes = 0
    for sp in spans:
        ts = sp.get("ts") or 0
        if now - ts > max(window_seconds, 60):
            continue
        cible = _organ_of(sp.get("action") or sp.get("agent"), organs)
        if not cible:
            cible = _organ_of(sp.get("target"), organs)
        if not cible:
            cible = _organe_de_la_route(sp.get("target"), sp.get("action"), organs)
        if cible:
            compte[cible] = compte.get(cible, 0) + 1
        else:
            _non_mappes += 1
    # Ce qui n'a pas pu etre rattache est COMPTE, pas tu : sans ce chiffre, une
    # couverture de deux pour cent se lirait comme une carte complete.
    if _non_mappes:
        compte["_non_mappes"] = _non_mappes
    return compte


def _organe_de_la_route(target: str | None, action: str | None, organs: dict) -> str | None:
    """Rattache une requete HTTP a l'organe qui la SERT.

    MESURE du 2026-09-18, sur quatre cents evenements : trois cent soixante-quatorze
    sont des requetes HTTP dont la cible est `POST /mcp` (deux cent soixante-huit),
    `GET /health` (quatre-vingt-trois) ou une route d'API. Le vocabulaire des
    organes ne contient aucun de ces mots : quatre cibles sur quatre cents etaient
    rattachables, et l'activite de la carte restait donc plate.

    Ce rattachement n'invente rien -- il nomme qui sert la route : le hub MCP
    repond sur `/mcp`, les sondes de sante et les routes d'API passent par lui,
    et un appel `provider:` est le fait du routeur de modeles.
    """
    cible = (target or "").lower()
    acte = (action or "").lower()
    if acte.startswith("provider:") and "llm_router" in organs:
        return "llm_router"
    if "/mcp" in cible and "hub" in organs:
        return "hub"
    if ("/health" in cible or "/api/" in cible) and "hub" in organs:
        return "hub"
    return None


def _organ_activity(name: str, hormones: dict[str, float], rag: dict,
                    embed_pct: float | None, trafic: dict[str, int] | None = None) -> float:
    """Calcule activite [0..1] d un organe selon hormones + signaux runtime.

    `trafic` -- requetes observees par organe sur la fenetre. Quand il est VIDE
    (source illisible), on n'ajoute rien : on ne deduit pas une activite nulle
    d'une mesure qu'on n'a pas pu prendre.
    """
    base = 0.3  # idle baseline
    if trafic:
        # Part du trafic total revenant a cet organe, bornee : un organe tres
        # sollicite monte vers 1, les autres restent lisibles. Le logarithme
        # evite qu'un seul organe bavard ecrase toute la carte.
        _n = trafic.get(name, 0)
        if _n > 0:
            base += min(0.5, math.log10(1 + _n) / 4.0)
    h_adr = hormones.get("adrenaline", 0.0)
    h_cor = hormones.get("cortisol", 0.0)
    h_dop = hormones.get("dopamine", 0.0)

    # Adrenaline boost organes de defense / action
    if name in ("firewall", "membrane", "guardian", "silo_security", "watchdog"):
        base += h_adr * 0.6
    # Cortisol boost router / planner (resource pressure)
    if name in ("llm_router", "hub", "thalamus", "cortex"):
        base += h_cor * 0.5
    # Dopamine boost recompense / RAG (consolidation, decision OK)
    if name in ("hippocampus", "rag_cortex", "brain_worker"):
        base += h_dop * 0.4

    # Activite RAG si beaucoup de chunks recents
    # embed_pct inconnu -> AUCUN bonus d'activite. On ne deduit rien d'une
    # mesure absente, dans un sens comme dans l'autre.
    if name == "brain_worker" and embed_pct is not None and embed_pct < 90:
        base += (90 - embed_pct) / 100.0  # plus de pending = plus actif

    return min(1.0, max(0.0, base))


def _organ_color(activity: float, hormones: dict[str, float]) -> str:
    """Couleur RGB selon activite + dominante hormonale."""
    h_adr = hormones.get("adrenaline", 0.0)
    h_dop = hormones.get("dopamine", 0.0)
    h_cor = hormones.get("cortisol", 0.0)
    # Adrenaline = rouge, dopamine = vert, cortisol = orange, base = bleu
    if h_adr > 0.5:
        # Rouge alarme
        r = int(220 - activity * 30)
        g = int(80 - activity * 40)
        b = int(80 - activity * 40)
    elif h_cor > 0.4:
        # Orange stress
        r = int(240 - activity * 20)
        g = int(150 - activity * 30)
        b = 60
    elif h_dop > 0.3:
        # Vert reward
        r = int(80 + activity * 30)
        g = int(200 - activity * 20)
        b = int(120 + activity * 30)
    else:
        # Bleu base / idle
        r = int(80 + activity * 60)
        g = int(140 + activity * 40)
        b = int(220 - activity * 30)
    return f"rgb({r},{g},{b})"


def _organ_health(name: str, alive_count: int, total_count: int, hormones: dict[str, float]) -> str:
    """Etiquette health : 'ok' / 'warn' / 'critical' utilisee pour CSS class."""
    if hormones.get("adrenaline", 0) > 0.7:
        return "critical"
    if hormones.get("cortisol", 0) > 0.5:
        return "warn"
    return "ok"


# Positions ANATOMIQUES dans le viewBox SVG 400x700 (anatomy.html). Les coords
# historiques de _ORGAN_LAYOUT etaient dans un espace ~900x600 -> HORS silhouette.
# Override applique dans get_anatomy_state : chaque organe sur le corps.
#   tete[x158-242 y5-105] cerveau · cou y110 · torse[x130-270 y125-350] coeur/foie ·
#   bras G/D x~105/295 muscles · jambes y>400.
_ANATOMY_XY = {
    "browser": (200, 16), "cortex": (200, 30), "hub": (200, 52),
    "thalamus": (176, 64), "hippocampus": (224, 64), "rag_cortex": (200, 82),
    "brain_worker": (160, 76), "cerebellum": (240, 84), "inspector": (200, 113),
    "firewall": (200, 134), "guardian": (252, 168), "deno_hub": (181, 184),
    "llm_router": (206, 236), "ollama": (240, 272), "ingest": (165, 264),
    "membrane": (146, 232), "rag_qualify": (200, 316), "watchdog": (250, 214),
    "silo_code": (104, 236), "silo_security": (296, 236), "silo_recon": (166, 470),
    "netcfg": (300, 288),
}

# Mapping nom-de-span (agent/action) -> organe. Premier match (ordre = priorité).
_ORGAN_KEYWORDS = [
    ("firewall", ["firewall", "prompt_guard", "canary", "preflight", "pre_flight"]),
    ("membrane", ["membrane", "egress", "postflight", "post_flight", "wrap"]),
    ("thalamus", ["thalamus", "nlu", "intent", "triage", "byte_router", "dispatch"]),
    ("hippocampus", ["hippocampus", "self_correction", "anchor", "lesson", "consolidat"]),
    ("rag_cortex", ["rag", "retriev", "hybrid", "vector", "embed_router", "qualify"]),
    ("ingest", ["ingest", "biblio", "crawl", "chunk", "watch"]),
    ("brain_worker", ["brain_worker", "embed", "npu", "bge"]),
    ("ollama", ["ollama", "local", "llamacpp", "lmstudio"]),
    ("cerebellum", ["cerebellum", "silo", "spike", "mpc", "actor"]),
    ("cortex", ["cortex", "cognitive"]),
    ("llm_router", ["router", "cascade", "llm_router", "agent_proxy", "provider", "handoff", "ask", "metabol"]),
    ("browser", ["browser", "web", "perception", "vision", "crawl_tool"]),
    ("netcfg", ["netcfg", "ssh", "network"]),
    ("hub", ["hub", "mcp_registry", "mcp_server", "tool"]),
]


def _organ_of(name: str | None, organs: dict) -> str | None:
    n = (name or "").lower()
    for organ, kws in _ORGAN_KEYWORDS:
        if organ in organs and any(k in n for k in kws):
            return organ
    return None


def _live_flows_from_spans(window_seconds: int, organs: dict) -> list:
    """Flux RÉELS organe->organe depuis audit.db (spans imbriqués span_id/parent_id).
    Mappe chaque span sur un organe, agrège les arêtes parent->enfant (count + durée).
    Vide si pas de spans -> fallback carte statique. Fail-open."""
    try:
        import sys as _s

        _s.path.insert(0, str(_ROOT / "app"))
        from nokido_agent.app.forge_audit_log import query_recent
    except Exception:
        return []
    try:
        spans = query_recent(limit=800)
    except Exception:
        return []
    now = time.time()
    by_id = {}
    for sp in spans:
        sid = sp.get("span_id")
        if sid and (now - (sp.get("ts") or 0)) <= max(window_seconds, 120) * 6:
            by_id[sid] = sp
    agg: dict[tuple, list] = {}
    for sp in by_id.values():
        pid = sp.get("parent_id")
        if not pid or pid not in by_id:
            continue
        a = _organ_of(by_id[pid].get("action") or by_id[pid].get("agent"), organs)
        b = _organ_of(sp.get("action") or sp.get("agent"), organs)
        if not a or not b or a == b:
            continue
        e = agg.setdefault((a, b), [0, 0])
        e[0] += 1
        e[1] += sp.get("duration_ms") or 0
    out = []
    for (a, b), (cnt, dur) in sorted(agg.items(), key=lambda x: -x[1][0]):
        out.append({"from": a, "to": b, "msg": f"{cnt}x", "effect": f"{dur}ms", "live": True})
    return out


def get_anatomy_state(window_seconds: int = 120) -> dict[str, Any]:
    heartbeats = _read_heartbeats(window_seconds)
    alive = [h for h in heartbeats if h["alive"]]
    rag = _rag_stats()
    # `None` se propage au lieu de se convertir en 0 : un pourcentage calcule
    # sur une mesure absente serait un chiffre invente, et il se lirait comme
    # une observation.
    embed_pct = (round(rag["embedded"] / max(rag["chunks"], 1) * 100, 1)
                 if rag.get("embedded") is not None and rag.get("chunks") else None)
    hormones = _hormones_active()
    # Trafic REEL par organe. `_ORGAN_LAYOUT` sert de reference des noms : il
    # porte les memes cles que `organs`, qui n'est pas encore construit ici.
    _trafic = _trafic_par_organe(window_seconds, _ORGAN_LAYOUT)

    organs: dict[str, dict] = {}
    for name, base in _ORGAN_LAYOUT.items():
        activity = _organ_activity(name, hormones, rag, embed_pct, _trafic)
        _xy = _ANATOMY_XY.get(name)  # repositionne sur la silhouette 400x700
        organs[name] = {
            **base,  # x, y, r, label, bio, port/module
            **({"x": _xy[0], "y": _xy[1], "r": min(int(base.get("r", 16)), 16)} if _xy else {}),
            "activity": round(activity, 3),
            "color": _organ_color(activity, hormones),
            "health": _organ_health(name, len(alive), len(heartbeats), hormones),
        }

    # Flows : RÉELS depuis les spans (audit.db) si dispo, sinon carte statique.
    _live = _live_flows_from_spans(window_seconds, organs)
    _src_flows = _live if _live else _BASE_FLOWS
    flows = []
    for f in _src_flows:
        if f["from"] in organs and f["to"] in organs:
            flows.append(
                {
                    **f,
                    "module_from": organs[f["from"]].get("label", f["from"]),
                    "module_to": organs[f["to"]].get("label", f["to"]),
                }
            )

    return {
        "ts": time.time(),
        "window_seconds": window_seconds,
        "organs": organs,
        "flows": flows,
        # MESURE OU TOPOLOGIE ? La carte servait les douze flux declares sans
        # jamais dire qu'ils n'etaient pas mesures -- un repli MUET, qui laisse
        # croire a du temps reel. Mesure du 2026-09-18 : sur huit cents evenements
        # d'audit frais, VINGT-SEPT portent un `span_id` et sept cent soixante-treize
        # designent un pere ; les paires joignables sont au nombre de ZERO, parce
        # que les requetes HTTP -- le vrai trafic -- n'emettent pas leur propre
        # identifiant. Le producteur de flux ne peut donc rien produire, et ce
        # n'est pas un defaut de la carte mais de l'emetteur.
        #
        # On le DIT, au lieu de le taire : `flows_live` vaut faux quand ce qui est
        # affiche est la topologie declaree, et `flows_reason` nomme ce qui manque.
        "flows_live": bool(_live),
        "flows_reason": (
            "flux mesures sur les spans d'audit"
            if _live else
            "topologie DECLAREE, pas une mesure : les requetes HTTP n'emettent pas "
            "de span_id, donc aucune arete parent-enfant n'est reconstituable"
        ),
        "trafic_par_organe": _trafic,
        "hormones": hormones,
        "daemons": {
            "alive": len(alive),
            "total": len(heartbeats),
            "list": heartbeats,
        },
        "rag": rag,
        "embed_pct": embed_pct,
        "recent_lessons": _recent_lessons(5),
    }


if __name__ == "__main__":
    import sys

    w = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    print(json.dumps(get_anatomy_state(w), ensure_ascii=False, default=str))
