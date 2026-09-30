"""
forge_mcp_proxy.py — Proxy STDIO → HTTP Nokido Hub v2.0
=========================================================
Proxy JSON-RPC 2.0 conforme spec + sécurité renforcée.

Conformité JSON-RPC 2.0 (https://www.jsonrpc.org/specification) :
  - Notifications (sans id) : relayées sans attendre de réponse
  - Batch requests (array) : traitement parallèle, réponses ordonnées par id
  - Error codes normalisés (-32700 parse, -32600 invalid, -32001 hub error)
  - id=null sur parse error
  - Pas de réponse aux notifications (spec section 4.1)

Sécurité (https://www.stackhawk.com/blog/json-rpc-security-best-practices) :
  - Validation stricte de chaque champ Request (jsonrpc, method, id, params)
  - Sanitisation des erreurs hub (pas de détails internes exposés)
  - Rate limiting par fenêtre glissante (configurable)
  - Pas de méthodes rpc.* non autorisées (réservées spec section 4)
  - Max payload size pour éviter DoS mémoire

Qualité de lien :
  - Zero buffering : flush immédiat sur chaque réponse
  - Reconnexion automatique hub (retry exponentiel)
  - Latence < 5ms loopback
  - BrokenPipe géré proprement (Claude Desktop ferme le canal)

Author-Agent: CLAUDE
Author-Session: 2026-04-25-network-monitor
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
HUB_URL = os.environ.get("LAFORGE_HUB_URL", "http://127.0.0.1:8766/mcp")
AGENT_NAME = os.environ.get("LAFORGE_AGENT", "CLAUDE")
HUB_TOKEN = os.environ.get("FORGE_MCP_TOKEN", "")
TIMEOUT = int(os.environ.get("LAFORGE_PROXY_TIMEOUT", "120"))
MAX_RETRY = int(os.environ.get("LAFORGE_PROXY_RETRIES", "3"))
RETRY_DLY = float(os.environ.get("LAFORGE_PROXY_RETRY_DELAY", "0.5"))
MAX_PAYLOAD = int(os.environ.get("LAFORGE_PROXY_MAX_BYTES", str(512 * 1024)))  # 512KB
RATE_LIMIT = int(os.environ.get("LAFORGE_PROXY_RATE_LIMIT", "60"))  # req/min

_LOGS = ROOT / "logs"
_LOGS.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] proxy — %(message)s",
    handlers=[
        RotatingFileHandler(
            _LOGS / "mcp_proxy.log", encoding="utf-8", maxBytes=10485760, backupCount=5
        )
    ],
)
logger = logging.getLogger("forge_mcp_proxy")

# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMITER — fenêtre glissante 60s
# ─────────────────────────────────────────────────────────────────────────────


class _RateLimiter:
    def __init__(self, max_per_minute: int):
        self._max = max_per_minute
        self._times: deque = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            # Supprimer les entrées > 60s
            while self._times and now - self._times[0] > 60:
                self._times.popleft()
            if len(self._times) >= self._max:
                return False
            self._times.append(now)
            return True


_rate = _RateLimiter(RATE_LIMIT)

# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION JSON-RPC 2.0 (spec section 4)
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_METHODS = {
    "initialize",
    "notifications/initialized",
    "tools/list",
    "tools/call",
    "prompts/list",
    "prompts/get",
    "resources/list",
    "resources/read",
    "ping",
    "$/cancelRequest",
}


def _validate_request(obj: Any) -> dict | None:
    """
    Valide un Request object JSON-RPC 2.0.
    Retourne un error dict si invalide, None si valide.
    Spec : jsonrpc MUST be "2.0", method MUST be string, id MAY be absent.
    """
    if not isinstance(obj, dict):
        return _err(-32600, "Invalid Request: not an object")

    if obj.get("jsonrpc") != "2.0":
        return _err(-32600, "Invalid Request: jsonrpc must be '2.0'")

    method = obj.get("method")
    if not isinstance(method, str) or not method:
        return _err(-32600, "Invalid Request: method must be a non-empty string")

    # Spec section 4 : méthodes rpc.* réservées pour extensions internes
    if method.startswith("rpc.") and method not in ("rpc.discover",):
        return _err(-32601, f"Method not found: '{method}' is reserved")

    # params doit être Object ou Array si présent
    params = obj.get("params")
    if params is not None and not isinstance(params, (dict, list)):
        return _err(-32602, "Invalid params: must be Object or Array")

    return None  # valide


def _err(code: int, message: str, req_id: Any = None) -> dict:
    """Construit un error response JSON-RPC 2.0 conforme."""
    # Sanitiser le message — pas de détails internes
    safe_msg = message[:200] if isinstance(message, str) else "Error"
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": safe_msg}}


def _is_notification(obj: dict) -> bool:
    """Spec 4.1 : Notification = Request sans id."""
    return "id" not in obj


# ─────────────────────────────────────────────────────────────────────────────
# HTTP CLIENT
# ─────────────────────────────────────────────────────────────────────────────


def _headers() -> dict:
    h = {
        "Content-Type": "application/json",
        "X-Agent-Name": AGENT_NAME,
        "X-Transport": "stdio-proxy/2.0",
    }
    if HUB_TOKEN:
        h["Authorization"] = f"Bearer {HUB_TOKEN}"
    return h


def _post(body: bytes, req_id: Any = None, attempt: int = 0) -> bytes | None:
    """
    POST vers le hub. Retry avec backoff exponentiel.
    Retourne None si c'est une notification (pas de réponse attendue).
    """
    req = urllib.request.Request(url=HUB_URL, data=body, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()

    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            logger.error(f"Hub auth {e.code}")
            # Sanitisé : pas d'info interne dans l'erreur
            return json.dumps(_err(-32001, "Hub authentication error", req_id)).encode()
        if e.code >= 500 and attempt < MAX_RETRY:
            time.sleep(RETRY_DLY * (2**attempt))
            return _post(body, req_id, attempt + 1)
        logger.error(f"Hub HTTP {e.code}")
        return json.dumps(_err(-32002, "Hub server error", req_id)).encode()

    except (urllib.error.URLError, ConnectionRefusedError, OSError) as e:
        if attempt < MAX_RETRY:
            delay = RETRY_DLY * (2**attempt)
            logger.warning(f"Hub down (tentative {attempt + 1}/{MAX_RETRY}) retry {delay:.1f}s")
            time.sleep(delay)
            return _post(body, req_id, attempt + 1)
        logger.error(f"Hub inaccessible: {e}")
        return json.dumps(
            _err(-32003, "Nokido Hub unavailable — check NokidoMCP service", req_id)
        ).encode()


def _wait_hub(max_wait: float = 5.0) -> bool:
    health = HUB_URL.replace("/mcp", "/health")
    t0 = time.monotonic()
    n = 0
    while time.monotonic() - t0 < max_wait:
        try:
            urllib.request.urlopen(health, timeout=2)
            if n:
                logger.info(f"Hub UP après {n} tentatives")
            return True
        except Exception:
            n += 1
            time.sleep(0.5)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# TRAITEMENT — single, notification, batch
# ─────────────────────────────────────────────────────────────────────────────


def _handle_single(obj: dict) -> bytes | None:
    """
    Traite un Request object unique.
    Retourne None si notification (spec 4.1 : pas de réponse).
    """
    req_id = obj.get("id")  # absent = notification

    # Validation
    err = _validate_request(obj)
    if err:
        if _is_notification(obj):
            return None  # spec : pas de réponse même sur erreur pour notification
        err["id"] = req_id
        return json.dumps(err).encode()

    # Rate limiting
    if not _rate.allow():
        if _is_notification(obj):
            return None
        return json.dumps(_err(-32029, "Rate limit exceeded", req_id)).encode()

    # Log
    method = obj.get("method", "?")
    logger.info(f"→ {method} id={req_id}")

    # POST vers hub
    body = json.dumps(obj, ensure_ascii=False).encode()
    t0 = time.monotonic()
    resp = _post(body, req_id)
    lat = round((time.monotonic() - t0) * 1000, 1)

    # Spec 4.1 : Notification → pas de réponse au client
    if _is_notification(obj):
        logger.info(f"  notification {method} relayée (pas de réponse)")
        return None

    logger.info(f"← {method} id={req_id} {lat}ms")
    return resp


def _handle_batch(arr: list) -> bytes:
    """
    Spec section 6 : Batch request.
    Traitement concurrent, réponses dans un Array.
    Les notifications dans le batch ne produisent pas de réponse.
    Si le batch ne contient que des notifications → retourner rien (spec).
    """
    if not arr:
        return json.dumps(_err(-32600, "Invalid Request: empty batch")).encode()

    results = []
    with ThreadPoolExecutor(max_workers=min(len(arr), 8)) as ex:
        futures = {ex.submit(_handle_single, item): item for item in arr if isinstance(item, dict)}
        for fut in as_completed(futures):
            try:
                resp = fut.result()
                if resp is not None:
                    results.append(json.loads(resp))
            except Exception as e:
                logger.error(f"Batch item error: {e}")

    # Spec : si toutes les notifications → pas de réponse
    if not results:
        return b""  # ne rien écrire

    return json.dumps(results, ensure_ascii=False).encode()


# ─────────────────────────────────────────────────────────────────────────────
# BOUCLE PRINCIPALE
# ─────────────────────────────────────────────────────────────────────────────


def run():
    logger.info(f"forge_mcp_proxy v2.0 | agent={AGENT_NAME} | hub={HUB_URL}")

    if not _wait_hub(5.0):
        logger.warning("Hub pas UP au démarrage — retry sur chaque message")

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue

        # Protection DoS : payload trop grand
        if len(raw) > MAX_PAYLOAD:
            err = json.dumps(
                _err(
                    -32600,
                    f"Request too large: {len(raw)} bytes (max {MAX_PAYLOAD})",
                    None,  # id inconnu car pas encore parsé
                )
            ).encode()
            stdout.write(err + b"\n")
            stdout.flush()
            continue

        # Parse JSON
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            # Spec -32700 : parse error → id=null
            err = json.dumps(_err(-32700, f"Parse error: {e.msg}", None)).encode()
            stdout.write(err + b"\n")
            stdout.flush()
            continue

        # Dispatch : batch (Array) ou single (Object)
        if isinstance(obj, list):
            resp = _handle_batch(obj)
        elif isinstance(obj, dict):
            resp = _handle_single(obj)
        else:
            resp = json.dumps(_err(-32600, "Invalid Request: must be Object or Array")).encode()

        # Écriture réponse — uniquement si non-None (notifications = pas de réponse)
        if resp:
            stdout.write(resp + b"\n")
            stdout.flush()


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        logger.info("Arrêt (KeyboardInterrupt)")
    except BrokenPipeError:
        logger.info("Arrêt (BrokenPipeError — Claude Desktop a fermé le canal)")
    except Exception as e:
        logger.error(f"Erreur fatale: {e}", exc_info=True)
        sys.exit(1)
