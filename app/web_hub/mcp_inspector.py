"""
app/web_hub/mcp_inspector.py - MCP Inspector intégré au web_hub.

Outil de debug MCP équivalent fonctionnel de @modelcontextprotocol/inspector
adapté à l'archi Nokido à 2 transports (stdio + streamable_http).

Design figé : sandbox/mcp_inspector_design.md
Mount : app.include_router(router, prefix="/inspector", tags=["inspector"])

Sécurité :
- Auth via AuthMiddleware existant (pas de bypass)
- Allowlist 14 outils Nokido composites
- Args validés (max 64KB, profondeur 10)
- Bind via hub (127.0.0.1)
- Pas de log persistant des invocations
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

logger = logging.getLogger("nokido.inspector")
router = APIRouter()

# --- CONSTANTES -------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent.parent
_BRIDGE_SCRIPT = _ROOT / "tools" / "mcp_stdio_bridge.py"
_HUB_URL = os.environ.get("LAFORGE_HUB_URL", "http://127.0.0.1:8766/mcp")
_HEALTH_URL = _HUB_URL.replace("/mcp", "/health")
_PYTHON = sys.executable

# Allowlist : 14 outils Nokido composites + 2 méta (tools/list, ping)
_TOOL_ALLOWLIST = frozenset(
    {
        "run",
        "read",
        "write",
        "query",
        "ask",
        "route_task",
        "research_agent",
        "web_search",
        "hub",
        "task",
        "event",
        "rag",
        "auto_test",
        "trigger_autonomous_evolution",
    }
)

_MAX_ARGS_BYTES = 64 * 1024
_MAX_ARGS_DEPTH = 10
_INVOKE_TIMEOUT = 30.0
_BRIDGE_SPAWN_TIMEOUT = 5.0


# --- VALIDATION DES ARGS -----------------------------------------------


def _check_depth(obj: Any, max_depth: int, current: int = 0) -> bool:
    """Profondeur d'objet JSON <= max_depth (anti DoS récursif)."""
    if current > max_depth:
        return False
    if isinstance(obj, dict):
        return all(_check_depth(v, max_depth, current + 1) for v in obj.values())
    if isinstance(obj, list):
        return all(_check_depth(v, max_depth, current + 1) for v in obj)
    return True


def _validate_args(tool: str, args: Any) -> None:
    """Lève HTTPException si invalide."""
    if tool not in _TOOL_ALLOWLIST:
        raise HTTPException(400, f"tool {tool!r} not in allowlist")
    if not isinstance(args, dict):
        raise HTTPException(400, "args must be a JSON object")
    try:
        encoded = json.dumps(args).encode("utf-8")
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"args not JSON-serializable: {e}")
    if len(encoded) > _MAX_ARGS_BYTES:
        raise HTTPException(400, f"args too large: {len(encoded)}b > {_MAX_ARGS_BYTES}b")
    if not _check_depth(args, _MAX_ARGS_DEPTH):
        raise HTTPException(400, f"args nesting > {_MAX_ARGS_DEPTH}")


# --- CLIENT TRANSPORT : STDIO -----------------------------------------


class _StdioClient:
    """Spawn le bridge stdio à la demande, exécute 1 call, cleanup.

    Pas de pool persistant : chaque invocation démarre un bridge frais.
    Surcoût ~1s par call, acceptable pour usage debug.
    """

    def __init__(self, bridge_script: Path = _BRIDGE_SCRIPT):
        self.bridge = bridge_script
        if not self.bridge.exists():
            raise RuntimeError(f"bridge introuvable: {self.bridge}")

    async def call(self, method: str, params: dict, request_id: int = 1) -> dict:
        """Lance bridge -> envoie JSON-RPC -> lit réponse -> kill."""
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        request_bytes = (json.dumps(request) + "\n").encode("utf-8")

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                _PYTHON,
                str(self.bridge),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
                cwd=str(_ROOT),
            )
            assert proc.stdin and proc.stdout
            proc.stdin.write(request_bytes)
            await proc.stdin.drain()

            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=_INVOKE_TIMEOUT)
            except asyncio.TimeoutError:
                raise HTTPException(504, "stdio transport timeout (30s)")

            if not line:
                raise HTTPException(502, "stdio bridge closed without response")

            try:
                return {
                    "request_payload": request,
                    "response_payload": json.loads(line.decode("utf-8")),
                }
            except json.JSONDecodeError as e:
                raise HTTPException(502, f"stdio bridge invalid JSON: {e}")
        finally:
            if proc and proc.returncode is None:
                try:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
                except ProcessLookupError:
                    pass
