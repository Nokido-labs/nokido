"""Tests for forge_swarm_agents catalog of provider-specialized Agents.

Run :
    PYTHONNOUSERSITE=1 __import__("os").path.expanduser("~/miniforge3/python.exe") -m pytest \
        tests/test_forge_swarm_agents.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `app/` importable without installing the package.
_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import pytest  # noqa: E402

import forge_swarm_agents as sa  # noqa: E402
from forge_handoff import Agent  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — every factory returns a valid Agent (name + instructions + provider)
# ─────────────────────────────────────────────────────────────────────────────

def test_every_factory_returns_valid_agent():
    for factory in sa._ALL_FACTORIES:
        agent = factory()
        assert isinstance(agent, Agent), f"{factory.__name__} did not return Agent"
        assert agent.name, f"{factory.__name__} has empty name"
        assert agent.instructions, f"{factory.__name__} has empty instructions"
        assert agent.provider, f"{factory.__name__} missing provider field"
        assert agent.mode in ("PLANNING", "EXECUTE"), (
            f"{factory.__name__} has invalid mode {agent.mode!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — all_specialists() returns the full catalog (>=10)
# ─────────────────────────────────────────────────────────────────────────────

def test_all_specialists_returns_at_least_ten():
    specialists = sa.all_specialists()
    assert len(specialists) >= 10, (
        f"expected >=10 specialists, got {len(specialists)}"
    )
    # No name collisions — each specialist must be uniquely identifiable
    names = [a.name for a in specialists]
    assert len(set(names)) == len(names), f"duplicate names in catalog: {names}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — specialists_for_use_case('code') >= 3
# ─────────────────────────────────────────────────────────────────────────────

def test_specialists_for_code_has_at_least_three():
    code_agents = sa.specialists_for_use_case("code")
    assert len(code_agents) >= 3, (
        f"expected >=3 code specialists, got {len(code_agents)}"
    )
    for a in code_agents:
        assert "code" in a.name.lower() or a.model == "code", (
            f"{a.name} doesn't look code-specialized (model={a.model})"
        )


def test_specialists_for_unknown_use_case_returns_empty():
    assert sa.specialists_for_use_case("nonexistent_xyz") == []


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — runnable_specialists filters by host capabilities + env keys
# ─────────────────────────────────────────────────────────────────────────────

def test_runnable_specialists_filters_when_no_env_keys(monkeypatch):
    # Strip every cloud env var we know about
    for env_key in set(sa.PROVIDER_ENV_KEYS.values()):
        if env_key:
            monkeypatch.delenv(env_key, raising=False)
    # Force host_info that rejects every local model (0 GB inference RAM)
    poor_host = {"effective_inference_ram_gb": 0, "vram_gb": 0, "ram_gb": 0}
    runnable = sa.runnable_specialists(host_info=poor_host)
    # With no keys AND no local capacity, runnable must be a strict subset of all
    all_count = len(sa.all_specialists())
    assert len(runnable) < all_count, (
        f"runnable {len(runnable)} should be strictly less than catalog {all_count} "
        "when host is poor and no env keys are present"
    )


def test_runnable_specialists_returns_list_of_agents():
    runnable = sa.runnable_specialists()
    assert isinstance(runnable, list)
    for a in runnable:
        assert isinstance(a, Agent)


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — key_present_for('ollama_local') always True (local)
# ─────────────────────────────────────────────────────────────────────────────

def test_key_present_for_local_providers():
    assert sa.key_present_for("ollama_local") is True
    assert sa.key_present_for("llamacpp_local") is True
    assert sa.key_present_for("lmstudio_native") is True


def test_key_present_for_unknown_provider_returns_false():
    assert sa.key_present_for("totally_made_up_provider") is False


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — key_present_for('groq_fast') depends on GROQ_API_KEY env
# ─────────────────────────────────────────────────────────────────────────────

def test_key_present_for_groq_depends_on_env(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert sa.key_present_for("groq_fast") is False
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    assert sa.key_present_for("groq_fast") is True


def test_key_present_for_groq_blank_value_is_false(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "   ")
    assert sa.key_present_for("groq_fast") is False


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — no forbidden paid provider in catalog
# ─────────────────────────────────────────────────────────────────────────────

def test_no_paid_provider_in_catalog():
    """Memory feedback_paid_providers : xAI + DeepSeek API + Anthropic forbidden."""
    for factory in sa._ALL_FACTORIES:
        agent = factory()
        assert agent.provider not in sa.FORBIDDEN_PROVIDERS, (
            f"{factory.__name__} uses forbidden paid provider {agent.provider!r}"
        )


def test_forbidden_set_contains_known_paid_providers():
    """Sanity : the forbidden set must include the obvious culprits."""
    assert "xai_grok3" in sa.FORBIDDEN_PROVIDERS
    assert "xai_grok3_mini" in sa.FORBIDDEN_PROVIDERS
    assert "anthropic" in sa.FORBIDDEN_PROVIDERS


# ─────────────────────────────────────────────────────────────────────────────
# Test 8 — heavy-refactor agents default to PLANNING mode
# ─────────────────────────────────────────────────────────────────────────────

def test_sambanova_405b_is_planning_mode():
    """code_sambanova handles multi-file refactor — must gate via <think>."""
    agent = sa.code_sambanova()
    assert agent.mode == "PLANNING", (
        "code_sambanova should default to PLANNING (sensitive sink: heavy refactor)"
    )
