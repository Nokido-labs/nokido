"""
app/ui/commands_via_facade.py - Commandes TUI qui utilisent EXCLUSIVEMENT la facade.

OBJECTIF (Priorite 1 Gemini - 2026-04):
  Fournir des commandes d'exemple qui montrent le NOUVEAU pattern :
  AUCUN import direct de forge_agents, forge_rag_engine, forge_code, etc.
  Tout passe par NokidoFacade via facade_accessor.

Ces commandes peuvent etre :
  - Enregistrees dans la TUI Textual (ajoutees au menu @commands)
  - Appelees via CLI (tools/nokido_status.py)
  - Utilisees dans des tests d integration

PATTERN RECOMMANDE pour nouvelles features Nokido.

Commands disponibles :
  - cmd_ask_llm : demande LLM avec backend au choix
  - cmd_status : dashboard complet via facade
  - cmd_scan_code : scan securite d un snippet via facade

AUCUN de ces imports :
  - forge_ollama_bridge, forge_gemini_bridge, forge_llamacpp
  - forge_rag_engine
  - forge_code_guard, forge_code
  - forge_agents
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from app.ui.facade_accessor import get_ui_facade, get_ui_facade_sync


# ═══════════════════════════════════════════════════════════════════════════
# COMMAND 1 : ask_llm
# ═══════════════════════════════════════════════════════════════════════════


async def cmd_ask_llm(prompt: str, backend: str = "ollama", context: str = "", **kwargs: Any) -> str:
    """Demande LLM via la facade async.

    Args:
        prompt: Prompt utilisateur.
        backend: "ollama", "gemini", "llamacpp", "litellm", "openrouter".
        context: Contexte optionnel.
        **kwargs: Autres params (temperature, max_tokens).

    Returns:
        Reponse texte du LLM.

    Example:
        answer = await cmd_ask_llm("explique DI", backend="gemini")
    """
    facade = get_ui_facade()
    return await facade.ask_llm_async(prompt, backend=backend, context=context, **kwargs)


def cmd_ask_llm_sync(prompt: str, backend: str = "ollama", **kwargs: Any) -> str:
    """Version sync de cmd_ask_llm (pour scripts non-async)."""
    facade = get_ui_facade_sync()
    return facade.ask_llm(prompt, backend=backend, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# COMMAND 2 : status dashboard
# ═══════════════════════════════════════════════════════════════════════════


async def cmd_status() -> Dict[str, Any]:
    """Dashboard complet : agents + rag + settings + breakers.

    Utilise asyncio.gather pour paralleliser les appels.

    Returns:
        Dict avec cles: agents, rag, domains, breakers.
    """
    facade = get_ui_facade()
    # Parallelisation des 3 status
    agents_s, rag_s, domains = await asyncio.gather(
        facade.agents_status_async(),
        facade.rag_status_async(),
        asyncio.to_thread(get_ui_facade_sync().settings_domains),
    )

    # Circuit breakers (sync, pas expose en async encore)
    try:
        from nokido_agent.app.forge_llm_router import get_circuit_breakers_snapshot

        breakers = get_circuit_breakers_snapshot()
    except ImportError:
        breakers = {"_note": "forge_llm_router indisponible"}

    return {
        "agents": agents_s,
        "rag": rag_s,
        "domains": domains,
        "breakers": breakers,
    }


def cmd_status_sync() -> Dict[str, Any]:
    """Version sync de cmd_status."""
    return asyncio.run(cmd_status())


# ═══════════════════════════════════════════════════════════════════════════
# COMMAND 3 : scan_code
# ═══════════════════════════════════════════════════════════════════════════


async def cmd_scan_code(code: str, language: str = "python") -> Dict[str, Any]:
    """Scan un snippet de code pour detecter patterns dangereux.

    Args:
        code: Source a analyser.
        language: Langage (python par defaut).

    Returns:
        Dict avec keys: safe, issues, patterns_detected.

    Example:
        report = await cmd_scan_code("x = 1 + 1")
        assert report["safe"]
    """
    facade = get_ui_facade()
    return await facade.scan_code_async(code, language=language)


def cmd_scan_code_sync(code: str, language: str = "python") -> Dict[str, Any]:
    """Version sync de cmd_scan_code."""
    return get_ui_facade_sync().scan_code(code, language=language)


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY (pour dispatch par nom depuis la TUI)
# ═══════════════════════════════════════════════════════════════════════════


COMMANDS_REGISTRY = {
    "ask": cmd_ask_llm,
    "ask_sync": cmd_ask_llm_sync,
    "status": cmd_status,
    "status_sync": cmd_status_sync,
    "scan": cmd_scan_code,
    "scan_sync": cmd_scan_code_sync,
}


def get_command(name: str):
    """Retourne une commande par nom depuis le registry."""
    return COMMANDS_REGISTRY.get(name)


def list_commands() -> list[str]:
    """Liste les noms des commandes disponibles."""
    return list(COMMANDS_REGISTRY.keys())


__all__ = [
    "cmd_ask_llm",
    "cmd_ask_llm_sync",
    "cmd_status",
    "cmd_status_sync",
    "cmd_scan_code",
    "cmd_scan_code_sync",
    "COMMANDS_REGISTRY",
    "get_command",
    "list_commands",
]
