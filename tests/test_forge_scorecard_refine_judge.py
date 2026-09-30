"""tests/test_forge_scorecard_refine_judge.py
Tests : create_refine_task (forge_scorecard) + judge batch job."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

from forge_scorecard import (  # noqa: E402
    QualityGrade, Scorecard, create_refine_task,
)
import forge_scorecard_judge_job as judge_job  # noqa: E402


# === create_refine_task =======================================================

def test_create_refine_task_success():
    """urlopen retourne {result:{content:[{text: json{task_id}}]}}"""
    sc = Scorecard(grade=QualityGrade.PARTIAL,
                   confidence_score=0.6,
                   critique="missing error handling")

    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps({
        "result": {"content": [{"text": json.dumps(
            {"task_id": "agt_editor_42", "ok": True})}]}
    }).encode()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        out = create_refine_task(
            "agt_local_001", sc,
            original_description="generate retry logic",
            target_agent="EDITOR",
            hub_token="dummy")
    assert out["ok"] is True
    assert out["task_id"] == "agt_editor_42"


def test_create_refine_task_hub_down():
    """urlopen raise -> ok=False, raw contient l'erreur."""
    with patch("urllib.request.urlopen",
               side_effect=ConnectionError("hub :8766 down")):
        out = create_refine_task(
            "agt_local_001",
            Scorecard(grade=QualityGrade.PARTIAL, confidence_score=0.5,
                      critique="x"),
            hub_token="dummy")
    assert out["ok"] is False
    assert "hub :8766 down" in out["raw"]


def test_create_refine_task_payload_contains_critique():
    """Vérifie que la critique est embeddée dans description envoyée au hub."""
    sc = Scorecard(grade=QualityGrade.PARTIAL,
                   confidence_score=0.55,
                   critique="needs proper exception handling")
    captured = {}

    def _fake_urlopen(req, timeout=15):
        captured["body"] = req.data
        captured["headers"] = req.headers
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=m)
        m.__exit__ = MagicMock(return_value=False)
        m.read.return_value = json.dumps(
            {"result": {"content": [{"text": "{}"}]}}).encode()
        return m

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        create_refine_task("orig_1", sc, hub_token="t")
    body = json.loads(captured["body"])
    desc = body["params"]["arguments"]["description"]
    assert "needs proper exception handling" in desc
    assert "orig_1" in desc
    assert body["params"]["arguments"]["intent"] == "refine"


# === judge batch job ==========================================================

def _make_tasks_db(rows: list[tuple]) -> str:
    """Create temp tasks.db with given rows. Each row = (id, desc, result, scorecard_json, status)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT, "
        "result TEXT, scorecard_json TEXT, status TEXT, updated_at TEXT)")
    for tid, desc, res, sj, status in rows:
        conn.execute(
            "INSERT INTO tasks(id, description, result, scorecard_json, "
            "status, updated_at) VALUES(?, ?, ?, ?, ?, datetime('now'))",
            (tid, desc, res, sj, status))
    conn.commit()
    conn.close()
    return path


def test_scan_unrated_picks_only_unrated_done():
    sc_unrated = json.dumps(
        Scorecard(grade=QualityGrade.UNRATED).to_dict())
    sc_optimal = json.dumps(
        Scorecard(grade=QualityGrade.OPTIMAL,
                  confidence_score=0.95).to_dict())
    db = _make_tasks_db([
        ("t_unrated", "x", "code", sc_unrated, "done"),
        ("t_optimal", "x", "code", sc_optimal, "done"),
        ("t_no_sc",   "x", "code", None,       "done"),
        ("t_pending", "x", "code", sc_unrated, "pending"),  # skip status
    ])
    try:
        rows = judge_job.scan_unrated(db, limit=10)
        ids = {r["id"] for r in rows}
        assert "t_unrated" in ids
        assert "t_no_sc" in ids
        assert "t_optimal" not in ids
        assert "t_pending" not in ids
    finally:
        Path(db).unlink(missing_ok=True)


def test_scan_unrated_missing_column_returns_empty():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()
        assert judge_job.scan_unrated(path, limit=10) == []
    finally:
        Path(path).unlink(missing_ok=True)


def test_judge_one_no_code_block_returns_none():
    db = _make_tasks_db([("t_text", "do x", "just text no code", None, "done")])
    try:
        sc = judge_job.judge_one(
            {"id": "t_text", "description": "do x",
             "result": "just text no code", "scorecard_json": None},
            db_path=db, dry_run=True)
        assert sc is None
    finally:
        Path(db).unlink(missing_ok=True)


def test_judge_one_combines_det_and_sem():
    """Prior det=0.9 + sem=0.4 -> confidence = min = 0.4 -> PARTIAL."""
    prior = json.dumps(Scorecard(
        grade=QualityGrade.UNRATED,
        confidence_score=0.9,
        critique="det: pylint 8/10",
    ).to_dict())
    db = _make_tasks_db([
        ("t_code", "make function f", "```python\ndef f(): pass\n```",
         prior, "done"),
    ])
    try:
        with patch("forge_scorecard_judge_job._llm_judge",
                   return_value=(0.4, "missing return value")):
            sc = judge_job.judge_one(
                {"id": "t_code", "description": "make function f",
                 "result": "```python\ndef f(): pass\n```",
                 "scorecard_json": prior},
                db_path=db, dry_run=True)
        assert sc is not None
        assert sc.confidence_score == 0.4
        assert sc.grade == QualityGrade.PARTIAL
        assert "missing return value" in sc.critique
        assert "pylint 8/10" in sc.critique
    finally:
        Path(db).unlink(missing_ok=True)
