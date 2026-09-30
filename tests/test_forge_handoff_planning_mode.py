"""Tests for forge_handoff Planning Mode + <think> gate.

Inspired by Devin AI dualite (PLANNING vs STANDARD) and Claude Code 2.0
(TodoWrite before multi-step work). See CLAUDE.md section "Planning Mode +
<think> Gate" for the design rationale.

Run :
    __import__("os").path.expanduser("~/miniforge3/python.exe") -m pytest tests/test_forge_handoff_planning_mode.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `app/` importable without installing the package.
_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import forge_handoff  # noqa: E402
from forge_handoff import PLANNING_PREFIX, Agent, _llm_round  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — backward compat : default mode is EXECUTE
# ─────────────────────────────────────────────────────────────────────────────

def test_agent_default_mode_is_execute():
    a = Agent(name="X", instructions="be useful")
    assert a.mode == "EXECUTE", (
        "Default must stay EXECUTE so existing callers keep working unchanged."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — plan_first() returns a PLANNING copy (immutable)
# ─────────────────────────────────────────────────────────────────────────────

def test_plan_first_returns_planning_copy_without_mutating_original():
    original = Agent(name="X", instructions="be useful")
    planning = original.plan_first()
    assert planning.mode == "PLANNING"
    assert original.mode == "EXECUTE", (
        "plan_first() must be immutable — Swarm pattern reuses Agent definitions."
    )
    # Same identity-bearing fields are preserved
    assert planning.name == original.name
    assert planning.instructions == original.instructions
    assert planning.model == original.model
    assert planning.text_handoff == original.text_handoff
    # Different object, same content + new mode
    assert planning is not original


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — explicit PLANNING construction is accepted
# ─────────────────────────────────────────────────────────────────────────────

def test_agent_accepts_explicit_planning_mode():
    a = Agent(name="X", instructions="be useful", mode="PLANNING")
    assert a.mode == "PLANNING"
    # And EXECUTE explicit works too
    b = Agent(name="Y", instructions="be useful", mode="EXECUTE")
    assert b.mode == "EXECUTE"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — _llm_round() injects PLANNING_PREFIX in the system message
#           when current agent is in PLANNING mode.
# ─────────────────────────────────────────────────────────────────────────────

def test_llm_round_injects_planning_prefix_when_mode_planning(monkeypatch):
    captured: dict = {}

    def _fake_router(prompt: str, use_case: str, max_tokens: int = 500) -> dict:
        captured["prompt"] = prompt
        captured["use_case"] = use_case
        return {
            "message": {"role": "assistant", "content": "ok"},
            "tool_calls": [],
            "_router_meta": {},
        }

    # Patch the router call so no real LLM backend is touched.
    monkeypatch.setattr(forge_handoff, "_call_router", _fake_router)

    a = Agent(name="X", instructions="be useful", model="general", mode="PLANNING")
    out = _llm_round(a, [{"role": "user", "content": "audit prod DB"}], with_tools=False)

    assert out["message"]["content"] == "ok"
    assert "PLANNING PHASE" in captured["prompt"], (
        "Planning prefix must reach the LLM through the system message."
    )
    assert PLANNING_PREFIX.strip().splitlines()[0] in captured["prompt"]
    # Original instructions must still be present (prefix, not replace)
    assert "be useful" in captured["prompt"]


def test_llm_round_no_prefix_when_mode_execute(monkeypatch):
    captured: dict = {}

    def _fake_router(prompt: str, use_case: str, max_tokens: int = 500) -> dict:
        captured["prompt"] = prompt
        return {
            "message": {"role": "assistant", "content": "ok"},
            "tool_calls": [],
            "_router_meta": {},
        }

    monkeypatch.setattr(forge_handoff, "_call_router", _fake_router)

    a = Agent(name="X", instructions="be useful", model="general")  # default EXECUTE
    _llm_round(a, [{"role": "user", "content": "ping"}], with_tools=False)

    assert "PLANNING PHASE" not in captured["prompt"], (
        "EXECUTE mode must NOT inject the planning prefix (backward compat)."
    )
