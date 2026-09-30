"""
forge_hormones.py — Système endocrinien typé Nokido.

Phase 9 (2026-05-24) régulation hormonale. Le pub/sub Deno existe deja
(nervous_system.ts), mais le hub Python n'avait pas de taxonomie d'event
typée avec demi-vie et récepteurs ciblés. Sans typage, un event "urgent"
ressemble a un event "info" pour les subscribers.

Analogie biologique : adrenaline (court, urgence) != cortisol (long, stress
chronique) != insulin (homeostasie continue) != dopamine (recompense) !=
melatonin (cycle veille/sommeil) != tsh (regulation thyroide).

Stockage in-RAM (single-process). Cleanup automatique des hormones
expirees (now - released_ts > halflife_s * 3). Pas de persistence DB
voulu : c'est volatile par nature.

API publique :
    release(hormone, level=1.0, payload={}, receptors=[]) -> hormone_id
    active(hormone=None) -> [{...}]   # filtre expirees
    receptors_for(receptor_role) -> [{...}]  # tous les events ciblant ce role
    cleanup() -> int

API HTTP exposee via hub :8766 :
    POST /api/hormones/release    body = {hormone, level, payload, receptors}
    GET  /api/hormones/active     [?hormone=...]
    GET  /api/hormones/receptors/{role}
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("forge_hormones")

# Taxonomie canonique (calque biologie). half_life en SECONDES.
HORMONES: dict[str, dict[str, Any]] = {
    "adrenaline": {
        "half_life_s": 60,
        "purpose": "urgence immediate — TDR, BSOD imminent, signal incident critique",
        "typical_level": 1.0,
    },
    "cortisol": {
        "half_life_s": 1800,  # 30 min
        "purpose": "stress chronique — quotas API epuises, restart >5 service en 1h",
        "typical_level": 0.5,
    },
    "insulin": {
        "half_life_s": 300,  # 5 min
        "purpose": "homeostasie ressources — RAM/CPU descend, signal apaisement",
        "typical_level": 0.3,
    },
    "dopamine": {
        "half_life_s": 600,  # 10 min
        "purpose": "recompense — test PASS, scorecard PROMOTED, deploy succes",
        "typical_level": 0.7,
    },
    "tsh": {
        "half_life_s": 3600,  # 1h
        "purpose": "regulation cycle — vectorisation backlog, embedding queue, rebuild",
        "typical_level": 0.5,
    },
    "melatonin": {
        "half_life_s": 7200,  # 2h
        "purpose": "cycle circadien — entree mode sommeil/NREM, baisse activite",
        "typical_level": 0.4,
    },
    "leptin": {
        "half_life_s": 900,  # 15 min
        "purpose": "satiete — mailbox plein, embed buffer plein, throttle producers",
        "typical_level": 0.6,
    },
    "oxytocin": {
        "half_life_s": 1200,  # 20 min
        "purpose": "cooperation — agent handoff reussi, multi-agent consensus",
        "typical_level": 0.5,
    },
}

# Etat in-RAM : {hormone_id: {hormone, level, released_ts, expires_at, payload, receptors}}
_ACTIVE: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()

# Phase 12 — bus event-driven : subscribers asyncio.Queue dans le hub.
# release() push sur tous les subscribers connectes. SSE endpoint
# /api/hormones/stream itere son queue dedie. Cross-process : le daemon
# listener consomme via HTTP SSE (recv bloquant, zero polling).
# Liste protegee par _LOCK car release() peut etre appele d'un thread.
_SUBSCRIBERS: list = []  # list[asyncio.Queue] — typage tardif pour eviter import


def subscribe_event_queue():
    """Cree et enregistre une asyncio.Queue subscriber. Appel depuis handler SSE."""
    import asyncio as _asyncio

    q: _asyncio.Queue = _asyncio.Queue(maxsize=200)
    with _LOCK:
        _SUBSCRIBERS.append(q)
    return q


def unsubscribe(q) -> None:
    with _LOCK:
        try:
            _SUBSCRIBERS.remove(q)
        except ValueError:
            pass


import re as _re_pii


# Phase 33 (2026-05-25) — patterns redact PII basiques pour SSE broadcast.
# Critique Plan-SPOF passe 2 : payload SSE non-filtre = leak PII vers tout
# subscriber (browser, agent compromis). Redact best-effort regex.
_PII_PATTERNS = [
    # Paths Windows utilisateur
    (_re_pii.compile(r"C:\\Users\\[^\\/'\":\n]+", _re_pii.IGNORECASE), "<USER_PATH>"),
    (_re_pii.compile(r"/home/[^/'\":\n]+", _re_pii.IGNORECASE), "<USER_PATH>"),
    # Tokens base64url longs (probable JWT, API key)
    (_re_pii.compile(r"\b[A-Za-z0-9_-]{40,}\b"), "<TOKEN>"),
    # Emails
    (_re_pii.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "<EMAIL>"),
    # IPs privees (RFC1918 + loopback)
    (_re_pii.compile(r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168|127)(?:\.\d{1,3}){3}\b"), "<PRIVATE_IP>"),
    # Filenames sensibles
    (_re_pii.compile(r"\b[\w.-]*(?:\.env|\.credentials|\.key|\.pem|\.p12)\b", _re_pii.IGNORECASE), "<SECRET_FILE>"),
]
_REDACT_KEY_DENYLIST = {
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "credential",
    "auth",
}


def _redact_value(v):
    if isinstance(v, str):
        for pat, repl in _PII_PATTERNS:
            v = pat.sub(repl, v)
        return v
    if isinstance(v, dict):
        return _redact_dict(v)
    if isinstance(v, list):
        return [_redact_value(x) for x in v]
    return v


def _redact_dict(d: dict) -> dict:
    """Recursive redact. Keys denylist -> '<REDACTED>'. Values regex patterns."""
    out: dict = {}
    for k, v in d.items():
        k_low = str(k).lower()
        if any(deny in k_low for deny in _REDACT_KEY_DENYLIST):
            out[k] = "<REDACTED>"
        else:
            out[k] = _redact_value(v)
    return out


def _push_to_subscribers(rec: dict) -> None:
    """Best-effort push (non-blocking) avec redact PII Phase 33.
    Si une queue est pleine, l'event est drop pour ce subscriber."""
    if not _SUBSCRIBERS:
        return
    # Redact payload AVANT push (copie defensive, l'original _ACTIVE garde tout)
    try:
        safe_rec = {**rec, "payload": _redact_dict(rec.get("payload") or {})}
    except Exception:
        safe_rec = rec  # fallback fail-safe
    with _LOCK:
        subs = list(_SUBSCRIBERS)
    for q in subs:
        try:
            q.put_nowait(safe_rec)
        except Exception:
            pass  # full or no loop, skip


def _expires_at(hormone: str, released_ts: float) -> float:
    spec = HORMONES.get(hormone, {"half_life_s": 60})
    # Convention : event "actif" tant que age < 3 * half_life (decay > 87%).
    return released_ts + 3 * spec["half_life_s"]


def release(
    hormone: str,
    level: float = 1.0,
    payload: dict | None = None,
    receptors: list[str] | None = None,
) -> dict[str, Any]:
    """Releve un event hormonal. Retourne le record cree."""
    if hormone not in HORMONES:
        return {
            "ok": False,
            "error": f"unknown hormone '{hormone}'",
            "known": sorted(HORMONES.keys()),
        }
    now = time.time()
    hid = uuid.uuid4().hex[:12]
    rec = {
        "id": hid,
        "hormone": hormone,
        "level": float(max(0.0, min(1.0, level))),
        "released_ts": now,
        "expires_at": _expires_at(hormone, now),
        "half_life_s": HORMONES[hormone]["half_life_s"],
        "purpose": HORMONES[hormone]["purpose"],
        "payload": payload or {},
        "receptors": list(receptors or []),
    }
    with _LOCK:
        _ACTIVE[hid] = rec
    logger.info("release %s id=%s level=%.2f receptors=%s", hormone, hid, rec["level"], rec["receptors"])
    # Phase 12 push event-driven (non-bloquant best-effort)
    try:
        _push_to_subscribers(rec)
    except Exception:
        pass
    # Phase 12 persist si critique (survie restart hub). Seules les hormones
    # de stress/urgence a haut niveau sont persistees.
    if hormone in ("adrenaline", "cortisol") and rec["level"] >= 0.9:
        try:
            from nokido_agent.app.forge_critical_events import persist as _persist

            _persist("hormone", "critical", rec)
        except Exception:
            pass
    # Phase 25 (2026-05-25) — dual-write vers forge_endocrine (SQLite autorité).
    # Consensus 4-voix LLM : endocrine = autorité long-terme (persiste reboot,
    # consume par homeostasis_orchestrator). hormones reste view in-RAM + SSE
    # push (transport). Migration progressive : ce dual-write garantit que
    # tous les events hormonaux atterrissent aussi dans SQLite sans casser
    # les consumers SSE existants. Phase 28+ : retirer state local, hormones
    # devient view sur endocrine.
    try:
        from nokido_agent.app.forge_endocrine import release as _endo_release

        # Mapping signature : forge_endocrine accepte (hormone, level, ttl_s,
        # source, reason, meta). Récupère source depuis premier receptor ou
        # 'hormones_module', meta = full payload+receptors pour traçabilité.
        _src = rec["receptors"][0] if rec["receptors"] else "hormones_module"
        _meta = {
            "payload": rec.get("payload", {}),
            "receptors": rec.get("receptors", []),
            "hormones_id": hid,
            "half_life_s": rec["half_life_s"],
        }
        _endo_release(hormone, rec["level"], ttl_s=int(3 * rec["half_life_s"]), source=_src, reason="", meta=_meta)
    except Exception as exc:
        logger.debug("endocrine dual-write skipped: %s", exc)
    return {"ok": True, **rec}


def _decay_level(rec: dict[str, Any], now: float) -> float:
    """Exponential decay : level * 0.5^(elapsed / half_life)."""
    elapsed = now - rec["released_ts"]
    if elapsed <= 0:
        return rec["level"]
    return rec["level"] * (0.5 ** (elapsed / rec["half_life_s"]))


def cleanup() -> int:
    """Removes expired hormones. Returns count purged."""
    now = time.time()
    n = 0
    with _LOCK:
        expired = [k for k, v in _ACTIVE.items() if v["expires_at"] < now]
        for k in expired:
            del _ACTIVE[k]
            n += 1
    return n


def active(hormone: str | None = None, include_endocrine: bool = True) -> list[dict[str, Any]]:
    """Phase 31 step 2 : merge state local in-RAM + scan endocrine SQLite.
    include_endocrine=True (default) lit aussi forge_endocrine.scan() pour
    voir les hormones survivantes après restart hub (persistées Phase 25 dual-write).
    Dedupe par hormone_name : in-RAM gagne si meme hormone presente."""
    cleanup()
    now = time.time()
    out: list[dict[str, Any]] = []
    seen_hormones: set[str] = set()
    with _LOCK:
        for rec in _ACTIVE.values():
            if hormone and rec["hormone"] != hormone:
                continue
            cur_level = _decay_level(rec, now)
            r = dict(rec)
            r["current_level"] = round(cur_level, 4)
            r["age_s"] = round(now - rec["released_ts"], 1)
            r["_source"] = "ram"
            out.append(r)
            seen_hormones.add(rec["hormone"])
    if include_endocrine:
        try:
            from nokido_agent.app.forge_endocrine import scan as _endo_scan

            endo_readings = _endo_scan()
            for endo_r in endo_readings:
                # Skip si meme hormone deja vue in-RAM (in-RAM = source plus recente)
                if endo_r.name in seen_hormones:
                    continue
                if hormone and endo_r.name != hormone:
                    continue
                if endo_r.expired:
                    continue
                out.append(
                    {
                        "id": f"endo_{endo_r.name}",
                        "hormone": endo_r.name,
                        "level": endo_r.fresh_level,
                        "current_level": round(endo_r.level, 4),
                        "released_ts": now - endo_r.age_s,
                        "age_s": endo_r.age_s,
                        "half_life_s": endo_r.half_life_s,
                        "ttl_s": endo_r.ttl_s,
                        "payload": {"source": endo_r.source, "reason": endo_r.reason},
                        "receptors": [],
                        "_source": "endocrine_sqlite",
                    }
                )
        except Exception:
            pass  # endocrine indispo = fallback in-RAM seul
    out.sort(key=lambda r: r["released_ts"], reverse=True)
    return out


def receptors_for(role: str) -> list[dict[str, Any]]:
    """Retourne les hormones actives ciblant ce role precis."""
    role_l = role.strip().lower()
    return [r for r in active() if any(t.lower() == role_l for t in r["receptors"])]


def system_state() -> dict[str, Any]:
    """Snapshot global — utile pour TUI / decisions agent-level."""
    cleanup()
    by_hormone: dict[str, list[float]] = {}
    now = time.time()
    with _LOCK:
        for rec in _ACTIVE.values():
            lv = _decay_level(rec, now)
            by_hormone.setdefault(rec["hormone"], []).append(lv)
    return {
        "ts": now,
        "active_count": sum(len(v) for v in by_hormone.values()),
        "by_hormone": {
            h: {"count": len(lvs), "sum_level": round(sum(lvs), 3), "max_level": round(max(lvs), 3)}
            for h, lvs in by_hormone.items()
        },
        "known_hormones": sorted(HORMONES.keys()),
    }


if __name__ == "__main__":
    # smoke test
    import json

    release("adrenaline", 1.0, {"event": "test"}, ["agt_security"])
    release("cortisol", 0.7, {"event": "quota_drain"}, ["agt_router", "agt_planner"])
    print(json.dumps(system_state(), indent=2))
    print(json.dumps(active("adrenaline"), indent=2))
