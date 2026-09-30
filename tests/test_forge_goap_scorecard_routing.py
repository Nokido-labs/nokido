"""tests/test_forge_goap_scorecard_routing.py
Tests des helpers read_task_scorecard + route_next_action de
forge_goap_hub_bridge.py. DB tasks.db temporaire."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))

from forge_goap_hub_bridge import read_task_scorecard, route_next_action  # noqa
from forge_scorecard import Scorecard, QualityGrade  # noqa


def _seed(db_path: str, task_id: str, scorecard_json: str | None) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, scorecard_json TEXT)")
    conn.execute(
        "INSERT INTO tasks(id, scorecard_json) VALUES(?, ?)",
        (task_id, scorecard_json))
    conn.commit()
    conn.close()


def test_read_scorecard_optimal():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        sc = Scorecard(grade=QualityGrade.OPTIMAL, confidence_score=0.95)
        _seed(db, "t1", sc.to_json())
        loaded = read_task_scorecard("t1", db_path=db)
        assert loaded is not None
        assert loaded.grade == QualityGrade.OPTIMAL
        assert loaded.confidence_score == 0.95
    finally:
        Path(db).unlink(missing_ok=True)


def test_read_scorecard_missing_returns_none():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        _seed(db, "t1", None)
        assert read_task_scorecard("t1", db_path=db) is None
    finally:
        Path(db).unlink(missing_ok=True)


def test_read_scorecard_no_column():
    """Pas de colonne scorecard_json -> retourne None (pas de crash)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO tasks(id) VALUES('t1')")
        conn.commit()
        conn.close()
        assert read_task_scorecard("t1", db_path=db) is None
    finally:
        Path(db).unlink(missing_ok=True)


def test_route_next_action_optimal_closes():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        sc = Scorecard(grade=QualityGrade.OPTIMAL, confidence_score=0.95)
        _seed(db, "t1", sc.to_json())
        assert route_next_action("t1", db_path=db) == "close"
    finally:
        Path(db).unlink(missing_ok=True)


def test_route_next_action_partial_refines():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        sc = Scorecard(grade=QualityGrade.PARTIAL, confidence_score=0.6)
        _seed(db, "t1", sc.to_json())
        assert route_next_action("t1", db_path=db) == "refine"
    finally:
        Path(db).unlink(missing_ok=True)


def test_route_next_action_rejected_bans():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        sc = Scorecard(grade=QualityGrade.REJECTED, confidence_score=0.1)
        _seed(db, "t1", sc.to_json())
        assert route_next_action("t1", db_path=db) == "ban_and_retry"
    finally:
        Path(db).unlink(missing_ok=True)


def test_route_next_action_no_db_triggers_judge():
    """DB absente -> UNRATED -> judge."""
    assert route_next_action(
        "anything", db_path="C:/nonexistent/path/tasks.db") == "judge"
