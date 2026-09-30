"""forge_goap_intuition.py — heuristique d'INTUITION (Système 1) pour le planner GOAP.

Remplace le tri par coût STATIQUE du BFS par un score intuitif = blend de signaux
associatifs/structurels, AVANT l'épreuve du REPL (élague l'explosion combinatoire).

Inspiration neuro (Kahneman/Damasio + signal/bruit) :
  - L'intuition vraie est SILENCIEUSE et NETTE ; le bruit (anxiété/cortisol) est PLAT
    et persistant. On code ça par une PORTE signal/bruit : `confidence` = netteté de la
    marge (top action très détachée → on fait confiance et on élague ; distribution plate
    → rumination/faux-positifs → NE PAS faire confiance, élargir la recherche).
  - Marqueur somatique = score appris qui pré-sélectionne avant l'analyse.

Providers INJECTABLES (dégradation gracieuse) :
  - vec   : gut-feeling associatif (défaut = affinité lexicale rapide, 0 dép/réseau ;
            remplaçable par RAG cosine / embeddings).
  - graph : intuition topologique (PPR sur graphe outils/deps) — hook.
  - value : value_net AlphaGo-style (forge_value_net.predict_value sur un embedding) — hook ;
            NB: nécessite un embed d'état ALIGNÉ sur les traces d'entraînement (sinon bruit,
            que la porte signal/bruit absorbe de toute façon).

Tout provider absent/KO est ignoré → au pire l'affinité lexicale seule. Best-effort partout.
"""

from __future__ import annotations

import math
import re

DEFAULT_WEIGHTS = {"vec": 1.0, "graph": 0.7, "value": 1.2}
_TOK = re.compile(r"[a-zA-Z_]{3,}")


def _tokens(s: str) -> set[str]:
    return set(_TOK.findall((s or "").lower()))


def keyword_affinity(state_text: str, action) -> float:
    """Signal associatif léger (gut-feeling lexical) : recouvrement cosine-like des tokens
    entre l'énoncé/état et le profil de l'action. Rapide, 0 réseau, 0 embedder."""
    st = _tokens(state_text)
    profile = f"{getattr(action, 'name', '')} {getattr(action, 'hub_tool', '')} {getattr(action, 'hub_args', '')}"
    at = _tokens(profile)
    if not st or not at:
        return 0.0
    return len(st & at) / math.sqrt(len(st) * len(at))


def _confidence(scores: list[float]) -> float | None:
    """PORTE signal/bruit — TROIS états, jamais deux (constitution du 2026-09-05).

    1.0 = top très détaché (intuition NETTE → élaguer dur) ; 0.0 = distribution PLATE
    effectivement MESURÉE (rumination/bruit → élargir) ; None = marge NON MESURABLE,
    c'est-à-dire UNKNOWN.

    None couvre deux cas qui n'ont aucune marge à offrir : aucun score positif (on n'a
    rien vu) et un seul candidat positif (il n'a pas de second, donc pas d'écart). Ni
    l'un ni l'autre n'est un signal plat, et surtout aucun n'est une certitude — rendre
    1.0 sur un candidat unique faisait élaguer dur ET désarmait le réflexe doute→oracle
    chez l'appelant (`forge_goap_hub_bridge.plan`). UNKNOWN se traite du côté PRUDENT.
    """
    pos = sorted((s for s in scores if s > 0), reverse=True)
    if len(pos) < 2 or pos[0] <= 0:
        return None
    top, second = pos[0], pos[1]
    return max(0.0, min(1.0, (top - second) / top))


def intuition_rank(state_text: str, actions, *, providers=None, weights=None):
    """Retourne (scored, confidence) où scored = [(action, score, breakdown)] trié desc.
    providers = {'vec'|'graph'|'value': callable(state_text, action) -> float}. Best-effort."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    providers = dict(providers or {})
    providers.setdefault("vec", keyword_affinity)  # garantit toujours au moins le signal lexical

    scored = []
    for a in actions:
        bd: dict[str, float] = {}
        for key in ("vec", "graph", "value"):
            fn = providers.get(key)
            if fn is None:
                continue
            try:
                bd[key] = float(fn(state_text, a))
            except Exception:  # noqa: BLE001 — un signal KO ne casse jamais l'intuition
                continue
        score = sum(w.get(k, 1.0) * v for k, v in bd.items())
        scored.append((a, score, bd))
    scored.sort(key=lambda t: -t[1])
    return scored, _confidence([s for _, s, _ in scored])


def make_value_provider(*, embed_fn, root=None):
    """Hook value_net : embed_fn(text)->np.ndarray ALIGNÉ sur les traces, puis predict_value.
    Retourne None si forge_value_net indisponible (dégradation). La porte signal/bruit absorbe
    le bruit si l'embedding n'est pas parfaitement aligné."""
    try:
        import sys
        from pathlib import Path

        _app = str(Path(root or Path(__file__).resolve().parent))
        if _app not in sys.path:
            sys.path.insert(0, _app)
        from nokido_agent.app.forge_value_net import predict_value
    except Exception:  # noqa: BLE001
        return None

    def _value(state_text: str, action) -> float:
        text = f"{state_text} || {getattr(action, 'name', '')} {getattr(action, 'hub_args', '')}"
        return float(predict_value(embed_fn(text)))

    return _value


_EMBED_FN = None
_EMBED_TRIED = False


def default_embed_fn():
    """Embedder 384D (all-MiniLM-L6-v2) ALIGNÉ sur les traces legacy du value_net (IN_DIM=384).
    Singleton lazy. None si `sentence_transformers` absent du runtime → value_net reste DORMANT
    (cas actuel de laforge_py314). S'auto-active dès que MiniLM est installé. NB: même présent,
    l'alignement repr (états-de-traces vs contextes-action GOAP) est lâche → la porte signal/bruit
    discount ce signal tant que le value_net n'est pas RÉ-ENTRAÎNÉ sur des traces GOAP courantes."""
    global _EMBED_FN, _EMBED_TRIED
    if _EMBED_TRIED:
        return _EMBED_FN
    _EMBED_TRIED = True
    import os as _os

    if not _os.environ.get("LAFORGE_GOAP_VALUE_NET"):
        _EMBED_FN = None  # OPT-IN : évite la taxe d'import ST/torch (~5s) quand value_net inutilisé
        return None
    try:
        import numpy as _np
        from sentence_transformers import SentenceTransformer

        # local_files_only : cache-ou-rien. Le planner (sandbox offline) ne touche JAMAIS
        # le réseau → fail-fast si modèle non caché (pas de HEAD HF, pas de 5 retries).
        _m = SentenceTransformer("all-MiniLM-L6-v2", device="cpu", local_files_only=True)
        _EMBED_FN = lambda text: _np.asarray(_m.encode([text])[0], dtype="float32")  # noqa: E731
    except Exception:  # noqa: BLE001
        _EMBED_FN = None
    return _EMBED_FN


_HF_MINILM_URL = ("https://router.huggingface.co/hf-inference/models/"
                  "sentence-transformers/all-MiniLM-L6-v2/pipeline/feature-extraction")


def online_embed_fn():
    """Embedder 384D ONLINE via HF Inference — all-MiniLM-L6-v2 = le MODÈLE EXACT du value_net
    (aligné), sans download local ni combat offline. Nécessite réseau (sandbox-online) + HF_TOKEN.
    None si token/réseau absent. NB: round-trip réseau par appel → réservé au planning non-fast-path
    ou au RÉ-ENTRAÎNEMENT batch des traces, pas au System-1 par-action serré."""
    try:
        import os as _os
        import sys as _sys
        from pathlib import Path as _P

        _app = str(_P(__file__).resolve().parent)
        if _app not in _sys.path:
            _sys.path.insert(0, _app)
        from nokido_agent.app.forge_machine_vault import vault_get

        tok = vault_get("HF_TOKEN") or _os.environ.get("HF_TOKEN") or ""
        if not tok:
            return None
    except Exception:  # noqa: BLE001
        return None
    import json as _json
    import urllib.request as _u

    import numpy as _np

    def _embed(text):
        req = _u.Request(_HF_MINILM_URL, data=_json.dumps({"inputs": text}).encode(),
                         headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        emb = _json.loads(_u.urlopen(req, timeout=20).read())
        flat = emb if isinstance(emb[0], (int, float)) else emb[0]
        return _np.asarray(flat, dtype="float32")

    return _embed


def resolve_embed_fn():
    """Embedder 384D selon LAFORGE_GOAP_VALUE_NET : 'online'=HF MiniLM (réseau) |
    'local'/'1'=MiniLM caché | absent=None. Partagé par les providers ET le trace-recorder."""
    import os as _os

    mode = (_os.environ.get("LAFORGE_GOAP_VALUE_NET") or "").lower()
    if not mode:
        return None
    # CHECKPOINT-TIED : l'embedder DOIT matcher l'espace d'entrainement du value_net.
    # La dim suit la cognition (forge_state_encoder.STATE_DIM = env LAFORGE_STATE_DIM) :
    #   384 (defaut)  -> MiniLM legacy (espace value_net 384d actuel, inchange).
    #   != 384 (post-retrain BGE-M3) -> embed_router via encode_state (MEME espace que le RAG).
    try:
        import sys as _sys
        from pathlib import Path as _P
        _app = str(_P(__file__).resolve().parent)
        if _app not in _sys.path:
            _sys.path.insert(0, _app)
        from nokido_agent.app.forge_state_encoder import STATE_DIM as _DIM
    except Exception:  # noqa: BLE001
        _DIM = 384
    if _DIM != 384:
        try:
            import numpy as _np
            from nokido_agent.app.forge_state_encoder import encode_state as _enc

            return lambda text: _np.asarray(_enc(text, dim=_DIM), dtype="float32")  # noqa: E731
        except Exception:  # noqa: BLE001
            return None
    if mode == "online":
        return online_embed_fn()
    if mode in ("1", "local", "true"):
        return default_embed_fn()
    return None


def make_default_providers(*, embed_fn=None, graph_fn=None, root=None) -> dict:
    """vec=lexical TOUJOURS ON. value selon resolve_embed_fn (online/local/off). graph si graph_fn."""
    providers = {"vec": keyword_affinity}
    ef = embed_fn if embed_fn is not None else resolve_embed_fn()
    if ef is not None:
        v = make_value_provider(embed_fn=ef, root=root)
        if v is not None:
            providers["value"] = v
    if graph_fn is not None:
        providers["graph"] = graph_fn
    return providers


def record_trajectory_step(state_text, action, next_state_text, success, *,
                           embed_fn=None, task_type="goap", record_fn=None):
    """KEYSTONE self-play : persiste une transition GOAP (state_t, action, state_t1, success)
    dans execution_traces.db → corpus AMI (value/policy/cost nets, trace_mining, SFT futur).
    Embed best-effort ONLINE aligné (HF MiniLM = même espace que les nets) ; sans embedder →
    trace SANS emb (toujours minable + backfillable). Best-effort total : ne lève JAMAIS."""
    ef = embed_fn if embed_fn is not None else resolve_embed_fn()
    se = st1 = None
    if ef is not None:
        try:
            se, st1 = ef(state_text), ef(next_state_text)
        except Exception:  # noqa: BLE001
            se = st1 = None
    rec = record_fn
    if rec is None:
        try:
            import sys as _sys
            from pathlib import Path as _P

            _app = str(_P(__file__).resolve().parent)
            if _app not in _sys.path:
                _sys.path.insert(0, _app)
            from nokido_agent.app.forge_execution_tracer import record_trace as rec
        except Exception:  # noqa: BLE001
            return None
    try:
        cb = float(action.get("cost", 1.0)) if isinstance(action, dict) else 1.0
        return rec(se, action, st1, cb, 0.0 if success else cb, task_type, bool(success))
    except Exception:  # noqa: BLE001
        return None
