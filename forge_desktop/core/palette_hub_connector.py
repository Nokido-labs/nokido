"""
forge_desktop/core/palette_hub_connector.py
=============================================
COMMAND_HUB_BRIDGE_V17 — PaletteHubConnector
Protocol  : HTTP_JSON_RPC
Primary   : http://localhost:8766/mcp  (Hub v16.5)
Fallback  : http://localhost:8080/execute (Gateway)
Timeout   : 2000ms
Retry     : Exponential_Backoff (3 attempts)
Auth      : X-Forge-Authority header — win32cred
Audit     : Log to RAG/embeddings.db event_log
MMap      : Update sequence_id via live_bridge
"""
from __future__ import annotations
import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT_PATH = Path(__file__).resolve().parent.parent.parent
APP_PATH  = ROOT_PATH / "app"
EVENT_DB  = ROOT_PATH / "RAG" / "embeddings.db"

from PySide6.QtCore import QObject, Signal, QThread, QTimer

# ── Token source ──────────────────────────────────────────────────────────────

def _get_token() -> str:
    """Lit FORGE_MCP_TOKEN depuis win32cred (win32cred_forge_secrets)."""
    # 1. win32cred direct
    try:
        import win32cred
        cred = win32cred.CredRead("FORGE_MCP_TOKEN@Nokido",
                                  win32cred.CRED_TYPE_GENERIC)
        blob = cred.get("CredentialBlob", b"")
        val  = blob.decode("utf-16-le", "replace").rstrip("\x00") if blob else ""
        if val:
            return val
    except Exception:
        pass
    # 2. forge_secrets fallback
    try:
        if str(APP_PATH) not in sys.path:
            sys.path.insert(0, str(APP_PATH))
        from forge_secrets import get_secret
        return get_secret("FORGE_MCP_TOKEN") or ""
    except Exception:
        return ""


# ── Exponential backoff HTTP ──────────────────────────────────────────────────

def _http_post(url: str, payload: bytes, headers: dict,
               timeout: float = 2.0, attempts: int = 3) -> dict:
    """
    POST avec Exponential_Backoff.
    Delays : 0.1s → 0.2s → 0.4s
    """
    import urllib.request, urllib.error
    last_err = ""
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                url, data=payload,
                headers=headers, method="POST"
            )
            r = urllib.request.urlopen(req, timeout=timeout)
            return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.reason}"
            if e.code in (400, 401, 403, 404):
                break  # pas la peine de retry
        except Exception as e:
            last_err = str(e)[:80]
        if attempt < attempts - 1:
            time.sleep(0.1 * (2 ** attempt))  # 0.1 → 0.2 → 0.4
    return {"error": last_err, "attempts": attempts}


# ── Audit trail ───────────────────────────────────────────────────────────────

def _audit_log(cmd_id: str, endpoint: str, result: dict,
               elapsed_ms: int, ok: bool) -> int:
    """
    Écrit dans RAG/embeddings.db event_log.
    Retourne le sequence_id alloué.
    """
    try:
        conn = sqlite3.connect(str(EVENT_DB), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        last = conn.execute(
            "SELECT MAX(sequence_id) FROM event_log"
        ).fetchone()[0] or 0
        seq = int(last) + 1
        ts  = time.strftime("%Y-%m-%dT%H:%M:%S")
        payload = json.dumps({
            "cmd_id":     cmd_id,
            "endpoint":   endpoint,
            "elapsed_ms": elapsed_ms,
            "ok":         ok,
            "result_preview": str(result)[:200],
        }, ensure_ascii=False)
        conn.execute(
            "INSERT INTO event_log "
            "(timecode,sequence_id,session_id,agent_id,event_type,"
            " target,payload,prev_hash,new_hash,status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ts, seq, "palette_hub", "CLAUDE",
             "palette_dispatch", cmd_id, payload, "", "",
             "ok" if ok else "err")
        )
        conn.commit()
        conn.close()
        return seq
    except Exception:
        return -1


# ── MMap sequence update ──────────────────────────────────────────────────────

def _mmap_update_seq(seq_id: int, cmd_id: str, ok: bool):
    """Écrit le résultat dans le MMap partagé."""
    try:
        if str(APP_PATH) not in sys.path:
            sys.path.insert(0, str(APP_PATH))
        from live_bridge import bridge
        bridge.json_set("palette.last_seq",    seq_id)
        bridge.json_set("palette.last_cmd",    cmd_id)
        bridge.json_set("palette.last_ok",     ok)
        bridge.json_set("palette.last_ts",     time.time())
    except Exception:
        pass


# ── Worker QThread isolé ──────────────────────────────────────────────────────

class _ConnectorWorker(QThread):
    """
    Exécute la requête HTTP dans un thread isolé.
    Émet result_ready avec le résultat complet.
    """
    result_ready = Signal(str, dict, int, bool)  # cmd_id, result, seq, ok

    def __init__(self, cmd_id: str, tool: str, args: dict,
                 token: str, parent=None):
        super().__init__(parent)
        self._cmd_id = cmd_id
        self._tool   = tool
        self._args   = args
        self._token  = token

    def run(self):
        t0 = time.time()
        result, endpoint = self._dispatch()
        elapsed = int((time.time() - t0) * 1000)
        ok = "error" not in result

        # Audit trail
        seq = _audit_log(self._cmd_id, endpoint, result, elapsed, ok)

        # MMap update
        _mmap_update_seq(seq, self._cmd_id, ok)

        self.result_ready.emit(self._cmd_id, result, seq, ok)

    def _dispatch(self) -> tuple[dict, str]:
        """
        Tente Hub :8766 → fallback Gateway :8080.
        """
        token = self._token
        headers = {
            "Content-Type":      "application/json",
            "X-Forge-Authority": token,
            "Authorization":     f"Bearer {token}",
        }

        # ── Tentative 1 : Hub :8766 JSON-RPC ─────────────────────────────────
        payload_hub = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {
                "name":      self._tool,
                "arguments": self._args,
            },
        }).encode()
        result = _http_post(
            "http://localhost:8766/mcp",
            payload_hub, headers,
            timeout=2.0, attempts=3
        )
        if "error" not in result:
            return result, "hub:8766/mcp"

        # ── Fallback : Gateway :8080/execute ─────────────────────────────────
        payload_gw = json.dumps({
            "command": self._args.get("command", self._cmd_id),
            "source":  "palette",
            "agent":   "CLAUDE",
        }).encode()
        result2 = _http_post(
            "http://localhost:8080/execute",
            payload_gw, headers,
            timeout=2.0, attempts=2
        )
        if "error" not in result2:
            return result2, "gateway:8080/execute"

        # ── Fallback local : dispatch TUI direct ──────────────────────────────
        try:
            if str(APP_PATH) not in sys.path:
                sys.path.insert(0, str(APP_PATH))
            from forge_dispatch import dispatch
            cmd = self._args.get("command", self._cmd_id)
            local_result = dispatch(cmd, source="palette_hub")
            return {"result": str(local_result)[:300]}, "local_dispatch"
        except Exception as e:
            return {"error": f"all endpoints failed: {e}"}, "none"


# ── PaletteHubConnector ───────────────────────────────────────────────────────

class PaletteHubConnector(QObject):
    """
    COMMAND_HUB_BRIDGE_V17
    Connecteur asynchrone Palette → Hub.

    Usage :
        connector = PaletteHubConnector()
        connector.result_ready.connect(my_handler)
        connector.dispatch("@disco", "nokido_dispatch",
                           {"command": "@disco"})

    Signals :
        result_ready(cmd_id, result, seq_id, ok)
        dispatch_started(cmd_id)
        dispatch_failed(cmd_id, error)
    """
    result_ready     = Signal(str, dict, int, bool)
    dispatch_started = Signal(str)
    dispatch_failed  = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._token   = ""
        self._workers: list[_ConnectorWorker] = []
        self._pending = 0

        # Charger token au démarrage
        QTimer.singleShot(0, self._load_token)

    def _load_token(self):
        self._token = _get_token()

    def dispatch(self, cmd_id: str, tool: str, args: dict):
        """
        Lance la requête dans un QThread isolé.
        Non-bloquant — résultat via signal result_ready.
        """
        if not self._token:
            self._token = _get_token()

        self.dispatch_started.emit(cmd_id)
        self._pending += 1

        worker = _ConnectorWorker(cmd_id, tool, args, self._token, self)
        worker.result_ready.connect(self._on_result)
        worker.finished.connect(lambda: self._cleanup(worker))
        self._workers.append(worker)
        worker.start()

    def _on_result(self, cmd_id: str, result: dict, seq: int, ok: bool):
        self._pending -= 1
        self.result_ready.emit(cmd_id, result, seq, ok)
        if not ok:
            self.dispatch_failed.emit(
                cmd_id, result.get("error", "unknown")[:120]
            )

    def _cleanup(self, worker: _ConnectorWorker):
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()

    @property
    def is_busy(self) -> bool:
        return self._pending > 0

    def status(self) -> dict:
        return {
            "token_ok": bool(self._token),
            "pending":  self._pending,
            "workers":  len(self._workers),
        }
