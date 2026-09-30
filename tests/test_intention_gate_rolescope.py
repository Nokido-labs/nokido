# -*- coding: utf-8 -*-
"""Régression scope-défaut dérivé-système (Agent Policier — ferme le bypass opt-out).

Le gate d'intention ne doit PAS dépendre du SCOPE_SET volontaire de l'agent : quand
ROLESCOPE actif, le périmètre attendu est dérivé du profil système (specialites).
Fallback OPT-IN (LAFORGE_INTENTION_GATE_ROLESCOPE), défaut OFF = comportement inchangé.
Hermétique : lookups injectés/monkeypatchés.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "app"))
import forge_intention_gate as ig  # noqa: E402
import forge_tool_scope as ts  # noqa: E402


# ── expected_scope_for : déclaré prioritaire, sinon rôle, sinon None ──
def test_expected_scope_declared_wins(monkeypatch):
    monkeypatch.setattr(ts, "active_tools_for", lambda a: {"rag", "read"})
    monkeypatch.setattr(ts, "role_scope_for", lambda a, embed_fn=None: {"run"})
    tools, src = ts.expected_scope_for("X")
    assert tools == {"rag", "read"} and src == "declared"


def test_expected_scope_role_derived(monkeypatch):
    monkeypatch.setattr(ts, "active_tools_for", lambda a: None)
    monkeypatch.setattr(ts, "role_scope_for", lambda a, embed_fn=None: {"rag", "read"})
    tools, src = ts.expected_scope_for("X")
    assert tools == {"rag", "read"} and src == "role_derived"


def test_expected_scope_unknown_none(monkeypatch):
    monkeypatch.setattr(ts, "active_tools_for", lambda a: None)
    monkeypatch.setattr(ts, "role_scope_for", lambda a, embed_fn=None: None)
    tools, src = ts.expected_scope_for("X")
    assert tools is None and src is None


def test_role_scope_none_without_profile(monkeypatch):
    monkeypatch.setattr(ts, "_specialites_for", lambda a: None)
    assert ts.role_scope_for("X") is None


# ── gate : consomme le rôle SEULEMENT si ROLESCOPE actif ──
def test_gate_uses_rolescope_when_enabled(monkeypatch):
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_MODE", "warn")
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_ROLESCOPE", "1")
    monkeypatch.setattr(ts, "expected_scope_for", lambda a, embed_fn=None: ({"rag", "read"}, "role_derived"))
    v = ig.check_scope_drift("AGT", "nokido_ensure_service", active_tools=None, record_journal=False)
    assert v["drift"] is True and v["blocked"] is False
    assert v["scope_source"] == "role_derived"
    assert "hors scope" in v["reason"]


def test_gate_role_in_scope_aligned(monkeypatch):
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_MODE", "warn")
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_ROLESCOPE", "1")
    monkeypatch.setattr(ts, "expected_scope_for", lambda a, embed_fn=None: ({"rag", "read"}, "role_derived"))
    v = ig.check_scope_drift("AGT", "rag", active_tools=None, record_journal=False)
    assert v["aligned"] is True and v["reason"] == "in_scope"
    assert v["scope_source"] == "role_derived"


def test_gate_ignores_rolescope_when_disabled(monkeypatch):
    monkeypatch.delenv("LAFORGE_INTENTION_GATE_ROLESCOPE", raising=False)
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_MODE", "warn")
    # expected_scope_for donnerait un scope, mais flag OFF -> NE doit PAS être consulté
    monkeypatch.setattr(ts, "expected_scope_for", lambda a, embed_fn=None: ({"rag"}, "role_derived"))
    monkeypatch.setattr(ts, "active_tools_for", lambda a: None)
    v = ig.check_scope_drift("AGT", "run", active_tools=None, record_journal=False)
    assert v["reason"] == "no_declared_scope"


def test_gate_rolescope_error_mode_blocks(monkeypatch):
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_MODE", "error")
    monkeypatch.setenv("LAFORGE_INTENTION_GATE_ROLESCOPE", "1")
    monkeypatch.setattr(ts, "expected_scope_for", lambda a, embed_fn=None: ({"rag"}, "role_derived"))
    allow, reason = ig.gate_tool_call("AGT", "nokido_ensure_service", active_tools=None)
    assert allow is False and "hors scope" in reason


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v", "-p", "no:logging"]))
