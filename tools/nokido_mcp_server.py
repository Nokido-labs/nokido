"""
nokido_mcp_server.py — Nokido MCP Server (STDIO) v17.02
=========================================================
Unified with forge_mcp_registry (Chantier C).

v17.02 :
  - Branchement forge_network_logger sur le canal STDIO
    Chaque tool call entrant/sortant est loggue dans network_log
    et diffuse via SSE vers /forge/network
  - Mesure de latence par tool call
  - Logging du session_id pour correlation des echanges

v17.01 :
  - Suppression du _stdin_watchdog qui consommait stdin
  - Securisation du logging : creation auto du dossier logs/
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import sys
import time
from datetime import datetime as _dt
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Thread pool pour offloader le dispatch SQLite-lourd hors du loop asyncio principal.
# Empêche les sqlite3.connect() synchrones de staller les appels parallèles.
_DISPATCH_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=6, thread_name_prefix="nokido_dispatch"
)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG & PATHS
# ─────────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

_SANDBOX = ROOT / "sandbox"
_LIVE_LOG = _SANDBOX / "mcp_live.log"
_SANDBOX.mkdir(parents=True, exist_ok=True)

_LOGS_DIR = ROOT / "logs"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(
            _LOGS_DIR / "mcp_service.log", encoding="utf-8", maxBytes=10485760, backupCount=5
        )
    ],
)

# Session ID pour correlation des events (unique par process)
import uuid as _uuid

_SESSION_ID = f"stdio_{_uuid.uuid4().hex[:8]}"

# ─────────────────────────────────────────────────────────────────────────────
# NETWORK LOGGER (v17.02)
# ─────────────────────────────────────────────────────────────────────────────


def _get_net_logger():
    """Import lazy du network logger (evite crash si module absent)."""
    try:
        from nokido_agent.app.forge_network_logger import log_internal, log_stdio_in, log_stdio_out

        return log_stdio_in, log_stdio_out, log_internal
    except Exception:
        return None, None, None


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def _live_log(tool, msg, status="OK"):
    try:
        # Heure SEULE = un journal qu'on ne peut pas placer sur un jour. Convention
        # unique Nokido : UTC ISO-8601 ms suffixe Z (forge_timecode).
        try:
            from nokido_agent.app.forge_timecode import now_iso

            ts = now_iso()
        except Exception:  # noqa: BLE001
            from datetime import timezone as _tz

            ts = _dt.now(_tz.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        line = f"[{ts}] [{status:4}] [{tool:18}] {msg[:200]}\n"
        with open(_LIVE_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# SERVER CORE
# ─────────────────────────────────────────────────────────────────────────────

server = Server("Nokido")


@server.list_tools()
async def handle_list_tools():
    from nokido_agent.app.forge_mcp_registry import get_registry

    raw_tools = get_registry().get_tool_list()
    return [Tool(**t) for t in raw_tools]


@server.call_tool()
async def handle_call_tool(name, arguments):
    args = arguments or {}
    _agent = os.environ.get("LAFORGE_AGENT", "CLAUDE")
    ring = int(os.environ.get("LAFORGE_RING", "0"))
    t0 = time.monotonic()

    # v17.02 : log entrant
    _live_log(name, f"appel STDIO [{_agent}]", "CALL")
    log_in, log_out, log_int = _get_net_logger()
    if log_in:
        log_in(name, _agent, ring, args)

    try:
        from nokido_agent.app.forge_mcp_registry import get_registry

        registry = get_registry()

        # Offload dans un thread dédié : sqlite3.connect() synchrone dans les handlers
        # async bloquerait l'event loop sous appels parallèles (15 connect() identifiés).
        # Chaque thread crée son propre event loop → pas de contention sur le loop principal.
        loop = asyncio.get_event_loop()

        def _sync_dispatch():
            import asyncio as _a

            return _a.run(registry.dispatch(name, args, agent=_agent, ring=ring))

        res = await loop.run_in_executor(_DISPATCH_POOL, _sync_dispatch)

        latency = round((time.monotonic() - t0) * 1000, 1)
        _is_err = str(res).startswith(("ERR", "SECURITY", "SECRET GUARD"))

        # v17.02 : log sortant
        if log_out:
            log_out(name, _agent, ring, str(res), latency)

        return [TextContent(type="text", text=str(res), isError=_is_err)]

    except Exception as e:
        latency = round((time.monotonic() - t0) * 1000, 1)
        err_msg = f"TOOL ERROR [{name}]: {type(e).__name__}: {e}"
        if log_out:
            log_out(name, _agent, ring, err_msg, latency)
        return [TextContent(type="text", text=err_msg, isError=True)]


async def main():
    _live_log("SYSTEM", f"MCP STDIO demarre (session={_SESSION_ID})", "INIT")

    # Log demarrage dans network_log
    log_in, _, log_int = _get_net_logger()
    if log_int:
        log_int(
            "STDIO_START",
            "SYSTEM",
            {
                "session_id": _SESSION_ID,
                "agent": os.environ.get("LAFORGE_AGENT", "CLAUDE"),
                "ring": os.environ.get("LAFORGE_RING", "0"),
            },
        )

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
