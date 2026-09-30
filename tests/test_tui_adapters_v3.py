"""Tests adapters TUI v3 — services / tasks / health."""
from __future__ import annotations

import io
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from tui_adapters import services_adapter as sa  # noqa: E402
from tui_adapters import tasks_adapter as ta  # noqa: E402
from tui_adapters import health_adapter as ha  # noqa: E402


# ── Services adapter ────────────────────────────────────────────────────────

def _mock_response(payload: dict):
    """Fake context manager that mimics urllib.request.urlopen return."""
    class _R:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return json.dumps(payload).encode()
    return _R()


def test_list_services_sorts_running_first():
    body = {"services": {
        "NokidoDead": {"status": "sleeping", "pid": None, "restarts": 0},
        "LaForgeMCP":  {"status": "running",  "pid": 100, "restarts": 0,
                        "uptime_s": 1234, "essential": True, "port": 8766},
        "NokidoOff":  {"status": "stopped",  "pid": None, "restarts": 3},
    }}
    with patch("urllib.request.urlopen", return_value=_mock_response(body)):
        out = sa.list_services()
    assert [s["name"] for s in out] == ["LaForgeMCP", "NokidoDead", "NokidoOff"]
    assert out[0]["status"] == "running"
    assert out[0]["essential"] is True


def test_list_services_handles_supervisor_down():
    def boom(*a, **k):
        raise OSError("ECONNREFUSED")
    with patch("urllib.request.urlopen", side_effect=boom):
        assert sa.list_services() == []


def test_wake_returns_dict():
    body = {"ok": True, "action": "wake", "name": "Xy"}
    with patch("urllib.request.urlopen", return_value=_mock_response(body)):
        r = sa.wake("Xy")
    assert r["ok"] is True


def test_wake_error_path():
    with patch("urllib.request.urlopen", side_effect=OSError("nope")):
        r = sa.wake("Xy")
    assert r["ok"] is False
    assert "nope" in r["error"]


def test_supervisor_up_true_false():
    with patch("urllib.request.urlopen", return_value=_mock_response({"services": {}})):
        assert sa.supervisor_up() is True
    with patch("urllib.request.urlopen", side_effect=OSError("x")):
        assert sa.supervisor_up() is False


# ── Tasks adapter ───────────────────────────────────────────────────────────

@pytest.fixture
def tasks_db(tmp_path):
    p = tmp_path / "embeddings.db"
    c = sqlite3.connect(str(p))
    c.execute("""
        CREATE TABLE agent_tasks (
            id INTEGER PRIMARY KEY,
            created_at TEXT, updated_at TEXT,
            orchestrator TEXT, executor TEXT,
            title TEXT, description TEXT,
            task_type TEXT, priority INTEGER,
            plan TEXT, status TEXT, results TEXT,
            forge_verdict TEXT, forge_notes TEXT,
            rag_context TEXT, meta TEXT,
            sequence_id TEXT, session_id TEXT,
            intent_embedding BLOB, intent_hash TEXT,
            bypass_llm INTEGER, replay_count INTEGER
        )
    """)
    rows = [
        (1, "2026-05-23T10:00:00", "", "claude", "gemini", "T1", "", "review",
         1, "{}", "done", "{}", "", "", "", "{}", "", "", None, "", 0, 0),
        (2, "2026-05-23T11:00:00", "", "claude", "claude", "T2", "", "code",
         2, "{}", "in_progress", "{}", "", "", "", "{}", "", "", None, "", 0, 0),
        (3, "2026-05-23T12:00:00", "", "claude", "agt_codex", "T3", "", "code",
         3, "{}", "queued", "{}", "", "", "", "{}", "", "", None, "", 0, 0),
    ]
    c.executemany("INSERT INTO agent_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    c.commit(); c.close()
    return p


def test_recent_tasks_returns_descending(tasks_db):
    out = ta.recent_tasks(db_path=tasks_db)
    assert [t["id"] for t in out] == [3, 2, 1]
    assert out[0]["title"] == "T3"
    assert out[0]["status"] == "queued"


def test_recent_tasks_limit(tasks_db):
    assert len(ta.recent_tasks(limit=2, db_path=tasks_db)) == 2


def test_recent_tasks_missing_db(tmp_path):
    assert ta.recent_tasks(db_path=tmp_path / "absent.db") == []


def test_task_counts(tasks_db):
    c = ta.task_counts(db_path=tasks_db)
    assert c == {"done": 1, "in_progress": 1, "queued": 1}


# ── Health adapter ──────────────────────────────────────────────────────────

def test_health_load_report_absent(tmp_path):
    r = ha.load_report(tmp_path / "absent.json")
    assert r["score"] is None
    assert "absent" in r["error"]


def test_health_load_report_parsed(tmp_path):
    p = tmp_path / "h.json"
    p.write_text(json.dumps({
        "score": 87,
        "gaps": ["a", "b"],
        "ts": "2026-05-23T12:00:00",
        "rag_chunks": {"pct_vectorized": 92.5},
        "services_http": {"hub_mcp": {"up": True}},
        "workers_heartbeat": {"x": {"alive": True}},
        "imports": {"broken": [{"file": "f.py", "missing": "m"}]},
        "provider_keys": {"broken": []},
        "hormones_released": [{"hormone": "TSH_VECTORIZATION", "level": 0.3}],
    }), encoding="utf-8")
    r = ha.load_report(p)
    assert r["score"] == 87
    assert r["gaps"] == ["a", "b"]
    assert r["rag_pct_vec"] == 92.5
    assert r["imports_broken"] == 1
    assert r["provider_keys_broken"] == 0
    assert r["hormones"] == ["TSH_VECTORIZATION"]


def test_health_load_report_malformed_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json {", encoding="utf-8")
    r = ha.load_report(p)
    assert r["score"] is None
    assert "error" in r
