# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_dispatch
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
forge_dispatch.py — REGISTRY unifié des commandes @ Nokido
============================================================
Expose REGISTRY : dict {cmd: async_handler(app, cmd_line, parts, cmd)}
Utilisé par tools/mcp_nr.py check_registry (attend >= 26 cmds, toutes async).

Règle NR :
  - len(REGISTRY) >= 26
  - toutes les valeurs sont des coroutines (inspect.iscoroutinefunction)
  - commandes attendues : @help @audit @scan @mode @collab @rag @loop @role
                          @estim @run @ssh @disco @evolve @agentic @tools
                          @ci @workflow @proxy (+ autres)
"""

import logging
import os

logger = logging.getLogger("Nokido.Dispatch")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _lazy(module: str, fn: str) -> object:
    """
    Import lazy — résout la fonction au moment de l'appel, pas au chargement.
    Permet à forge_dispatch d'être importé par le NR (avec mock __main__)
    sans que les imports lourds de forge_handlers échouent.
    """

    async def _handler(app, cmd_line: str, parts: list, cmd: str) -> None:
        """Handler.

        Args:
            app: Description.
            cmd_line: Description.
            parts: Description.
            cmd: Description.
        """
        args = " ".join(parts[1:]) if len(parts) > 1 else ""
        try:
            import importlib

            mod = importlib.import_module(module)
            func = getattr(mod, fn)
            await func(app, args)
        except Exception as e:
            try:
                app._chat_log().write(f"[red]{cmd} erreur: {e}[/]")
            except Exception:
                pass

    return _handler


def _lazy_at(module: str, fn: str) -> object:
    """Import lazy pour handlers AT_DISPATCH (signature différente)."""

    async def _handler(app, cmd_line: str, parts: list, cmd: str) -> None:
        """Handler.

        Args:
            app: Description.
            cmd_line: Description.
            parts: Description.
            cmd: Description.
        """
        try:
            import importlib

            mod = importlib.import_module(module)
            func = getattr(mod, fn)
            await func(app, cmd_line, parts, cmd)
        except Exception as e:
            try:
                app._chat_log().write(f"[red]{cmd} erreur: {e}[/]")
            except Exception:
                pass

    return _handler


def _delegate(method_name: str) -> object:
    """Délègue à app._handle_X(args) — pour cmds gérées dans Nokido.py."""

    async def _handler(app, cmd_line: str, parts: list, cmd: str) -> None:
        """Handler.

        Args:
            app: Description.
            cmd_line: Description.
            parts: Description.
            cmd: Description.
        """
        args = " ".join(parts[1:]) if len(parts) > 1 else ""
        try:
            method = getattr(app, method_name, None)
            if method:
                await method(args)
            else:
                app._chat_log().write(f"[yellow]⚠ {cmd} non disponible[/]")
        except Exception as e:
            try:
                app._chat_log().write(f"[red]{cmd} erreur: {e}[/]")
            except Exception:
                pass

    return _handler


# ── REGISTRY complet — toutes entrées sont des coroutines ────────────────────
# Minimum 26 cmds, toutes async (inspect.iscoroutinefunction doit retourner True)
REGISTRY: dict = {
    # ── AT_DISPATCH — réseau/infra (lazy) ────────────────────────────────
    "@ssh": _lazy_at("forge_at_dispatch", "handle_at_ssh"),
    "@ollama": _lazy_at("forge_at_dispatch", "handle_at_ollama"),
    "@scan": _lazy_at("forge_at_dispatch", "handle_at_scan"),
    "@web": _lazy_at("forge_at_dispatch", "handle_at_web"),
    "@agentic": _lazy_at("forge_at_dispatch", "handle_at_agentic"),
    "@ragas": _lazy_at("forge_at_dispatch", "handle_at_ragas"),
    "@services": _lazy_at("forge_at_dispatch", "handle_at_services"),
    "@ids": _lazy_at("forge_at_dispatch", "handle_at_ids"),
    # ── Handlers externalisés (lazy) ─────────────────────────────────────
    "@nr": _lazy("forge_handlers", "_handle_nr"),
    "@rag": _lazy("forge_handler_rag", "_handle_rag"),
    "@role": _lazy("forge_handler_agents", "_handle_role"),
    "@mode": _lazy("forge_handler_agents", "_handle_mode"),
    "@workflow": _lazy("forge_handler_ci", "_handle_workflow"),
    "@ci": _lazy("forge_handler_ci", "_handle_ci"),
    "@apply": _lazy("forge_handler_patch", "_handle_apply"),
    "@run": _lazy("forge_handler_patch", "_handle_run"),
    # ── Délégués à Nokido.py ─────────────────────────────────────────────
    "@help": _delegate("_handle_help"),
    "@audit": _delegate("_handle_audit"),
    "@loop": _delegate("_handle_loop"),
    "@collab": _delegate("_handle_collab"),
    "@proxy": _delegate("_handle_proxy"),
    "@tools": _delegate("_handle_tools"),
    "@estim": _delegate("_handle_estim"),
    "@disco": _delegate("_handle_disco"),
    "@chain": _delegate("_handle_chain"),
    "@mem": _delegate("_handle_mem"),
    "@model": _delegate("_handle_model"),
    # Advanced handlers v17
    "@optimize": _lazy("forge_handler_advanced", "handle_optimize_core"),
    "@sprint": _lazy("forge_handler_advanced", "handle_sprint_refactor"),
    "@factory": _lazy("forge_handler_advanced", "handle_app_factory"),
    "@llm": _lazy("forge_handler_advanced", "handle_multi_llm"),
    "@search": _lazy("forge_handler_advanced", "handle_deep_search"),
    "@safety": _lazy("forge_handler_advanced", "handle_safety_audit"),
    "@build": _lazy("forge_handler_build", "handle_build_new_app"),
    "@evolve": _lazy("forge_handler_evolve", "handle_evolve"),  # Siloed Reasoning Engine
    "@fragment": _lazy("forge_handler_fragment", "handle_fragment"),  # Fragmenteur + NoiseGuardian
    "@skill": _lazy("forge_handler_skill", "handle_skill"),  # ClawHub Skill Registry
    "@triad": _lazy("forge_triad_authority", "run_triad"),
    "@harvest": _lazy("forge_knowledge_harvester", "_handle_harvest_cmd"),
}

# Commandes de la capacité déportée (lab borné) : enregistrées SEULEMENT si le lab
# est explicitement activé (NOKIDO_REDTEAM_INTENTS_JSON). Gel, pas suppression — le
# cœur ne les expose pas dans le REGISTRY par défaut.
if os.environ.get("NOKIDO_REDTEAM_INTENTS_JSON"):
    REGISTRY["@exegol"] = _lazy("forge_handler_exegol", "handle_exegol")
    REGISTRY["@cai"] = _lazy("forge_cai_bridge", "_handle_cai")

__all__ = ["REGISTRY"]
