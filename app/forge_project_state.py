"""app/forge_project_state.py — Snapshot et diff de l'état du projet."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


@dataclass
class ProjectState:
    files: Dict[str, float]  # path -> mtime
    modules: List[str]  # modules Python importés (uniques)
    open_todos: List[str]  # "file:lineno: TODO..."
    stale_files: List[str]  # modifiés > 7j sans commit récent


def snapshot(root: str) -> ProjectState:
    files: Dict[str, float] = {}
    modules_set: set[str] = set()
    todos: List[str] = []
    stale: List[str] = []

    stale_threshold = time.time() - 7 * 86400
    committed = _committed_since(root, days=7)

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip caches
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git", "node_modules")]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fp = os.path.join(dirpath, fname)
            mtime = os.path.getmtime(fp)
            files[fp] = mtime

            src = Path(fp).read_text("utf-8", errors="replace")

            # Extraire modules importés
            try:
                tree = ast.parse(src, filename=fp)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            modules_set.add(alias.name.split(".")[0])
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        modules_set.add(node.module.split(".")[0])
            except SyntaxError:
                pass

            # TODOs
            for i, line in enumerate(src.splitlines(), 1):
                if re.search(r"\b(TODO|FIXME)\b", line, re.IGNORECASE):
                    todos.append(f"{fp}:{i}: {line.strip()[:120]}")

            # Stale: modifié > 7j ET pas dans les commits récents
            if mtime < stale_threshold and fp not in committed:
                stale.append(fp)

    return ProjectState(
        files=files,
        modules=sorted(modules_set),
        open_todos=todos,
        stale_files=stale,
    )


def _committed_since(root: str, days: int = 7) -> set[str]:
    """Fichiers touchés par un commit git dans les N derniers jours."""
    try:
        out = subprocess.check_output(
            ["git", "log", f"--since={days} days ago", "--name-only", "--format="],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        errors="replace")
        return {os.path.join(root, f.strip()) for f in out.splitlines() if f.strip()}
    except Exception:
        return set()


def diff(old: ProjectState, new: ProjectState) -> dict:
    """Compare deux snapshots. Retourne {added, removed, changed}."""
    old_keys = set(old.files)
    new_keys = set(new.files)
    return {
        "added": sorted(new_keys - old_keys),
        "removed": sorted(old_keys - new_keys),
        "changed": sorted(f for f in old_keys & new_keys if abs(old.files[f] - new.files[f]) > 0.5),
        "todos_delta": len(new.open_todos) - len(old.open_todos),
        "stale_delta": len(new.stale_files) - len(old.stale_files),
    }


if __name__ == "__main__":
    import json
    import sys

    root = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent.parent)
    state = snapshot(root)
    print(
        json.dumps(
            {
                "files": len(state.files),
                "modules": len(state.modules),
                "todos": len(state.open_todos),
                "stale": len(state.stale_files),
                "sample_todos": state.open_todos[:3],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


# ── Propagation graph (session-scoped caller tracking) ──────────────────────

import sqlite3 as _sqlite3

_GRAPH_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_state_edges (
    session_id   TEXT NOT NULL,
    changed_file TEXT NOT NULL,
    caller_file  TEXT NOT NULL,
    propagated   INTEGER DEFAULT 0,
    PRIMARY KEY (session_id, changed_file, caller_file)
);
"""
_ROOT_DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"


class ForgeProjectStateGraph:
    """Tracks which callers are affected by file changes, per session."""

    def __init__(self, db_path: str = str(_ROOT_DB)):
        self.db_path = db_path
        self._init()

    def _conn(self):
        c = _sqlite3.connect(self.db_path)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init(self):
        with self._conn() as conn:
            conn.execute(_GRAPH_SCHEMA)

    def record_change(self, session_id: str, file_path: str, callers: List[str]) -> int:
        if not callers:
            return 0
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO project_state_edges (session_id, changed_file, caller_file) VALUES (?,?,?)",
                [(session_id, file_path, c) for c in callers],
            )
        return len(callers)

    def get_pending_propagation(self, session_id: str) -> List[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT changed_file FROM project_state_edges WHERE session_id=? AND propagated=0",
                (session_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def get_callers(self, session_id: str, file_path: str) -> List[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT caller_file FROM project_state_edges WHERE session_id=? AND changed_file=?",
                (session_id, file_path),
            ).fetchall()
        return [r[0] for r in rows]

    def mark_propagated(self, session_id: str, file_path: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE project_state_edges SET propagated=1 WHERE session_id=? AND changed_file=?",
                (session_id, file_path),
            )

    def summary(self, session_id: str) -> dict:
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM project_state_edges WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(DISTINCT changed_file) FROM project_state_edges WHERE session_id=? AND propagated=0",
                (session_id,),
            ).fetchone()[0]
        return {"session_id": session_id, "total_edges": total, "pending_files": pending}
