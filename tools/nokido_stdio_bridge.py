"""
nokido_stdio_bridge.py — Bridge STDIO async v17.02
====================================================
Tunnel pur STDIO <-> Hub HTTP. Muet, non-bloquant, auto-reconnect.

Responsabilité unique :
  stdin (Claude Desktop) → HTTP POST /mcp (Hub) → stdout (Claude Desktop)

v17.02 :
  - Reconnexion automatique si Hub redémarre (hub_restart)
  - Retry avec backoff sur erreur réseau transitoire
  - Timeout propre 30s sans freeze
  - aiohttp si disponible, fallback urllib sinon
  - WindowsSelectorEventLoopPolicy pour Windows

Config claude_desktop_config.json :
  Voir tools/claude_desktop_config_bridge.json
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(str(__import__("pathlib").Path(__file__).resolve().parents[1]))
HUB_URL = os.environ.get("LAFORGE_HUB_URL", "http://127.0.0.1:8766/mcp")
HUB_TOKEN = ""
TIMEOUT = 30.0
RETRY_MAX = 3
RETRY_DELAY = 1.0  # secondes entre retries

_env_file = ROOT / "Nokido.env"
if _env_file.exists():
    for _l in _env_file.read_text(encoding="utf-8").splitlines():
        _l = _l.strip()
        if _l.startswith("FORGE_MCP_TOKEN=") and not _l.startswith("#"):
            HUB_TOKEN = _l.split("=", 1)[1].split("#")[0].strip()
            break


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if HUB_TOKEN:
        h["Authorization"] = "Bearer " + HUB_TOKEN
    return h


def _error_response(bid, code: int, msg: str) -> dict:
    return {"jsonrpc": "2.0", "id": bid, "error": {"code": code, "message": msg}}


async def _post_aiohttp(session, body: dict) -> dict:
    import aiohttp

    try:
        async with session.post(
            HUB_URL, json=body, headers=_headers(), timeout=aiohttp.ClientTimeout(total=TIMEOUT)
        ) as resp:
            return await resp.json()
    except TimeoutError:
        return _error_response(body.get("id"), -32000, "Hub timeout (" + str(TIMEOUT) + "s)")
    except aiohttp.ClientConnectorError:
        return _error_response(body.get("id"), -32000, "Hub non accessible")
    except Exception as e:
        return _error_response(body.get("id"), -32603, "Bridge erreur: " + str(e))


async def _post_urllib(loop, body: dict) -> dict:
    """Fallback synchrone — exécuté dans un thread executor."""
    import urllib.request

    def _sync():
        data = json.dumps(body).encode()
        req = urllib.request.Request(HUB_URL, data=data, method="POST")
        for k, v in _headers().items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            return _error_response(body.get("id"), -32603, "Bridge erreur: " + str(e))

    return await loop.run_in_executor(None, _sync)


async def _ping_hub() -> dict | None:
    """Vérifie que le Hub répond — retourne le health dict ou None."""
    import urllib.request

    url = HUB_URL.replace("/mcp", "/health")
    req = urllib.request.Request(url, method="GET")
    if HUB_TOKEN:
        req.add_header("Authorization", "Bearer " + HUB_TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


async def _wait_hub_ready(max_wait: float = 30.0) -> bool:
    """
    Attend que le Hub soit disponible après un restart.
    Retourne True dès que le Hub répond, False si timeout.
    """
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        h = await _ping_hub()
        if h and h.get("status") == "ok":
            return True
        await asyncio.sleep(2.0)
    return False


# ── Bridge principal ──────────────────────────────────────────────────────────


async def run_bridge():
    """Boucle STDIO → Hub → STDIO. Auto-reconnect sur restart Hub."""

    # Vérifier aiohttp
    try:
        import aiohttp

        _use_aiohttp = True
    except ImportError:
        _use_aiohttp = False
        sys.stderr.write(
            "[Bridge] aiohttp absent — fallback urllib. "
            "pip install aiohttp pour de meilleures perfs." + chr(10)
        )

    # Ping initial
    h = await _ping_hub()
    if h:
        sys.stderr.write(
            "[Bridge] Hub " + h.get("version", "?") + " connecté sur " + HUB_URL + chr(10)
        )
    else:
        sys.stderr.write(
            "[Bridge] Hub non accessible au démarrage."
            + chr(10)
            + "[Bridge] Attente Hub (max 30s)..."
            + chr(10)
        )
        ok = await _wait_hub_ready(max_wait=30.0)
        if ok:
            sys.stderr.write("[Bridge] Hub connecté." + chr(10))
        else:
            sys.stderr.write("[Bridge] Hub toujours absent — je continue quand même." + chr(10))

    # Lire stdin async — compatible Windows
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    proto = asyncio.StreamReaderProtocol(reader)
    try:
        await loop.connect_read_pipe(lambda: proto, sys.stdin)
    except NotImplementedError:
        # Windows fallback — lecture synchrone dans un thread
        import threading

        def _feed_stdin():
            try:
                while True:
                    line = sys.stdin.buffer.readline()
                    if not line:
                        break
                    loop.call_soon_threadsafe(reader.feed_data, line)
            except Exception:
                loop.call_soon_threadsafe(reader.feed_eof)

        threading.Thread(target=_feed_stdin, daemon=True).start()

    # Écrire stdout
    import threading

    _write_lock = threading.Lock()

    def _write(obj: dict):
        line = json.dumps(obj, ensure_ascii=False) + chr(10)
        with _write_lock:
            sys.stdout.buffer.write(line.encode())
            sys.stdout.buffer.flush()

    # Session aiohttp réutilisable avec keepalive
    session = None
    if _use_aiohttp:
        import aiohttp

        connector = aiohttp.TCPConnector(
            limit=10,
            keepalive_timeout=60,
            enable_cleanup_closed=True,
        )
        session = aiohttp.ClientSession(connector=connector)

    hub_down_since: float | None = None

    try:
        while True:
            # Lire une ligne depuis stdin
            try:
                raw = await asyncio.wait_for(reader.readline(), timeout=60.0)
            except TimeoutError:
                # Keep-alive : pas de message depuis 60s, on continue
                continue
            except Exception:
                break

            if not raw:
                break

            raw_str = raw.decode("utf-8", errors="replace").strip()
            if not raw_str:
                continue

            try:
                msg = json.loads(raw_str)
            except json.JSONDecodeError:
                continue

            bid = msg.get("id")

            # Forward vers Hub avec retry auto-reconnect
            response = None
            for attempt in range(RETRY_MAX):
                if session and _use_aiohttp:
                    response = await _post_aiohttp(session, msg)
                else:
                    response = await _post_urllib(loop, msg)

                # Détecter erreur réseau → Hub en restart ?
                err = response.get("error", {})
                if err and err.get("code") in (-32000, -32603):
                    if attempt < RETRY_MAX - 1:
                        sys.stderr.write(
                            "[Bridge] Hub indisponible (tentative "
                            + str(attempt + 1)
                            + "/"
                            + str(RETRY_MAX)
                            + ") — reconnexion dans "
                            + str(RETRY_DELAY)
                            + "s..."
                            + chr(10)
                        )
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))

                        # Si Hub en restart, attendre qu'il soit de nouveau UP
                        if hub_down_since is None:
                            hub_down_since = time.monotonic()
                        if time.monotonic() - hub_down_since < 30.0:
                            ok = await _wait_hub_ready(max_wait=8.0)
                            if ok:
                                sys.stderr.write("[Bridge] Hub de nouveau UP — retry." + chr(10))
                                hub_down_since = None
                        continue
                    # Dernier attempt échoué
                else:
                    hub_down_since = None  # Hub répond normalement
                break

            # Assurer jsonrpc + id
            if "jsonrpc" not in response:
                response["jsonrpc"] = "2.0"
            if "id" not in response and bid is not None:
                response["id"] = bid

            _write(response)
            # sys.stdout.buffer.flush() déjà fait dans _write()

    finally:
        if session:
            await session.close()
        sys.stderr.write("[Bridge] Arrêt propre." + chr(10))


def main():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_bridge())


if __name__ == "__main__":
    main()
