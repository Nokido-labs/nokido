# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [RED]
DATE:2026-04-24 | VER:v_forge_failsafe_router
#FORGE:[score:95|agent:gemini-cli|temp:0.00|risk:0.05|ast:OK|test:OK|lint:OK|color:RED|attempt:1]
CONTRAINTE: SPOF Elimination (Hub bypass)
"""
from __future__ import annotations
__FORGE_COLOR__ = "RED"
__FORGE_TAGS__ = "#FORGE:[score:95|agent:gemini-cli|temp:0.00|risk:0.05|ast:OK|test:OK|lint:OK|color:RED|attempt:1]"

import asyncio
import httpx
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("Nokido.Failsafe.Router")


class FailsafeRouter:
    """Routeur capable de bypasser le Hub MCP s'il est hors-ligne."""

    def __init__(self, hub_url: str = "http://127.0.0.1:7440/rpc"):
        self.hub_url = hub_url
        self.timeout = 2.0  # Seuil critique de SPOF

    async def call_tool(self, tool_name: str, params: Dict[str, Any]) -> str:
        """Tente le Hub, sinon bascule en local (Mode Survie)."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Simulation d'appel JSON-RPC au Hub
                payload = {"jsonrpc": "2.0", "method": tool_name, "params": params, "id": 1}
                response = await client.post(self.hub_url, json=payload)
                if response.status_code == 200:
                    return response.json().get("result", "")
        except (httpx.ConnectError, httpx.TimeoutException):
            logger.warning(f"🚨 HUB DOWN! Activation du Failsafe pour {tool_name}")
            return await self._run_survival_mode(tool_name, params)

        return "Erreur inconnue"

    async def _run_survival_mode(self, tool_name: str, params: Dict[str, Any]) -> str:
        """Exécution directe sans passer par la couche réseau/Hub."""
        # Mapping des outils critiques vers leurs scripts d'origine
        survival_map = {
            "rag_search": "app/forge_rag_engine.py",
            "net_scan": "recon_silo/network_profiler.py",
            "code_audit": "app/forge_handler_ci.py",
        }

        if tool_name not in survival_map:
            return f"❌ Failsafe : L'outil {tool_name} n'est pas disponible en mode survie."

        script_path = survival_map[tool_name]
        try:
            # On lance le script en direct via l'interpréteur actuel
            cmd = [sys.executable, script_path, "--failsafe"]
            # Ajout des params en arguments (simplifié pour la démo)
            for k, v in params.items():
                cmd.extend([f"--{k}", str(v)])

            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return stdout.decode().strip()
            else:
                return f"❌ Erreur Survie : {stderr.decode().strip()}"

        except Exception as e:
            return f"❌ Crash Failsafe : {e}"


if __name__ == "__main__":
    router = FailsafeRouter()
    print("🔋 Test du Failsafe (Hub actif?)")
    # Simulation d'un appel RAG
    res = asyncio.run(router.call_tool("rag_search", {"query": "test"}))
    print(f"Résultat : {res}")
