"""
Phase 0 - AMI roadmap: trace (state_t, action, state_t1) -> execution_traces.db
Feed dataset for Phase 3 World Model training.
"""

import sqlite3
import time
import json
import uuid
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
DB_PATH = ROOT / "RAG" / "execution_traces.db"


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS traces (
            id           TEXT NOT NULL,
            ts           REAL NOT NULL,
            state_t_emb  BLOB,
            action_json  TEXT NOT NULL,
            state_t1_emb BLOB,
            cost_before  REAL,
            cost_after   REAL,
            task_type    TEXT,
            success      INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts        ON traces(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_type ON traces(task_type)")
    # Migration : colonne trace_id (corrélation) + index UNIQUE sur id.
    # Idempotence : un id déterministe + INSERT OR IGNORE déduplique les
    # double-lectures d'une même ligne d'audit (2 tailers, replay…). Les ids
    # historiques uuid4 étant déjà uniques, l'index unique se crée sans conflit.
    try:
        conn.execute("ALTER TABLE traces ADD COLUMN trace_id TEXT")
    except Exception:
        pass  # colonne déjà présente
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_id    ON traces(id)")
    conn.execute("CREATE INDEX IF NOT EXISTS        idx_trace ON traces(trace_id)")
    conn.commit()
    conn.close()


def record_trace(
    state_t_emb,
    action: dict,
    state_t1_emb,
    cost_before: float,
    cost_after: float,
    task_type: str,
    success: bool,
    trace_id: str | None = None,
    event_key: str | None = None,
) -> str:
    """Enregistre une transition (state_t, action, state_t1).

    trace_id : corrélation. Explicite > contextvar (forge_trace_context) > 'system'.
    event_key : si fourni, l'id de ligne est sha256(event_key) déterministe ->
      INSERT OR IGNORE rend l'écriture IDEMPOTENTE (2 writers/relectures de la
      même ligne d'audit = 1 seule ligne). Sinon uuid4 (compat historique).
    """
    import hashlib

    import numpy as np

    if trace_id is None:
        try:
            from nokido_agent.app.forge_trace_context import get_trace_id

            trace_id = get_trace_id()
        except Exception:
            trace_id = None
    if not trace_id:
        # Contextvar vide (écriture daemon/hors-requête) : get_trace_id() rend
        # None -> on stockait NULL (14839 lignes non-corrélables). Honorer le
        # contrat du docstring : fallback 'system' (jamais NULL).
        trace_id = "system"

    if event_key:
        row_id = hashlib.sha256(event_key.encode("utf-8", "replace")).hexdigest()[:24]
    else:
        row_id = str(uuid.uuid4())

    # DLP log Tier 1 : scrub PII/secrets de l'action avant persist (en clair sinon)
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_for_log as _scrub

        _action = _scrub(action)
    except Exception:
        _action = action

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT OR IGNORE INTO traces
           (id, ts, state_t_emb, action_json, state_t1_emb,
            cost_before, cost_after, task_type, success, trace_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            row_id,
            time.time(),
            np.array(state_t_emb, dtype="float32").tobytes() if state_t_emb is not None else None,
            json.dumps(_action),
            np.array(state_t1_emb, dtype="float32").tobytes() if state_t1_emb is not None else None,
            cost_before,
            cost_after,
            task_type,
            int(success),
            trace_id,
        ),
    )
    conn.commit()
    conn.close()
    return row_id


def get_traces(limit: int = 1000, task_type: str = None) -> list:
    import numpy as np

    conn = sqlite3.connect(DB_PATH)
    q = """SELECT id, ts, state_t_emb, action_json, state_t1_emb,
                  cost_before, cost_after, task_type, success
           FROM traces"""
    params: list = []
    if task_type:
        q += " WHERE task_type=?"
        params.append(task_type)
    q += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append(
            {
                "id": row[0],
                "ts": row[1],
                "state_t_emb": np.frombuffer(row[2], dtype="float32") if row[2] else None,
                "action": json.loads(row[3]),
                "state_t1_emb": np.frombuffer(row[4], dtype="float32") if row[4] else None,
                "cost_before": row[5],
                "cost_after": row[6],
                "task_type": row[7],
                "success": bool(row[8]),
            }
        )
    return result


def count_traces() -> int:
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
    conn.close()
    return n


if __name__ == "__main__":
    init_db()
    print(f"[tracer] DB: {DB_PATH}")
    print(f"[tracer] Traces: {count_traces()}")
