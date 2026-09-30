# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_bridge_cmd
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
bridge_cmd.py — Point d'entree force pour forge_commands
=========================================================
Importe et reexporte dispatch_at depuis forge_commands.
Importe en haut de Nokido.py pour garantir le chargement au boot.
"""

from nokido_agent.app.forge_commands import dispatch_at, COMMAND_MAP, _split  # noqa: F401

__all__ = ["dispatch_at", "COMMAND_MAP", "_split"]
