# -*- coding: utf-8 -*-
"""
PR-4 AXE 8 — injection persona INBYPASSABLE dans forge_agent_proxy.
Tout Provider.ask() (wrap __init_subclass__) reçoit la voix canonique.
"""
import asyncio
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from nokido_agent.app.forge_agent_proxy import Provider  # noqa: E402


class _CapProvider(Provider):
    name = "cap"
    model = "cap/m"
    cost_tier = 0  # local → firewall pré skip
    captured = {}

    async def ask(self, message, thread_messages, system_prompt, max_tokens, timeout):
        type(self).captured["sp"] = system_prompt
        return "réponse ok suffisamment longue pour passer"


def _run(coro):
    return asyncio.run(coro)


def test_provider_ask_gets_persona():
    p = _CapProvider()
    _CapProvider.captured.clear()
    _run(p.ask("salut", [], "", 100, 10))
    assert "[LAFORGE_PERSONA]" in _CapProvider.captured["sp"]


def test_provider_persona_idempotent():
    p = _CapProvider()
    _CapProvider.captured.clear()
    _run(p.ask("salut", [], "[LAFORGE_PERSONA]\ndéjà", 100, 10))
    assert _CapProvider.captured["sp"].count("[LAFORGE_PERSONA]") == 1


def test_provider_persona_disabled(monkeypatch):
    monkeypatch.setenv("FORGE_PERSONA_INJECT", "0")
    p = _CapProvider()
    _CapProvider.captured.clear()
    _run(p.ask("salut", [], "brut", 100, 10))
    assert "[LAFORGE_PERSONA]" not in _CapProvider.captured["sp"]
