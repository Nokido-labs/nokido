"""Police authorize() — décision UNIQUE identité×capacité (forge_videur).

authorize() compose resolve_identity (ring) + _tool_needed_ring (ring requis du tool,
source unique). C'est l'interface que le router de serving (Gemini) consulte AVANT de router.
Invariants : allow ssi ring <= needed ; pas de tool -> allow ; capacité KO -> fail-CLOSED.
"""
import importlib

import pytest

vid = importlib.import_module("forge_videur")


@pytest.fixture(autouse=True)
def _iso(monkeypatch):
    monkeypatch.setattr(vid, "_load_store", lambda: {})
    monkeypatch.setattr(vid, "_DEV_IS_ARMED_OVERRIDE", (lambda: (False, 0)), raising=False)
    monkeypatch.setitem(vid._SEED_RING, "CLAUDE", 1)


def _auth(tool):
    return vid.authorize("CLAUDE", token="x", local=True, tool=tool, agent_tokens={}, hub_token="")


def test_allow_when_ring_le_needed(monkeypatch):
    monkeypatch.setattr(vid, "_TOOL_RING_OVERRIDE", (lambda t: 2), raising=False)
    r = _auth("docker_action")
    assert r["allow"] is True and r["needed_ring"] == 2 and r["ring"] == 1


def test_deny_when_ring_gt_needed(monkeypatch):
    monkeypatch.setattr(vid, "_TOOL_RING_OVERRIDE", (lambda t: 0), raising=False)
    r = _auth("some_tool")
    assert r["allow"] is False and r["needed_ring"] == 0


def test_no_tool_allows(monkeypatch):
    r = _auth(None)
    assert r["allow"] is True and r["ring"] == 1


def test_capability_error_fail_closed(monkeypatch):
    def _boom(t):
        raise RuntimeError("db down")
    monkeypatch.setattr(vid, "_TOOL_RING_OVERRIDE", _boom, raising=False)
    r = _auth("some_tool")
    assert r["allow"] is False  # fail-closed
