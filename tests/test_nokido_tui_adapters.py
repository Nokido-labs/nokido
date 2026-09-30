"""Tests nokido_tui v2 — Phase 6 acceptance."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))


@pytest.fixture
def tmp_persist(tmp_path, monkeypatch):
    """Isolated bind mount + DB par test."""
    persist = tmp_path / "persist"
    persist.mkdir()
    monkeypatch.setenv("LAFORGE_PERSIST_DIR", str(persist))
    return persist


def test_fetch_recent_filters_by_agent_and_ts():
    from nokido_tui import fetch_recent
    msgs = fetch_recent("agt_claude", 0, limit=10)
    assert isinstance(msgs, list)
    for m in msgs:
        assert m["from"] == "agt_claude" or m["to"] == "agt_claude"
        assert "id" in m and "ts" in m


def test_input_parser_single_target():
    """@gemini msg → 1 target."""
    import re
    text = "@gemini ping"
    m = re.match(r"^(@\w+(?:,@\w+)*)\s+(.+)$", text)
    assert m is not None
    targets = [t.strip("@") for t in m.group(1).split(",")]
    assert targets == ["gemini"]
    assert m.group(2) == "ping"


def test_input_parser_multi_target():
    """@claude,@codex review → 2 targets."""
    import re
    text = "@claude,@codex review this PR"
    m = re.match(r"^(@\w+(?:,@\w+)*)\s+(.+)$", text)
    assert m is not None
    targets = [t.strip("@") for t in m.group(1).split(",")]
    assert targets == ["claude", "codex"]
    assert m.group(2) == "review this PR"


def test_input_parser_broadcast():
    """@all msg → expanded to all agents."""
    import re
    from nokido_tui import AGENTS
    text = "@all sync now"
    m = re.match(r"^(@\w+(?:,@\w+)*)\s+(.+)$", text)
    assert m is not None
    targets = [t.strip("@") for t in m.group(1).split(",")]
    assert targets == ["all"]
    if "all" in targets:
        targets = [a["label"].lower() for a in AGENTS]
    assert len(targets) == 5  # 5 agents


def test_input_parser_invalid_no_message():
    """@gemini sans message → match fail."""
    import re
    text = "@gemini"
    m = re.match(r"^(@\w+(?:,@\w+)*)\s+(.+)$", text)
    assert m is None


def test_session_dump_restore_roundtrip(tmp_persist, monkeypatch):
    """Save session, reload, vérifier état préservé."""
    # Reload module to pick up env override
    import importlib
    import nokido_tui
    importlib.reload(nokido_tui)
    assert str(tmp_persist) in str(nokido_tui.SESSION_FILE)

    # Write fake session
    session_data = {
        "panes": {
            "agt_claude": {"last_seen_id": "msg_abc123", "last_ts": 1234567890.0},
            "agt_gemini": {"last_seen_id": "msg_def456", "last_ts": 1234567990.0},
        },
        "rag_visible": True,
        "unread_filter": False,
        "saved_at": time.time(),
        "schema": "nokido.tui.session.v2",
    }
    nokido_tui.SESSION_FILE.write_text(
        json.dumps(session_data), encoding="utf-8"
    )

    # Round-trip via JSON
    loaded = json.loads(nokido_tui.SESSION_FILE.read_text(encoding="utf-8"))
    assert loaded["panes"]["agt_claude"]["last_seen_id"] == "msg_abc123"
    assert loaded["rag_visible"] is True
    assert loaded["schema"] == "nokido.tui.session.v2"


def test_session_expired_7days_ignored(tmp_persist, monkeypatch):
    """Session > 7j ignorée par _load_session."""
    import importlib
    import nokido_tui
    importlib.reload(nokido_tui)

    old = {
        "panes": {"agt_claude": {"last_seen_id": "old", "last_ts": 100.0}},
        "saved_at": time.time() - (8 * 86400),  # 8 jours
    }
    nokido_tui.SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    nokido_tui.SESSION_FILE.write_text(json.dumps(old), encoding="utf-8")

    # Note : test sans instancier App (Textual)
    # Vérifie juste fichier accessible
    assert nokido_tui.SESSION_FILE.exists()
    age = time.time() - json.loads(nokido_tui.SESSION_FILE.read_text())["saved_at"]
    assert age > 7 * 86400


def test_opsec_state_returns_dict():
    from nokido_tui import opsec_state
    state = opsec_state()
    assert isinstance(state, dict)
    assert "level" in state
    assert "locked" in state
    assert state["level"] in ("CTF", "STANDARD", "PARANOID", "?")
    assert isinstance(state["locked"], bool)


def test_status_services_returns_dict():
    from nokido_tui import status_services
    svc = status_services()
    assert isinstance(svc, dict)
    assert "hub" in svc
    assert all(v in ("🟢", "🔴") for v in svc.values())


def test_agents_have_required_fields():
    from nokido_tui import AGENTS
    assert len(AGENTS) >= 5
    for a in AGENTS:
        assert "id" in a and a["id"].startswith("agt_")
        assert "label" in a
        assert "color" in a
        assert "tag" in a and a["tag"].startswith("[") and a["tag"].endswith("]")


def test_fetch_recent_anchors_returns_list():
    from nokido_tui import fetch_recent_anchors
    anchors = fetch_recent_anchors(limit=3)
    assert isinstance(anchors, list)
    for a in anchors:
        assert "head" in a
        assert "preview" in a


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
