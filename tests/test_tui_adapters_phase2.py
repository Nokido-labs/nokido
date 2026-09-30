"""Tests adapters Phase 2 — events + forge."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from tui_adapters import events_adapter as ea  # noqa: E402
from tui_adapters import forge_adapter as fa  # noqa: E402


def _resp(payload):
    class _R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(payload).encode()
    return _R()


# ── events_adapter ──────────────────────────────────────────────────────────

def test_fetch_events_returns_list():
    with patch("urllib.request.urlopen", return_value=_resp([
        {"id": 1, "topic": "tool.run", "agent": "claude"},
        {"id": 2, "topic": "rpc.gemini.ask", "agent": "gemini"},
    ])):
        out = ea.fetch_events("*", limit=10)
    assert len(out) == 2
    assert out[0]["topic"] == "tool.run"


def test_fetch_events_webhub_down():
    with patch("urllib.request.urlopen", side_effect=OSError("x")):
        assert ea.fetch_events() == []


def test_event_stats_parsed():
    with patch("urllib.request.urlopen", return_value=_resp({
        "total_events": 42, "errors": 2,
        "by_prefix": {"tool": 10, "rpc": 30}, "by_agent": {"claude": 20},
    })):
        s = ea.event_stats()
    assert s["total_events"] == 42
    assert "tool" in s["by_prefix"]


# ── forge_adapter ───────────────────────────────────────────────────────────

@pytest.fixture
def rag_db(tmp_path):
    p = tmp_path / "embeddings.db"
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, "
              "domain TEXT, meta TEXT, source TEXT, ingested_at TEXT)")
    rows = [
        ("skill_aaa", "When task=replay_hub …", "curated_skills",
         json.dumps({"task_type": "replay_hub", "action_type": "system_tick",
                     "uses": 4000, "success_rate": 1.0, "score": 0.95}),
         "skill_curator", "2026-05-23T00:00:00"),
        ("skill_bbb", "When task=replay_run …", "curated_skills",
         json.dumps({"task_type": "replay_run", "action_type": "exec",
                     "uses": 200, "success_rate": 0.95, "score": 0.72}),
         "skill_curator", "2026-05-23T00:00:00"),
        ("skill_ccc", "low", "curated_skills",
         json.dumps({"task_type": "rare", "action_type": "x",
                     "uses": 5, "success_rate": 0.8, "score": 0.20}),
         "skill_curator", "2026-05-23T00:00:00"),
    ]
    c.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?,?,?)", rows)
    c.commit(); c.close()
    return p


def test_top_curated_skills_orders_by_score(rag_db):
    out = fa.top_curated_skills(db_path=rag_db, limit=10)
    assert [s["id"] for s in out] == ["skill_aaa", "skill_bbb", "skill_ccc"]
    assert out[0]["score"] == 0.95
    assert out[0]["uses"] == 4000


def test_top_curated_skills_limit(rag_db):
    assert len(fa.top_curated_skills(db_path=rag_db, limit=2)) == 2


def test_top_curated_skills_missing_db(tmp_path):
    assert fa.top_curated_skills(db_path=tmp_path / "absent.db") == []


@pytest.fixture
def traces_db(tmp_path):
    p = tmp_path / "execution_traces.db"
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE traces (id TEXT, ts REAL, action_json TEXT, "
              "cost_before REAL, cost_after REAL, task_type TEXT, success INTEGER)")
    import time as _t
    now = _t.time()
    rows = [(str(i), now - i * 60, "{}", 0.3, 0.2, "x", 1 if i < 8 else 0)
            for i in range(10)]
    c.executemany("INSERT INTO traces VALUES (?,?,?,?,?,?,?)", rows)
    c.commit(); c.close()
    return p


def test_ami_traces_summary(traces_db):
    s = fa.ami_traces_summary(db_path=traces_db)
    assert s["present"] is True
    assert s["total"] == 10
    assert s["successes"] == 8
    assert s["rate"] == 0.8
    assert s["last_24h"] == 10


def test_ami_traces_summary_missing(tmp_path):
    assert fa.ami_traces_summary(db_path=tmp_path / "absent.db") == {"present": False}


def test_goap_state_absent(tmp_path):
    r = fa.goap_state(path=tmp_path / "goap.json")
    assert r == {"present": False}


def test_goap_state_present(tmp_path):
    p = tmp_path / "goap.json"
    p.write_text(json.dumps({"plans": 3, "active_goal": "x"}), encoding="utf-8")
    r = fa.goap_state(path=p)
    assert r["present"] is True
    assert r["data"]["plans"] == 3


def test_night_trainer_state(tmp_path):
    (tmp_path / "night_trainer.heartbeat").write_text(
        json.dumps({"ts": "2026-05-23", "samples": 10000}), encoding="utf-8")
    r = fa.night_trainer_state(path=tmp_path)
    assert r["night"]["present"] is True
    assert r["night"]["data"]["samples"] == 10000
    assert r["offline"]["present"] is False
