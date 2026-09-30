"""Adapter Tasks — agent_tasks queue."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_DB = Path(__file__).resolve().parent.parent.parent / "RAG" / "embeddings.db"


def recent_tasks(limit: int = 30, db_path: Optional[Path] = None) -> list[dict]:
    db = db_path if db_path is not None else DEFAULT_DB
    if not db.exists():
        return []
    try:
        c = sqlite3.connect(str(db), timeout=5)
        rows = c.execute(
            "SELECT id, title, status, executor, orchestrator, "
            "       task_type, priority, created_at "
            "FROM agent_tasks ORDER BY datetime(created_at) DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()
        c.close()
    except Exception:
        return []
    return [
        {
            "id": r[0],
            "title": (r[1] or "")[:60],
            "status": r[2] or "?",
            "executor": r[3] or "-",
            "orchestrator": r[4] or "-",
            "task_type": r[5] or "",
            "priority": r[6] or 0,
            "created_at": r[7] or "",
        }
        for r in rows
    ]


def task_counts(db_path: Optional[Path] = None) -> dict:
    """Compteurs status pour barre résumée."""
    db = db_path if db_path is not None else DEFAULT_DB
    if not db.exists():
        return {}
    try:
        c = sqlite3.connect(str(db), timeout=5)
        rows = c.execute("SELECT status, COUNT(*) FROM agent_tasks GROUP BY status").fetchall()
        c.close()
    except Exception:
        return {}
    return {r[0]: r[1] for r in rows}
