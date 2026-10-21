"""NR -- une reaffectation sur une base SANS table tasks est ILLISIBLE et dite, jamais une exception.

CI de reference e6642dcf1 (19/10) : 4 NR rouges « sqlite3.OperationalError: no such table: tasks » dans _reaffecter --
le worktree neuf de la reference n'a pas de sandbox/tasks.db ; en local ils passaient par accident, sur la VRAIE base.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as E  # noqa: E402


def test_base_sans_table_rend_none_sans_lever(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_db", lambda: sqlite3.connect(str(tmp_path / "vide.db")))
    monkeypatch.setattr(E, "_executeur_bat", lambda _a: True)
    monkeypatch.setattr(E, "_executeur_suspendu", lambda _a: False)
    assert E._reaffecter({"id": "t1", "agent": "OPENCODE_GLM"}, "NON LIVRE", ordre=["OPENCODE_GPTOSS"]) is None
