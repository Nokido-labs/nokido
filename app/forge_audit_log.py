"""
forge_audit_log.py - Phase 29 (2026-05-25)
Audit append-only + W3C trace_id. Foie immunitaire : trace ce qui rentre/sort.

DB separee RAG/audit.db (PAS embeddings.db) :
  - isolation IO (WAL distinct, pas de concurrence avec ingest/embed)
  - purge agressive sans toucher au cortex semantique
  - scale 100k events sans fragmenter rag_chunks (8GB)

Schema : append-only. INSERT only. SELECT pour /api/audit/recent.

Anatomie : Foie (detox + tracabilite) + barriere hemato-encephalique.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(os.environ.get("LAFORGE_ROOT", str(Path(__file__).resolve().parent.parent)))
DB_PATH = ROOT / "RAG" / "audit.db"
logger = logging.getLogger("forge_audit_log")

_INIT_DONE = False
_W3C_VERSION = "00"
_FLAGS_SAMPLED = "01"


@contextlib.contextmanager
def _conn():
    """Connexion SQLite REELLEMENT fermee a la sortie du bloc.

    ⚠️ `with sqlite3.connect(...)` gere la TRANSACTION, jamais la FERMETURE.
    Le piege est classique ; ici il coutait cher, parce que ce module ecrit une
    ligne d'audit a CHAQUE requete HTTP du hub -- le middleware `_TraceCtxMW`
    appelle `persist_async` dans son `finally`, donc meme sur une route
    inexistante. En `journal_mode=WAL`, une connexion tient TROIS handles
    (`.db`, `.db-wal`, `.db-shm`).

    MESURE 2026-08-19 : +3,0 handles par requete, jamais rendus -- 5458 -> 5542
    pour trente appels a /health, +3,1 pour trente 404 (donc bien le pipeline
    generique, pas un handler), et +0 au repos sur dix secondes. La fuite etait
    STRICTEMENT proportionnelle au trafic servi : invisible en veille, et
    croissante tant que le hub travaille. Le process en portait 5424 apres une
    heure d'uptime.

    Le `yield` conserve la forme `with _conn() as c` de tous les appelants : le
    correctif tient en un point, la ou la ressource est creee.
    """
    c = sqlite3.connect(str(DB_PATH), timeout=10.0, isolation_level=None)
    try:
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("PRAGMA synchronous=NORMAL;")
        c.execute("PRAGMA temp_store=MEMORY;")
        c.execute("PRAGMA cache_size=-8000;")
        yield c
    finally:
        # `isolation_level=None` = autocommit : rien a valider ici, et fermer
        # reste correct meme si le bloc appelant a leve.
        c.close()


def init_db() -> None:
    global _INIT_DONE
    if _INIT_DONE:
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           REAL NOT NULL,
                trace_id     TEXT NOT NULL,
                parent_id    TEXT,
                agent        TEXT,
                action       TEXT NOT NULL,
                target       TEXT,
                status       INTEGER,
                duration_ms  INTEGER,
                payload_hash TEXT,
                payload_full TEXT,
                ring         INTEGER,
                client_ip    TEXT
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_log(trace_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts    ON audit_log(ts)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)")
        # Hiérarchie de spans (call-flow) : span_id propre -> un enfant référence
        # son parent via parent_id. Migration idempotente (additive). 2026-06-03.
        try:
            c.execute("ALTER TABLE audit_log ADD COLUMN span_id TEXT")
        except Exception:
            pass
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_span ON audit_log(span_id)")
    _INIT_DONE = True


def gen_trace_id() -> str:
    return secrets.token_hex(16)


def gen_span_id() -> str:
    return secrets.token_hex(8)


def parse_traceparent(hdr: Optional[str]) -> tuple[str, str]:
    if not hdr:
        return gen_trace_id(), gen_span_id()
    parts = hdr.strip().split("-")
    if len(parts) != 4 or len(parts[1]) != 32 or len(parts[2]) != 16:
        return gen_trace_id(), gen_span_id()
    return parts[1], parts[2]


def build_traceparent(trace_id: str, span_id: Optional[str] = None) -> str:
    return f"{_W3C_VERSION}-{trace_id}-{span_id or gen_span_id()}-{_FLAGS_SAMPLED}"


def _hash_payload(obj: Any) -> str:
    try:
        raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        raw = str(obj)
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16]


def persist(
    action: str,
    *,
    trace_id: str,
    span_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    agent: Optional[str] = None,
    target: Optional[str] = None,
    status: Optional[int] = None,
    duration_ms: Optional[int] = None,
    payload: Any = None,
    ring: Optional[int] = None,
    client_ip: Optional[str] = None,
    verbose: bool = False,
) -> bool:
    init_db()
    try:
        ph = _hash_payload(payload) if payload is not None else None
        pf = None
        if verbose and payload is not None:
            try:
                pf = json.dumps(payload, ensure_ascii=False, default=str)[:8000]
            except Exception:
                pf = None
        with _conn() as c:
            c.execute(
                "INSERT INTO audit_log(ts,trace_id,span_id,parent_id,agent,action,target,"
                "status,duration_ms,payload_hash,payload_full,ring,client_ip) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (time.time(), trace_id, span_id, parent_id, agent, action, target, status, duration_ms, ph, pf, ring, client_ip),
            )
        return True
    except Exception as exc:
        logger.warning(f"audit persist fail: {exc}")
        return False


async def persist_async(*args, **kwargs) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: persist(*args, **kwargs))


def query_recent(
    limit: int = 100, trace_id: Optional[str] = None, agent: Optional[str] = None, verbose: bool = False
) -> list[dict]:
    init_db()
    sql = (
        "SELECT id,ts,trace_id,span_id,parent_id,agent,action,target,status,"
        "duration_ms,payload_hash,ring,client_ip" + (",payload_full" if verbose else "") + " FROM audit_log WHERE 1=1"
    )
    params: list = []
    if trace_id:
        sql += " AND trace_id=?"
        params.append(trace_id)
    if agent:
        sql += " AND agent=?"
        params.append(agent)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(max(limit, 1), 1000))
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    cols = [
        "id",
        "ts",
        "trace_id",
        "span_id",
        "parent_id",
        "agent",
        "action",
        "target",
        "status",
        "duration_ms",
        "payload_hash",
        "ring",
        "client_ip",
    ]
    if verbose:
        cols.append("payload_full")
    return [dict(zip(cols, r)) for r in rows]


def purge_older_than(days: int = 30) -> int:
    init_db()
    cutoff = time.time() - days * 86400
    with _conn() as c:
        cur = c.execute("DELETE FROM audit_log WHERE ts < ?", (cutoff,))
        n = cur.rowcount
        c.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    return n
