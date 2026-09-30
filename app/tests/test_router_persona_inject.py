# -*- coding: utf-8 -*-
"""
PR-3 AXE 8 — injection persona unifiée dans forge_llm_router.call_cascade.
Vérifie que le `system` envoyé au LLM porte la voix canonique [LAFORGE_PERSONA],
et l'idempotence (pas de double injection).
"""
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))


class _FakeSlot:
    is_available = True
    is_configured = True
    _cooldown = 0.0
    api_key = "x"
    config = {"models": ["fakeslot/m"]}

    def record_call(self):
        pass

    def record_failure(self):
        pass

    def record_rate_limit(self, *a):
        pass


class _FakeMsg:
    def __init__(self, c):
        self.content = c


class _FakeChoice:
    def __init__(self, c):
        self.message = _FakeMsg(c)


class _FakeResp:
    def __init__(self):
        self.choices = [_FakeChoice("réponse ok suffisamment longue")]
        self.usage = type("U", (), {"total_tokens": 5})()


def _setup(monkeypatch):
    from nokido_agent.app import forge_llm_router as flr
    import litellm

    captured = {}

    def fake_completion(**kw):
        captured["messages"] = kw["messages"]
        return _FakeResp()

    monkeypatch.setattr(litellm, "completion", fake_completion)
    monkeypatch.setattr(flr, "USE_CASE_CHAINS", {"general": ["fakeslot"]})
    try:
        r = flr.LLMRouter()
    except Exception:
        pytest.skip("LLMRouter non instanciable dans cet env")
    r._slots = {"fakeslot": _FakeSlot()}
    return r, captured


def _system_of(captured):
    msgs = captured.get("messages", [])
    for m in msgs:
        if m.get("role") == "system":
            return m.get("content", "")
    return ""


def test_call_cascade_injects_persona(monkeypatch):
    r, captured = _setup(monkeypatch)
    res = r.call_cascade("bonjour", use_case="general")
    assert res.get("ok") is True
    assert "[LAFORGE_PERSONA]" in _system_of(captured)


def test_call_cascade_persona_idempotent(monkeypatch):
    r, captured = _setup(monkeypatch)
    # system déjà marqué → pas de double injection
    r.call_cascade("bonjour", use_case="general", system="[LAFORGE_PERSONA]\ndéjà là")
    assert _system_of(captured).count("[LAFORGE_PERSONA]") == 1


def test_call_cascade_inject_disabled(monkeypatch):
    r, captured = _setup(monkeypatch)
    r.call_cascade("bonjour", use_case="general", system="brut", inject_persona=False)
    assert "[LAFORGE_PERSONA]" not in _system_of(captured)
