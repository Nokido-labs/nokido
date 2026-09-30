#!/usr/bin/env python3
"""forge_recon_breaker.py — coupe-circuit COMPORTEMENTAL anti-fuite-tokens (transients).

Capte les recon FINES (read/grep/glob/Agent-Explore) sur le code Nokido et, au-delà
d'un seuil PAR SESSION, FORCE la délégation locale au lieu de laisser un client cloud
boucler (cf. fuite réelle 92k tokens cloud, 2026-06-20 : 31 reads/greps + Agent(Explore)
là où une seule recon LOCALE suffisait).

Partagé par DEUX étages (DRY, anti-dup) — c'est l'analyse TEMPORELLE qui manquait, les
gardes existants (forge_videur ring/RBAC par-appel, forge_lane_admission 1-job-lourd-par-lane)
ne comptent PAS les recon répétées :
  - client hook  : tools/forge_tool_gate.py  (PreToolUse Claude/Gemini)  -> verdict()
  - hub serveur  : app/forge_mcp_registry.dispatch (universel, tout client MCP) -> verdict()

Token-bucket disque par (session, kind), fenêtre glissante. Fail-open partout (un bug du
breaker ne doit JAMAIS casser un flux légitime). Bucket dans C:/tmp (écrivable owner ET
sandbox — le hook tourne owner, le hub tourne LaForgeSbxOffline ; chemin commun).
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : coupe-circuit comportemental anti-fuite de tokens"  # organe declare le 2026-09-06 (audit de raccordement)

import hashlib
import json
import time
from pathlib import Path

_DIR = Path("C:/tmp/nokido_recon_buckets")

# Seuils : les N premières recon Nokido passent (flux/trivial préservé — directive
# historique « ne pas tuer l'intelligence »), au-delà on bascule nudge puis deny.
_SOFT = 3          # n <= SOFT : allow ; SOFT < n <= HARD : nudge (conseil non bloquant)
_HARD = 6          # n  > HARD : deny (force la délégation locale)
_WINDOW_S = 900    # fenêtre glissante 15 min par (session, kind)

#: kinds soumis au breaker
RECON_KINDS = ("read", "search", "recon_agent")

#: directive renvoyée au client (honeypot : pointe l'outil de délégation locale).
HINT = (
    "recon lourde détectée -> DÉLÈGUE en LOCAL : outil hub `forge_deep_explore` "
    "{intent, target, breadth} (recon souveraine, 0 token cloud, renvoie une synthèse "
    "condensée), ou `forge_local_explore`. Tu es un CLIENT de Nokido, pas l'exécuteur."
)


def _key(session: str, kind: str) -> Path:
    h = hashlib.sha1(f"{session}:{kind}".encode("utf-8")).hexdigest()[:16]
    return _DIR / f"{h}.json"


def hit(session: str, kind: str) -> int:
    """Incrémente le compteur (session, kind) dans la fenêtre glissante et le renvoie.

    Fail-open -> 0 (le verdict traitera 0 comme 'allow')."""
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        p = _key(session or "UNKNOWN", kind)
        now = time.time()
        hits: list[float] = []
        if p.exists():
            try:
                hits = [float(t) for t in json.loads(p.read_text(encoding="utf-8"))]
            except Exception:
                hits = []
        hits = [t for t in hits if now - t < _WINDOW_S]
        hits.append(now)
        p.write_text(json.dumps(hits[-64:]), encoding="utf-8")
        return len(hits)
    except Exception:
        return 0


def verdict(session: str, kind: str, is_nokido: bool) -> tuple[str, str, int]:
    """('allow' | 'nudge' | 'deny', reason, count).

    N'agit QUE sur la recon de code Nokido. Agent(Explore)/Task sur Nokido = recon
    cloud massive -> deny direct (le coût était précisément là)."""
    if kind not in RECON_KINDS or not is_nokido:
        return ("allow", "", 0)
    n = hit(session, kind)
    if kind == "recon_agent":
        return ("deny", f"Agent(Explore) sur code Nokido = recon cloud facturée. {HINT}", n)
    if n > _HARD:
        return ("deny", f"{n} recon/{kind} Nokido en {_WINDOW_S // 60} min. {HINT}", n)
    if n > _SOFT:
        return ("nudge", f"recon Nokido répétée ({n}/{kind}) — pense `forge_deep_explore`.", n)
    return ("allow", "", n)


def is_nokido_args(args) -> bool:
    """Heuristique : les arguments d'outil visent-ils le code/système Nokido ?"""
    try:
        t = " ".join(str(v) for v in (args or {}).values()).lower()
    except Exception:
        return False
    return ("laforge" in t) or ("forge_" in t) or ("script python ia" in t)


# --- Variante IN-MEMORY (hub : process long-vécu, évite WORKSPACE_GUARD / FS) ---
_MEM: dict = {}


def hit_mem(key: str, kind: str) -> int:
    """Compteur recon EN MÉMOIRE process (pour le hub). Même fenêtre glissante."""
    import time as _t
    now = _t.time()
    k = f"{key}:{kind}"
    h = [t for t in _MEM.get(k, []) if now - t < _WINDOW_S]
    h.append(now)
    _MEM[k] = h[-64:]
    return len(h)


def verdict_mem(key: str, kind: str, is_nokido: bool) -> tuple[str, str, int]:
    """Comme verdict() mais compteur EN MÉMOIRE (hub-side, universel tout client MCP)."""
    if kind not in RECON_KINDS or not is_nokido:
        return ("allow", "", 0)
    n = hit_mem(key or "UNKNOWN", kind)
    if kind == "recon_agent":
        return ("deny", f"Agent(Explore) sur code Nokido = recon cloud. {HINT}", n)
    if n > _HARD:
        return ("deny", f"{n} recon/{kind} Nokido en {_WINDOW_S // 60} min. {HINT}", n)
    if n > _SOFT:
        return ("nudge", f"recon Nokido répétée ({n}/{kind}).", n)
    return ("allow", "", n)


def reset(session: str) -> int:
    """Purge les buckets d'une session (ex. après une délégation réussie). -> nb purgés."""
    cnt = 0
    try:
        for kind in RECON_KINDS:
            p = _key(session or "UNKNOWN", kind)
            if p.exists():
                p.unlink()
                cnt += 1
    except Exception:
        pass
    return cnt
