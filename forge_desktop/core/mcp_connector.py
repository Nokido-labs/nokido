"""
forge_desktop/core/mcp_connector.py
=====================================
Client MCP agile pour OneMCP — connecteur "Souverain".

Architecture :
  - Fire & Forget  → notifications, events, heartbeat (ring 5)
  - Await strict   → données vitales avec timeout configurable
  - Amovible       → si le serveur distant ne répond pas, la GUI continue

Modes de transport supportés :
  - stdio   → serveur local Python (mcp_server_tools.py)
  - sse     → serveur HTTP distant (OneMCP, Neuro-Grid)
  - ws      → WebSocket (futur)

Ring 5 — Cascade :
  Les appels MCP non-vitaux sont enfilés dans une queue asyncio
  et traités en arrière-plan sans bloquer le thread Qt.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
APP  = ROOT / "app"

logger = logging.getLogger("Nokido.MCP")

# ── Imports MCP SDK ───────────────────────────────────────────────────────────
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    HAS_MCP_STDIO = True
except ImportError:
    HAS_MCP_STDIO = False

try:
    from mcp.client.sse import sse_client
    HAS_MCP_SSE = True
except ImportError:
    HAS_MCP_SSE = False

# Timeouts
TIMEOUT_VITAL     = 10.0   # données vitales (Kill Switch, ring 0)
TIMEOUT_STANDARD  = 5.0    # appels normaux
TIMEOUT_NOTIFY    = 2.0    # fire & forget notifications


# ── Client de base ────────────────────────────────────────────────────────────

class LaForgeMCPBridge:
    """
    Client MCP agile — supporte stdio et SSE.
    Chaque appel ouvre une session courte et la ferme proprement.
    Compatible OneMCP et serveurs locaux.
    """

    def __init__(
        self,
        transport:    str  = "stdio",
        command:      str  = "python",
        args:         list = None,
        url:          str  = "http://127.0.0.1:9999/sse",
        timeout:      float = TIMEOUT_STANDARD,
    ):
        self.transport = transport
        self.command   = command
        self.args      = args or [str(ROOT / "app" / "mcp_server_tools.py")]
        self.url       = url
        self.timeout   = timeout
        self._available: Optional[bool] = None
        self._last_check: float = 0.0

    # ── API principale ────────────────────────────────────────────────────────

    async def call_tool(
        self,
        tool_name:  str,
        arguments:  dict,
        timeout:    float = None,
        vital:      bool  = False,
    ) -> dict:
        """
        Appelle un tool MCP avec timeout propre.

        Args:
            vital: si True → timeout TIMEOUT_VITAL et exception propagée
                   si False → timeout réduit, retourne {"error": ...} sans exception

        Returns:
            {"ok": bool, "result": Any, "elapsed_ms": float}
        """
        t0  = time.monotonic()
        tmt = timeout or (TIMEOUT_VITAL if vital else self.timeout)

        try:
            result = await asyncio.wait_for(
                self._call_impl(tool_name, arguments),
                timeout=tmt
            )
            return {
                "ok":         True,
                "result":     result,
                "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
                "tool":       tool_name,
            }
        except asyncio.TimeoutError:
            logger.warning("MCP timeout %s (%.1fs)", tool_name, tmt)
            return {
                "ok":    False,
                "error": f"timeout après {tmt}s",
                "tool":  tool_name,
                "elapsed_ms": tmt * 1000,
            }
        except Exception as e:
            if vital:
                raise
            logger.error("MCP error %s: %s", tool_name, e)
            return {"ok": False, "error": str(e)[:120], "tool": tool_name}

    async def fire_and_forget(
        self,
        tool_name:  str,
        arguments:  dict,
    ) -> None:
        """
        Envoie une notification sans attendre la réponse.
        Ring 5 — cascade non-bloquante.
        """
        asyncio.create_task(
            self.call_tool(tool_name, arguments,
                           timeout=TIMEOUT_NOTIFY, vital=False)
        )

    async def list_tools(self) -> list:
        """Retourne la liste des tools disponibles sur ce serveur."""
        try:
            return await asyncio.wait_for(
                self._list_impl(), timeout=TIMEOUT_STANDARD
            )
        except Exception:
            return []

    async def health_check(self) -> bool:
        """Vérifie la disponibilité du serveur MCP (cache 30s)."""
        now = time.monotonic()
        if now - self._last_check < 30.0 and self._available is not None:
            return self._available
        try:
            tools = await asyncio.wait_for(self._list_impl(), timeout=3.0)
            self._available = len(tools) > 0
        except Exception:
            self._available = False
        self._last_check = now
        return self._available

    # ── Implémentations par transport ─────────────────────────────────────────

    async def _call_impl(self, tool_name: str, arguments: dict) -> Any:
        if self.transport == "stdio":
            return await self._call_stdio(tool_name, arguments)
        elif self.transport == "sse":
            return await self._call_sse(tool_name, arguments)
        raise ValueError(f"Transport inconnu: {self.transport}")

    async def _list_impl(self) -> list:
        if self.transport == "stdio":
            return await self._list_stdio()
        elif self.transport == "sse":
            return await self._list_sse()
        return []

    async def _call_stdio(self, tool_name: str, arguments: dict) -> Any:
        if not HAS_MCP_STDIO:
            raise ImportError("mcp.client.stdio non disponible")
        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=None,
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                # Extraire le contenu texte
                if hasattr(result, "content") and result.content:
                    first = result.content[0]
                    if hasattr(first, "text"):
                        try:
                            return json.loads(first.text)
                        except json.JSONDecodeError:
                            return {"text": first.text}
                return result

    async def _list_stdio(self) -> list:
        if not HAS_MCP_STDIO:
            return []
        server_params = StdioServerParameters(
            command=self.command, args=self.args, env=None
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [t.name for t in (result.tools or [])]

    async def _call_sse(self, tool_name: str, arguments: dict) -> Any:
        if not HAS_MCP_SSE:
            raise ImportError("mcp.client.sse non disponible")
        async with sse_client(self.url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                if hasattr(result, "content") and result.content:
                    first = result.content[0]
                    if hasattr(first, "text"):
                        try:
                            return json.loads(first.text)
                        except Exception:
                            return {"text": first.text}
                return result

    async def _list_sse(self) -> list:
        if not HAS_MCP_SSE:
            return []
        try:
            async with sse_client(self.url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return [t.name for t in (result.tools or [])]
        except Exception:
            return []


# ── Pool de bridges (singletons par config) ───────────────────────────────────

_bridges: dict[str, LaForgeMCPBridge] = {}


def get_bridge(
    name:      str  = "local",
    transport: str  = "stdio",
    **kwargs,
) -> LaForgeMCPBridge:
    """Retourne un bridge singleton par nom."""
    if name not in _bridges:
        _bridges[name] = LaForgeMCPBridge(transport=transport, **kwargs)
    return _bridges[name]


def local_bridge() -> LaForgeMCPBridge:
    """Bridge vers le serveur MCP local (stdio)."""
    return get_bridge(
        "local", "stdio",
        command="python",
        args=[str(ROOT / "app" / "mcp_server_tools.py")],
    )


def hub_bridge() -> LaForgeMCPBridge:
    """Bridge vers le Hub SSE (OneMCP compatible)."""
    import os
    port = os.environ.get("MCP_PORT", "9999")
    return get_bridge(
        "hub", "sse",
        url=f"http://127.0.0.1:{port}/sse",
    )


# ── Worker Qt non-bloquant ────────────────────────────────────────────────────

try:
    from PySide6.QtCore import QThread, Signal

    class MCPWorker(QThread):
        """Exécute un appel MCP dans un QThread — ne bloque jamais le GUI."""
        result_ready = Signal(dict)

        def __init__(self, bridge: LaForgeMCPBridge,
                     tool: str, args: dict, parent=None):
            super().__init__(parent)
            self._bridge = bridge
            self._tool   = tool
            self._args   = args

        def run(self):
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(
                self._bridge.call_tool(self._tool, self._args)
            )
            loop.close()
            self.result_ready.emit(result)

except ImportError:
    pass   # pas de Qt — usage CLI/TUI uniquement
