# -*- coding: utf-8 -*-
"""Régression gate d'intention (Agent Policier moitié 2/2) — dérive de scope déclaré.

Pure function : active_tools injecté, record_journal=False (hermétique).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "app"))
import forge_intention_gate as ig  # noqa: E402


def _chk(agent, tool, active, **kw):
    return ig.check_scope_drift(agent, tool, active_tools=active, record_journal=False, **kw)


def test_no_declared_scope_is_aligned(monkeypatch):
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_MODE", "warn")
    v = _chk("CLAUDE", "nokido_ensure_service", None)
    assert v["aligned"] is True and v["drift"] is False
    assert v["reason"] == "no_declared_scope"


def test_tool_in_scope_is_aligned(monkeypatch):
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_MODE", "warn")
    v = _chk("CLAUDE", "rag", {"rag", "read", "run"})
    assert v["aligned"] is True and v["reason"] == "in_scope"


def test_drift_warn_mode_flags_but_does_not_block(monkeypatch):
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_MODE", "warn")
    v = _chk("CLAUDE", "nokido_ensure_service", {"rag", "read"})
    assert v["drift"] is True
    assert v["blocked"] is False  # WARN ne bloque jamais
    allow, _ = ig.gate_tool_call("CLAUDE", "nokido_ensure_service", active_tools={"rag", "read"})
    assert allow is True


def test_drift_error_mode_blocks(monkeypatch):
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_MODE", "error")
    v = _chk("CLAUDE", "nokido_ensure_service", {"rag", "read"})
    assert v["drift"] is True and v["blocked"] is True
    allow, reason = ig.gate_tool_call("CLAUDE", "nokido_ensure_service", active_tools={"rag", "read"})
    assert allow is False and "hors scope" in reason


def test_off_mode_disables_gate(monkeypatch):
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_MODE", "off")
    v = _chk("CLAUDE", "nokido_ensure_service", {"rag", "read"})
    assert v["aligned"] is True and v["reason"] == "gate_off"


def test_unknown_mode_defaults_warn(monkeypatch):
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_MODE", "bogus")
    v = _chk("CLAUDE", "nokido_ensure_service", {"rag"})
    assert v["mode"] == "warn" and v["drift"] is True and v["blocked"] is False


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v", "-p", "no:logging"]))
