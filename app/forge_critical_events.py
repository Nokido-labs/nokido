"""
forge_critical_events.py — Append-only SQLite log for events qui doivent
survivre a un restart hub.

Phase 12 (2026-05-24). Nokido accepte la perte d'events SSE/pub-sub
volatiles sur restart hub (local-first, restart <5s). EXCEPTION : events
de classe 'critical' (quarantine, cve_detected, security_breach,
adrenaline>=0.9, cortisol>=0.9) doivent persister sur disque pour que
le sentinel au boot suivant puisse les consulter et re-armer.

Schema SQLite (sandbox/critical_events.db) :
    id INTEGER PK AUTOINCREMENT
    ts REAL                  -- unix seconds
    kind TEXT                -- 'hormone' | 'quarantine' | 'cve' | 'security_breach' ...
    severity TEXT            -- 'warn' | 'error' | 'critical'
    payload TEXT             -- JSON serialise
    processed_at REAL        -- NULL si pas encore consomme par un sentinel

API :
    persist(kind, severity, payload) -> id
    unprocessed(limit=100) -> list[dict]
    mark_processed(ids: list[int]) -> int
    purge_older_than(days=7) -> int    # nettoyage routine NREM3 (glymphatic)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
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

logger = logging.getLogger("forge_critical_events")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "sandbox" / "critical_events.db"
_LOCK = threading.Lock()
_INITIALIZED = False


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), timeout=5.0)
    c.row_factory = sqlite3.Row
    return c


def _init_db() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _LOCK:
        if _INITIALIZED:
            return
        with _conn() as c:
            # Phase 22 (2026-05-24) durabilite : synchronous=FULL force fsync sur
            # chaque commit. Cout = ~10ms par insert. Pour events critiques
            # survie-restart, vaut largement le coup vs perte sur power loss.
            c.execute("PRAGMA synchronous=FULL")
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("""
                CREATE TABLE IF NOT EXISTS forge_critical_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    kind TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    processed_at REAL
                )
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_unprocessed
                ON forge_critical_events(processed_at, ts)
                WHERE processed_at IS NULL
            """)
        _INITIALIZED = True


def backup(suffix: str | None = None) -> dict[str, Any]:
    """Phase 22 — backup rotatif. SQLite .backup() API = consistent snapshot
    pendant que la DB est utilisee (pas un cp brut qui risque corruption).
    Retourne {ok, path, size_mb}."""
    import time as _t

    try:
        _init_db()
        suffix = suffix or _t.strftime("%Y%m%d")
        bak_path = DB_PATH.parent / f"critical_events.bak.{suffix}.db"
        with _conn() as src:
            bak = sqlite3.connect(str(bak_path), timeout=10.0)
            try:
                src.backup(bak)
            finally:
                bak.close()
        sz = bak_path.stat().st_size
        return {"ok": True, "path": str(bak_path), "size_mb": round(sz / 1024 / 1024, 2)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def rotate_backups(keep_last: int = 7) -> int:
    """Garde les keep_last backups les plus recents, supprime les anciens."""
    try:
        baks = sorted(DB_PATH.parent.glob("critical_events.bak.*.db"))
        if len(baks) <= keep_last:
            return 0
        removed = 0
        for old in baks[:-keep_last]:
            try:
                old.unlink()
                removed += 1
            except Exception:
                pass
        return removed
    except Exception:
        return 0


def persist(kind: str, severity: str, payload: dict | None = None) -> int:
    """Append event. Returns row id. Never raises (fail-safe)."""
    try:
        _init_db()
        payload = dict(payload or {})
        # DLP log Tier 1 : scrub PII/secrets du payload incident avant persist
        try:
            from nokido_agent.app.forge_semantic_firewall import redact_for_log as _scrub

            payload = _scrub(payload)
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            # CONTOURNEMENT DE PROTECTION DES DONNEES. Si le scrub echoue, le payload
            # part en base TEL QUEL : PII et secrets compris. Le silence faisait
            # passer un incident non expurge pour un incident expurge.
            _lg.getLogger(__name__).error(
                "[critical_events] scrub DLP IMPOSSIBLE (%s: %s) — le payload est "
                "persiste NON EXPURGE | consequence: cet enregistrement peut contenir "
                "des donnees personnelles ou des secrets, le traiter comme sensible",
                type(e).__name__, str(e)[:100])
        if "trace_id" not in payload:
            try:
                from nokido_agent.app.forge_trace_context import get_trace_id

                payload["trace_id"] = get_trace_id()
            except Exception as e:  # noqa: BLE001
                import logging as _lg

                _lg.getLogger(__name__).warning(
                    "[critical_events] trace_id absent (%s: %s) | consequence: cet "
                    "evenement ne pourra pas etre rattache a la chaine d'appels qui "
                    "l'a produit", type(e).__name__, str(e)[:90])
        with _conn() as c:
            cur = c.execute(
                "INSERT INTO forge_critical_events (ts, kind, severity, payload) VALUES (?, ?, ?, ?)",
                (time.time(), kind, severity, json.dumps(payload, default=str)),
            )
            row_id = cur.lastrowid
        logger.info("persist kind=%s severity=%s id=%s", kind, severity, row_id)
        return row_id or 0
    except Exception as exc:
        logger.error("persist fail (event lost): %s", exc)
        return 0


def unprocessed(limit: int = 100) -> list[dict[str, Any]]:
    try:
        _init_db()
        with _conn() as c:
            rows = c.execute(
                "SELECT id, ts, kind, severity, payload FROM forge_critical_events "
                "WHERE processed_at IS NULL ORDER BY id ASC LIMIT ?",
                (int(limit),),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                payload = json.loads(r["payload"])
            except Exception:
                payload = {"_raw": r["payload"][:200]}
            out.append(
                {
                    "id": r["id"],
                    "ts": r["ts"],
                    "kind": r["kind"],
                    "severity": r["severity"],
                    "payload": payload,
                }
            )
        return out
    except Exception as exc:
        logger.error("unprocessed fail: %s", exc)
        return []


def mark_processed(ids: list[int]) -> int:
    if not ids:
        return 0
    try:
        _init_db()
        now = time.time()
        with _conn() as c:
            cur = c.executemany(
                "UPDATE forge_critical_events SET processed_at = ? WHERE id = ?",
                [(now, int(i)) for i in ids],
            )
            return cur.rowcount or 0
    except Exception as exc:
        logger.error("mark_processed fail: %s", exc)
        return 0


def purge_older_than(days: int = 7) -> int:
    try:
        _init_db()
        cutoff = time.time() - days * 86400
        with _conn() as c:
            cur = c.execute(
                "DELETE FROM forge_critical_events WHERE processed_at IS NOT NULL AND ts < ?",
                (cutoff,),
            )
            return cur.rowcount or 0
    except Exception as exc:
        logger.error("purge fail: %s", exc)
        return 0


def stats() -> dict[str, Any]:
    try:
        _init_db()
        with _conn() as c:
            total = c.execute("SELECT COUNT(*) FROM forge_critical_events").fetchone()[0]
            unproc = c.execute("SELECT COUNT(*) FROM forge_critical_events WHERE processed_at IS NULL").fetchone()[0]
            by_kind = c.execute("SELECT kind, COUNT(*) FROM forge_critical_events GROUP BY kind").fetchall()
        return {
            "db_path": str(DB_PATH),
            "total": total,
            "unprocessed": unproc,
            "by_kind": {r[0]: r[1] for r in by_kind},
        }
    except Exception as exc:
        return {"error": str(exc)[:200]}


if __name__ == "__main__":
    print(json.dumps(stats(), indent=2))
