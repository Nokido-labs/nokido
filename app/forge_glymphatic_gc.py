"""
forge_glymphatic_gc.py — Maintenance NREM3 inspiree du systeme glymphatique.

Phase 11 (2026-05-24). Pendant le sommeil profond (NREM3), le cerveau
declenche le systeme glymphatique : cellules gliales se contractent,
liquide cephalo-rachidien lave les toxines (beta-amyloides). Equivalent
logiciel = SQLite VACUUM + rotate logs + cache LRU clear.

Declenche par supervisor.ts circadianLoop quand phase NREM3 atteinte
(POST /api/maintenance/gc), OU manuellement (admin token).

Operations (dans l'ordre, tolerantes) :
  1. SQLite VACUUM sur embeddings.db (recupere espace + defrag pages)
  2. Rotate logs > LOG_MAX_BYTES (truncate keep last N MB)
  3. Cache LRU clear (graph, RAG, hormones expired)
  4. Release(melatonin level=0.6 receptors=['supervisor', 'autonomy'])

Returns dict {ok, duration_s, steps:[{name, ok, info}]}.
"""

from __future__ import annotations

import logging
import os
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

logger = logging.getLogger("forge_glymphatic_gc")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "RAG" / "embeddings.db"
LOG_DIR = ROOT / "sandbox"
LOG_MAX_BYTES = 50 * 1024 * 1024  # 50 MB par log
LOG_KEEP_BYTES = 10 * 1024 * 1024  # garde derniers 10 MB


def _vacuum_db() -> dict[str, Any]:
    """Phase 17 (2026-05-24) refactor : remplace full VACUUM (exclusive lock + doublement
    espace disque + 30s+ block sur 8GB DB) par checkpoint WAL TRUNCATE + incremental_vacuum.
    Critique 5-voix LLM : full VACUUM pendant essentials actifs (NokidoOllama lit RAG)
    = SQLITE_BUSY cascade -> adrenaline -> paradoxe NREM3 (sommeil interrompu par stress).
    Nouveau pattern non-bloquant pour readers."""
    if not DB_PATH.exists():
        return {"name": "vacuum_safe", "ok": False, "info": "db not found"}
    t0 = time.monotonic()
    size_before = DB_PATH.stat().st_size
    steps: list[str] = []
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
        # Verifie + active WAL mode (idempotent)
        cur = conn.execute("PRAGMA journal_mode;")
        current_mode = (cur.fetchone() or ["?"])[0]
        steps.append(f"journal_mode={current_mode}")
        if str(current_mode).lower() != "wal":
            conn.execute("PRAGMA journal_mode=WAL;")
            steps.append("wal_enabled")
        # Checkpoint TRUNCATE : merge WAL -> main + truncate WAL file. Readers
        # NON-bloques (mode passive sans wait). Si concurrent writes, retry.
        cur = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        ck = cur.fetchone() or [None, None, None]
        steps.append(f"checkpoint busy={ck[0]} log_pages={ck[1]} ckpt_pages={ck[2]}")
        # Active auto_vacuum=INCREMENTAL si pas deja set (one-shot, persistant)
        cur = conn.execute("PRAGMA auto_vacuum;")
        av = (cur.fetchone() or [0])[0]
        # 0=NONE, 1=FULL, 2=INCREMENTAL
        if av != 2:
            steps.append(f"auto_vacuum={av} (NOT INCREMENTAL — full VACUUM needed once)")
        else:
            # Recupere des pages libres sans rewriter toute la DB (non-bloquant pour readers)
            cur = conn.execute("PRAGMA incremental_vacuum(1000);")
            steps.append("incremental_vacuum(1000) done")
        conn.close()
    except sqlite3.Error as exc:
        return {
            "name": "vacuum_safe",
            "ok": False,
            "info": f"sqlite: {exc}",
            "steps": steps,
            "size_before_mb": round(size_before / 1024 / 1024, 1),
        }
    size_after = DB_PATH.stat().st_size
    return {
        "name": "vacuum_safe",
        "ok": True,
        "duration_s": round(time.monotonic() - t0, 2),
        "steps": steps,
        "size_before_mb": round(size_before / 1024 / 1024, 1),
        "size_after_mb": round(size_after / 1024 / 1024, 1),
        "freed_mb": round((size_before - size_after) / 1024 / 1024, 1),
        "note": "non-blocking for readers. Full VACUUM doit etre fait manuellement hors NREM3 si auto_vacuum=NONE",
    }


def _rotate_logs() -> dict[str, Any]:
    if not LOG_DIR.is_dir():
        return {"name": "rotate_logs", "ok": True, "info": "no log dir"}
    rotated: list[dict[str, Any]] = []
    for log_file in LOG_DIR.glob("*.log"):
        try:
            sz = log_file.stat().st_size
            if sz <= LOG_MAX_BYTES:
                continue
            # Lire derniers LOG_KEEP_BYTES + ecrire en place
            with open(log_file, "rb") as f:
                f.seek(-LOG_KEEP_BYTES, os.SEEK_END)
                tail = f.read()
            log_file.write_bytes(tail)
            rotated.append(
                {
                    "file": log_file.name,
                    "before_mb": round(sz / 1024 / 1024, 1),
                    "after_mb": round(LOG_KEEP_BYTES / 1024 / 1024, 1),
                }
            )
        except (OSError, ValueError) as exc:
            rotated.append({"file": log_file.name, "error": str(exc)[:120]})
    return {"name": "rotate_logs", "ok": True, "rotated_count": len(rotated), "rotated": rotated[:20]}


def _clear_caches() -> dict[str, Any]:
    cleared: list[str] = []
    try:
        from nokido_agent.app.forge_hormones import cleanup as hcleanup

        n = hcleanup()
        cleared.append(f"hormones_expired={n}")
    except Exception as exc:
        cleared.append(f"hormones_skip={str(exc)[:80]}")
    try:
        from nokido_agent.app.forge_ast_index import get_index

        get_index(force_rebuild=True)
        cleared.append("ast_index_rebuilt")
    except Exception as exc:
        cleared.append(f"ast_index_skip={str(exc)[:80]}")
    # Phase 22 (2026-05-24) — critical_events maintenance integree au glymphatic.
    # 1. backup quotidien (snapshot consistent .backup() API). 2. rotate keep 7.
    # 3. purge events processed > 7 jours.
    try:
        from nokido_agent.app.forge_critical_events import backup as ce_backup, rotate_backups, purge_older_than

        bak = ce_backup()
        cleared.append(f"critical_events_backup={'ok' if bak.get('ok') else 'fail'}")
        n_rot = rotate_backups(keep_last=7)
        cleared.append(f"critical_events_rotated={n_rot}")
        n_purge = purge_older_than(days=7)
        cleared.append(f"critical_events_purged={n_purge}")
    except Exception as exc:
        cleared.append(f"critical_events_skip={str(exc)[:80]}")
    # Phase 29 — audit log purge integre glymphatic NREM3 (TTL 30j default)
    try:
        import os as _os
        from nokido_agent.app.forge_audit_log import purge_older_than as _audit_purge

        n_audit = _audit_purge(days=int(_os.environ.get("LAFORGE_AUDIT_TTL_DAYS", "30")))
        cleared.append(f"audit_purged={n_audit}")
    except Exception as exc:
        cleared.append(f"audit_skip={str(exc)[:80]}")
    return {"name": "clear_caches", "ok": True, "details": cleared}


def _release_melatonin() -> dict[str, Any]:
    try:
        from nokido_agent.app.forge_hormones import release

        rec = release(
            "melatonin",
            level=0.6,
            payload={"trigger": "glymphatic_gc"},
            receptors=["supervisor", "autonomy", "orchestrator"],
        )
        return {"name": "release_melatonin", "ok": rec.get("ok", False), "hormone_id": rec.get("id")}
    except Exception as exc:
        return {"name": "release_melatonin", "ok": False, "info": str(exc)[:120]}


def run_gc(vacuum: bool = True, rotate: bool = True, caches: bool = True, hormone: bool = True) -> dict[str, Any]:
    """Execute la maintenance glymphatique complete. Toutes etapes tolerantes."""
    t0 = time.monotonic()
    steps: list[dict[str, Any]] = []
    if vacuum:
        try:
            steps.append(_vacuum_db())
        except Exception as exc:
            steps.append({"name": "vacuum", "ok": False, "info": str(exc)[:200]})
    if rotate:
        try:
            steps.append(_rotate_logs())
        except Exception as exc:
            steps.append({"name": "rotate_logs", "ok": False, "info": str(exc)[:200]})
    if caches:
        try:
            steps.append(_clear_caches())
        except Exception as exc:
            steps.append({"name": "clear_caches", "ok": False, "info": str(exc)[:200]})
    if hormone:
        steps.append(_release_melatonin())
    duration_s = round(time.monotonic() - t0, 2)
    return {
        "ok": all(s.get("ok", False) for s in steps if s.get("name") != "release_melatonin"),
        "ts": time.time(),
        "duration_s": duration_s,
        "steps": steps,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_gc(), indent=2))
