# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE [GREEN]
DATE:2026-05-02 | VER:v_forge_docker_supervisor_v1
#FORGE:[score:88|agent:claude-opus-4.7|temp:0.00|risk:0.30|color:GREEN|attempt:1]
CONTRAINTE: Docker MCP gateway supervisor (cold-start + stdio bridge + JSON-RPC)

ORGANE (CLAUDE.md §10) :
  - SN peripherique (cousin de forge_mcp_registry).
  - Vascularisation : flux Hub :8766 -> stdio Popen('docker mcp gateway run')
    -> retour string, namespace docker_*.
  - Hemorragie : si daemon Docker down ou subprocess crash, on retourne
    'ERR: ...' propre (jamais d'exception non capturee dans le hub).

POURQUOI UN NOUVEAU MODULE (anti-duplication CLAUDE.md §3) :
  - forge_mcp_registry._handle_netcfg_proxy fait du HTTP -> netcfg-mcp :8767.
    Docker MCP n'expose PAS de HTTP, uniquement stdio JSON-RPC.
  - forge_runner.py fait du fire-forget mmap, pas du JSON-RPC bidirectionnel
    avec request id matching.
  - forge_handler_advanced.py / forge_handler_build.py utilisent run_python
    pour subprocess one-shot, pas un daemon long-lived a stdin partage.
  - Donc : module dedie minimal, pattern singleton lazy, request_id +
    asyncio.Future map pour multiplexer plusieurs in-flight calls.

USAGE :
  >>> from forge_docker_supervisor import DockerSupervisor
  >>> sup = DockerSupervisor.instance()
  >>> await sup.ensure_daemon()                 # cold-start si besoin
  >>> tools = await sup.list_tools()            # ['docker', 'compose', ...]
  >>> out = await sup.call_tool('docker', {'cmd': 'ps'}, timeout=15)
"""

from __future__ import annotations

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:88|agent:claude-opus-4.7|temp:0.00|risk:0.30|color:GREEN|attempt:1]"

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Nokido.DockerSupervisor")

# Source de verite pour le binaire Python (CLAUDE.md §11)
try:
    from nokido_agent.app.forge_python_bin import LAFORGE_PYTHON  # noqa: F401  (futur usage)
except Exception:
    LAFORGE_PYTHON = sys.executable

DOCKER_DESKTOP_PATH = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
DAEMON_BOOT_TIMEOUT = 90.0  # s
DAEMON_POLL_INTERVAL = 2.0  # s
GATEWAY_CMD = ["docker", "mcp", "gateway", "run"]


class DockerSupervisorError(RuntimeError):
    """Erreur niveau supervisor (daemon down, gateway crash, RPC timeout)."""


class DockerSupervisor:
    """
    Singleton lazy : garde un Popen('docker mcp gateway run') en vie,
    multiplexe les JSON-RPC requests via id counter + asyncio.Future map.

    Concurrency model :
      - Une seule instance hub-wide (DockerSupervisor.instance()).
      - Un reader thread daemon lit stdout en continu et route les
        responses vers les Future via _pending[id].
      - call_tool est async : pose un Future, ecrit la requete sur stdin,
        attend le Future avec timeout.
    """

    _instance: Optional["DockerSupervisor"] = None
    _instance_lock = threading.Lock()

    # ----- singleton -------------------------------------------------------

    @classmethod
    def instance(cls) -> "DockerSupervisor":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._lock = asyncio.Lock()
        self._req_id: int = 0
        self._pending: Dict[int, "asyncio.Future[dict]"] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        self._daemon_up: bool = False

    # ----- daemon health ---------------------------------------------------

    @staticmethod
    def _docker_info_ok() -> bool:
        try:
            r = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            return r.returncode == 0
        except Exception:
            return False

    async def ensure_daemon(self) -> None:
        """
        Garantit que `docker info` repond. Sinon lance Docker Desktop et
        attend jusqu a DAEMON_BOOT_TIMEOUT.
        Raise DockerSupervisorError si timeout.
        """
        if self._daemon_up and self._docker_info_ok():
            return

        if self._docker_info_ok():
            self._daemon_up = True
            return

        # Cold start : launch Docker Desktop GUI (boots WSL backend)
        if os.path.exists(DOCKER_DESKTOP_PATH):
            try:
                # CREATE_NO_WINDOW pour rester silencieux
                creationflags = 0
                if sys.platform == "win32":
                    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                subprocess.Popen(
                    [DOCKER_DESKTOP_PATH],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                logger.info("Docker Desktop launch initiated")
            except Exception as e:
                raise DockerSupervisorError(f"Cannot launch Docker Desktop: {e}")
        else:
            raise DockerSupervisorError(f"Docker Desktop introuvable a {DOCKER_DESKTOP_PATH} et daemon down")

        # Poll
        deadline = time.monotonic() + DAEMON_BOOT_TIMEOUT
        while time.monotonic() < deadline:
            if self._docker_info_ok():
                self._daemon_up = True
                logger.info("Docker daemon ready")
                return
            await asyncio.sleep(DAEMON_POLL_INTERVAL)
        raise DockerSupervisorError(f"Docker daemon pas pret apres {DAEMON_BOOT_TIMEOUT}s")

    # ----- gateway lifecycle ----------------------------------------------

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    async def spawn_gateway_stdio(self) -> None:
        """
        Lance `docker mcp gateway run` en subprocess long-lived.
        Idempotent : si deja en vie, ne fait rien.
        """
        if self._alive():
            return

        await self.ensure_daemon()

        # Capture la loop courante pour le reader thread (call_soon_threadsafe)
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = asyncio.get_event_loop()

        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self._proc = subprocess.Popen(
                GATEWAY_CMD,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,  # unbuffered binary
                creationflags=creationflags,
            )
        except FileNotFoundError as e:
            raise DockerSupervisorError(f"`docker mcp gateway run` introuvable (CLI Docker MCP plugin manquant): {e}")

        # Reset id counter et pending map a chaque spawn
        self._req_id = 0
        self._pending.clear()
        self._tools_cache = None

        # Demarre le reader thread (daemon=True : meurt avec le hub)
        self._reader_thread = threading.Thread(target=self._reader_loop, name="DockerSupervisorReader", daemon=True)
        self._reader_thread.start()
        logger.info("docker mcp gateway spawned pid=%s", self._proc.pid)

        # Initialize handshake (MCP requirement)
        try:
            await self._jsonrpc(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "laforge-hub", "version": "1.0"},
                },
                timeout=10,
            )
            # notification initialized
            self._send_raw({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception as e:
            logger.warning("Docker MCP handshake echoue: %s", e)

    def _reader_loop(self) -> None:
        """Thread bloquant : lit stdout ligne par ligne (NDJSON)."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw in iter(proc.stdout.readline, b""):
                if not raw:
                    break
                try:
                    msg = json.loads(raw.decode("utf-8", errors="replace").strip())
                except Exception:
                    continue
                rid = msg.get("id")
                if rid is None:
                    # notification, ignore
                    continue
                fut = self._pending.pop(rid, None)
                if fut is None or self._loop is None:
                    continue
                # Marshal back to the asyncio loop
                self._loop.call_soon_threadsafe(lambda f=fut, m=msg: f.set_result(m) if not f.done() else None)
        except Exception as e:
            logger.error("Docker reader loop crashed: %s", e)
        finally:
            # Reveiller tous les pending pour ne pas leaker
            if self._loop is not None:
                for fid, fut in list(self._pending.items()):
                    self._loop.call_soon_threadsafe(
                        lambda f=fut: f.set_exception(DockerSupervisorError("gateway closed")) if not f.done() else None
                    )
                self._pending.clear()

    def _send_raw(self, obj: dict) -> None:
        if not self._alive() or self._proc is None or self._proc.stdin is None:
            raise DockerSupervisorError("gateway not running")
        line = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except Exception as e:
            raise DockerSupervisorError(f"stdin write failed: {e}")

    async def _jsonrpc(self, method: str, params: dict, timeout: float = 15.0) -> dict:
        """
        JSON-RPC 2.0 request/response avec id matching.
        Lazy spawn du gateway si pas encore demarre.
        """
        if not self._alive():
            await self.spawn_gateway_stdio()

        async with self._lock:
            self._req_id += 1
            rid = self._req_id

        loop = asyncio.get_running_loop()
        fut: "asyncio.Future[dict]" = loop.create_future()
        self._pending[rid] = fut

        self._send_raw(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": method,
                "params": params,
            }
        )

        try:
            resp = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise DockerSupervisorError(f"timeout {timeout}s on {method}")

        if "error" in resp:
            err = resp["error"]
            raise DockerSupervisorError(f"{method} error: {err}")
        return resp.get("result", {})

    # ----- public API ------------------------------------------------------

    async def list_tools(self, force: bool = False) -> List[Dict[str, Any]]:
        """
        Retourne la liste des tools exposes par le gateway.
        Cache lazy : invalide si force=True.
        """
        if self._tools_cache is not None and not force:
            return self._tools_cache
        result = await self._jsonrpc("tools/list", {}, timeout=15)
        tools = result.get("tools", [])
        self._tools_cache = tools
        return tools

    async def call_tool(self, name: str, args: dict, timeout: float = 15.0) -> str:
        """
        Appelle un tool du gateway. `name` est le nom NATIF (sans prefixe
        docker_). Retourne content[0].text si dispo, sinon str(result).
        """
        result = await self._jsonrpc(
            "tools/call",
            {"name": name, "arguments": args or {}},
            timeout=timeout,
        )
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and "text" in first:
                return str(first["text"])
        return json.dumps(result, ensure_ascii=False)

    # ----- shutdown --------------------------------------------------------

    def shutdown(self) -> None:
        """Termine le gateway proprement. A appeler au shutdown du hub."""
        if not self._alive() or self._proc is None:
            self._proc = None
            return
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)
        except Exception as e:
            logger.warning("Shutdown gateway: %s", e)
        finally:
            self._proc = None
            self._tools_cache = None
            self._daemon_up = False


def get_supervisor() -> DockerSupervisor:
    """Helper pour symetrie avec get_registry / get_state_manager."""
    return DockerSupervisor.instance()


__all__ = [
    "DockerSupervisor",
    "DockerSupervisorError",
    "get_supervisor",
]
