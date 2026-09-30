# -*- coding: utf-8 -*-
"""tests/test_hybrid_orchestrator.py — Tests de l'assembleur (glue) hybride.

Verifie le cablage aux organes reels via injection de faux modules dans sys.modules
(hermetique, zero import d'organe lourd) + le pont async->sync.
"""
from __future__ import annotations

import sys
import types

import pytest

from sandbox import hybrid_orchestrator as ho


def _fake_module(name: str, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def test_text_of_variants():
    assert ho._text_of("brut") == "brut"
    assert ho._text_of({"response": "R"}) == "R"
    assert ho._text_of({"content": "C"}) == "C"


def test_sync_bridge_runs_coroutine():
    async def _co():
        return 42

    assert ho._sync(_co()) == 42


def test_condense_fn_uses_router(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "forge_llm_router",
        _fake_module(
            "forge_llm_router",
            router_call=lambda prompt, use_case="general", max_tokens=500, **k: {"response": "requete reecrite"},
        ),
    )
    out = ho.condense_fn("le", [{"role": "user", "content": "rapport ventes"}])
    assert out == "requete reecrite"


def test_condense_fn_fallback_on_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("router down")

    monkeypatch.setitem(sys.modules, "forge_llm_router", _fake_module("forge_llm_router", router_call=_boom))
    assert ho.condense_fn("ma requete", [{"role": "user", "content": "x"}]) == "ma requete"


def test_route_local_general_is_none(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "forge_semantic_route",
        _fake_module("forge_semantic_route", semantic_route=lambda t, **k: ("general", 0.2)),
    )
    assert ho.route_local_fn("bonjour") == (None, 0.2)


def test_route_local_real_intent(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "forge_semantic_route",
        _fake_module("forge_semantic_route", semantic_route=lambda t, **k: ("code", 0.8)),
    )
    assert ho.route_local_fn("ecris du python") == ("code", 0.8)


def test_extract_claude_parses_json(monkeypatch):
    async def _fake_ask(prompt, rag_context=True, max_tokens=2000, **k):
        return {"response": 'ok: {"intent": "send_email", "parameters": {"to": "x"}} .'}

    monkeypatch.setitem(sys.modules, "forge_agent_proxy", _fake_module("forge_agent_proxy", ask_claude=_fake_ask))
    out = ho.extract_claude_fn([{"role": "user", "content": "envoie mail"}])
    assert out["intent"] == "send_email"
    assert out["parameters"] == {"to": "x"}
    assert out["tool_use_id"].startswith("toolu_")


def test_executor_dispatch_and_error(monkeypatch):
    class _Reg:
        async def dispatch(self, name, args, agent, ring):
            return "resultat ok" if name == "ok_tool" else {"error": "inconnu"}

    monkeypatch.setitem(sys.modules, "forge_mcp_registry", _fake_module("forge_mcp_registry", get_registry=lambda: _Reg()))
    ex = ho.make_executor_fn("CLAUDE", 2)
    assert ex("ok_tool", {}) == "resultat ok"
    with pytest.raises(RuntimeError):
        ex("bad_tool", {})


def test_build_and_run_end_to_end(monkeypatch):
    """Chaine cablee complete (organes faux) : route locale forte -> exec local -> SUCCESS."""
    monkeypatch.setitem(
        sys.modules,
        "forge_semantic_route",
        _fake_module("forge_semantic_route", semantic_route=lambda t, **k: ("refund", 0.9)),
    )

    class _Reg:
        async def dispatch(self, name, args, agent, ring):
            return f"exec:{name}"

    monkeypatch.setitem(sys.modules, "forge_mcp_registry", _fake_module("forge_mcp_registry", get_registry=lambda: _Reg()))

    state = ho.run_hybrid("je veux un remboursement")
    assert state.intent == "refund"
    assert state.local_execution_result == "exec:refund"
    assert state.status == "SUCCESS"
