"""Tests for forge_handoff multi-provider dispatch (Agent.provider field).

Verifies the 3-branch dispatch in _llm_round() :
  1. provider=None         -> legacy (_call_ollama_chat or _call_router)
  2. provider in LOCAL      -> _call_ollama_chat (with agent.model as tag)
  3. provider=<cloud_name>  -> _call_router_provider (forced single slot),
                              with quota gate + fallback chain on error.

Run :
    PYTHONNOUSERSITE=1 __import__("os").path.expanduser("~/miniforge3/python.exe") -m pytest \
        tests/test_forge_handoff_multiprovider.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `app/` importable without installing the package.
_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import pytest  # noqa: E402

import forge_handoff  # noqa: E402
from forge_handoff import Agent, _llm_round  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — backward compat : Agent without provider keeps legacy dispatch
# ─────────────────────────────────────────────────────────────────────────────

def test_agent_without_provider_uses_legacy_router(monkeypatch):
    """Default Agent(provider=None) + model='general' → _call_router path."""
    captured: dict = {}

    def _fake_router(prompt: str, use_case: str, max_tokens: int = 500) -> dict:
        captured["called"] = "router"
        captured["use_case"] = use_case
        return {
            "message": {"role": "assistant", "content": "legacy-router-ok"},
            "tool_calls": [],
            "_router_meta": {"ok": True},
        }

    def _fake_ollama(model, messages, tools=None, **kw) -> dict:
        captured["called"] = "ollama"
        return {"message": {"role": "assistant", "content": "should-not-reach"},
                "tool_calls": []}

    monkeypatch.setattr(forge_handoff, "_call_router", _fake_router)
    monkeypatch.setattr(forge_handoff, "_call_ollama_chat", _fake_ollama)

    a = Agent(name="legacy", instructions="be useful", model="general")
    assert a.provider is None, "default provider must be None for backward compat"

    out = _llm_round(a, [{"role": "user", "content": "hi"}], with_tools=False)
    assert captured["called"] == "router"
    assert captured["use_case"] == "general"
    assert out["message"]["content"] == "legacy-router-ok"


def test_agent_without_provider_with_ollama_model_uses_direct_ollama(monkeypatch):
    """provider=None + model with ':' → direct _call_ollama_chat (legacy)."""
    captured: dict = {}

    def _fake_ollama(model, messages, tools=None, **kw) -> dict:
        captured["called"] = "ollama"
        captured["model"] = model
        return {"message": {"role": "assistant", "content": "ollama-direct-ok"},
                "tool_calls": []}

    monkeypatch.setattr(forge_handoff, "_call_ollama_chat", _fake_ollama)

    a = Agent(name="legacy_o", instructions="x", model="qwen2.5-coder:7b")
    _llm_round(a, [{"role": "user", "content": "go"}], with_tools=False)
    assert captured["called"] == "ollama"
    assert captured["model"] == "qwen2.5-coder:7b"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — provider=<cloud_name> dispatches via _call_router_provider
# ─────────────────────────────────────────────────────────────────────────────

def test_agent_with_cloud_provider_dispatches_forced_slot(monkeypatch):
    """Agent(provider='groq_fast') → _call_router_provider('groq_fast')."""
    captured: dict = {}

    def _fake_force(prompt: str, provider: str, max_tokens: int = 500,
                    temperature: float = 0.2, timeout: int = 30) -> dict:
        captured["forced_provider"] = provider
        captured["prompt"] = prompt
        return {
            "message": {"role": "assistant", "content": "groq-forced-ok"},
            "tool_calls": [],
            "_router_meta": {"ok": True, "provider": "groq_fast"},
        }

    monkeypatch.setattr(forge_handoff, "_call_router_provider", _fake_force)

    a = Agent(name="cloud_x", instructions="audit", model="code",
              provider="groq_fast")
    out = _llm_round(a, [{"role": "user", "content": "review"}], with_tools=False)

    assert captured["forced_provider"] == "groq_fast"
    assert out["message"]["content"] == "groq-forced-ok"
    # Original instructions must be in the flattened prompt sent to the router
    assert "audit" in captured["prompt"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — quota exhausted → _call_router_provider raises → fallback cascade
# ─────────────────────────────────────────────────────────────────────────────

def test_quota_exhausted_falls_back_to_use_case_cascade(monkeypatch):
    """Forced provider raises (quota) → _call_router(use_case=agent.model)."""
    sequence: list[str] = []

    def _fake_force(prompt: str, provider: str, **kw) -> dict:
        sequence.append(f"force:{provider}")
        raise RuntimeError(f"provider {provider} quota exhausted")

    def _fake_router(prompt: str, use_case: str, max_tokens: int = 500) -> dict:
        sequence.append(f"cascade:{use_case}")
        return {
            "message": {"role": "assistant", "content": "fallback-cascade-ok"},
            "tool_calls": [],
            "_router_meta": {"ok": True, "provider": "ollama_local"},
        }

    monkeypatch.setattr(forge_handoff, "_call_router_provider", _fake_force)
    monkeypatch.setattr(forge_handoff, "_call_router", _fake_router)

    a = Agent(name="quota_test", instructions="x", model="code",
              provider="groq_fast")
    out = _llm_round(a, [{"role": "user", "content": "ping"}], with_tools=False)

    assert sequence == ["force:groq_fast", "cascade:code"], (
        f"expected force then cascade, got {sequence}"
    )
    assert out["message"]["content"] == "fallback-cascade-ok"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — provider HS + cascade HS → degraded text-handoff envelope
# ─────────────────────────────────────────────────────────────────────────────

def test_provider_and_cascade_both_dead_returns_degraded_envelope(monkeypatch):
    """When everything fails, return a stable envelope so run_swarm doesn't crash."""

    def _fake_force(prompt: str, provider: str, **kw) -> dict:
        raise RuntimeError("HTTP 503 service unavailable")

    def _fake_router(prompt: str, use_case: str, max_tokens: int = 500) -> dict:
        raise RuntimeError("cascade also down")

    monkeypatch.setattr(forge_handoff, "_call_router_provider", _fake_force)
    monkeypatch.setattr(forge_handoff, "_call_router", _fake_router)

    a = Agent(name="dead", instructions="x", model="code",
              provider="groq_fast")
    out = _llm_round(a, [{"role": "user", "content": "ping"}], with_tools=False)

    assert "message" in out
    assert "tool_calls" in out
    assert out["tool_calls"] == []
    # Degraded envelope must mark provider unavailable so run_swarm can terminate
    assert "unavailable" in out["message"]["content"].lower() or \
           "fallback" in out["message"]["content"].lower()
    meta = out.get("_router_meta", {})
    assert meta.get("ok") is False
    assert meta.get("fallback") == "text-handoff"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — local provider explicit (provider='ollama_local') uses direct chat
# ─────────────────────────────────────────────────────────────────────────────

def test_explicit_local_provider_uses_direct_ollama(monkeypatch):
    """provider='ollama_local' + concrete model tag → _call_ollama_chat."""
    captured: dict = {}

    def _fake_ollama(model, messages, tools=None, **kw) -> dict:
        captured["model"] = model
        captured["msg_count"] = len(messages)
        return {"message": {"role": "assistant", "content": "local-ok"},
                "tool_calls": []}

    monkeypatch.setattr(forge_handoff, "_call_ollama_chat", _fake_ollama)

    a = Agent(name="local_qwen", instructions="x",
              model="qwen2.5-coder:7b-instruct-q4_K_M",
              provider="ollama_local")
    _llm_round(a, [{"role": "user", "content": "go"}], with_tools=False)

    assert captured["model"] == "qwen2.5-coder:7b-instruct-q4_K_M"
    # 1 system + 1 user
    assert captured["msg_count"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — _quota_should_skip returns False on missing module (soft-fail)
# ─────────────────────────────────────────────────────────────────────────────

def test_quota_should_skip_soft_fails_on_exception(monkeypatch):
    """If forge_provider_quota is missing/broken, never block the call."""
    import builtins as _b
    real_import = _b.__import__

    def _bad_import(name, *a, **kw):
        if name == "forge_provider_quota":
            raise ImportError("simulated missing module")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(_b, "__import__", _bad_import)
    assert forge_handoff._quota_should_skip("groq_fast") is False
