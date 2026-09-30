"""
forge_lifecycle_tool.py — MCP tool: manage_forge_lifecycle
===========================================================
Façade unifiée START/STOP/RESTART/STATUS/LIST/SHUTDOWN_ALL/BOOT_ALL des
services Nokido. Source de vérité unique = supervisor :8765 (Deno
LaForge-Master). Tous CLI tiers (Gemini, Codex, Claude) passent par CE
tool MCP → ils n'ont jamais besoin de connaître :8765 ni NSSM.

Migration 2026-05-24 : ne dépend plus de NSSM. Refactor pour parler HTTP
au supervisor (post-migration #3). PROCESS_ORGANS (llama-server etc.)
conservés inchangés — pas gérés par supervisor.
"""

from __future__ import annotations

import json
import os
import subprocess
import signal
import urllib.error
import urllib.request
from pathlib import Path

SUPERVISOR_URL = os.environ.get("LAFORGE_SUPERVISOR_URL", "http://127.0.0.1:8765")
_HTTP_TIMEOUT = 5.0

# Resolve paths relative to this file so the module is portable
_HERE = Path(__file__).resolve().parent  # app/
ROOT = _HERE.parent  # LaForge/
LAFORGE_PYTHON = os.environ.get(
    "LAFORGE_PYTHON_BIN",
    str(Path.home() / "miniforge3" / "python.exe"),
)

NSSM = r"C:\ProgramData\chocolatey\lib\NSSM\tools\nssm.exe"

ALLOWED_ORGANS = [
    "NokidoMCP",
    "NokidoWebHub",
    "NokidoDenoProxy",
    "NokidoDenoWebHub",
    "NokidoOpenAIProxy",
    "NokidoDenoHubMCP",
    "NokidoLlamaRouter",
    "NokidoAutonomousLoops",
    "NokidoGeminiDaemon",
    "NokidoGraph",
    "NokidoHebbian",
    "NokidoHomeostasis",
    "NokidoRSSWatcher",
    "NokidoWatchdog",
    "netcfg-agent-mcp",
    "llama-server",
    "llama-proxy",
]

_LLAMA_DIR = os.environ.get("LLAMA_DIR", str(Path.home() / "llama-vulkan"))
_LLAMA_CMD = [
    str(Path(_LLAMA_DIR) / "llama-server.exe"),
    "-m",
    r"D:\ollama\models\blobs\sha256-60e05f2100071479f596b964f89f510f057ce397ea22f2833a0cfe029bfc2463",
    "-md",
    r"D:\ollama\models\blobs\sha256-29d8c98fa6b098e200069bfb88b9508dc3e85586d20cba59f8dda9a808165104",
    "--host",
    "127.0.0.1",
    "--port",
    "8091",
    "-ngl",
    "99",
    "-ngld",
    "99",
    "-c",
    "32768",
    "-cd",
    "32768",
    "-ctk",
    "q8_0",
    "-ctv",
    "q8_0",
    "-fa",
    "auto",
    "--cache-prompt",
    "--prio",
    "1",
    "--threads",
    "-1",
    "-np",
    "-1",
    "--draft-max",
    "16",
    "--draft-min",
    "4",
    "-a",
    "qwen,qwen2.5-coder,laforge-coder",
]
PROTECTED = {"NokidoMCP", "NokidoWebHub"}  # cannot STOP
VALID_ACTIONS = {"START", "STOP", "RESTART", "STATUS", "LIST", "SHUTDOWN_ALL", "BOOT_ALL"}

# action → supervisor path (POST). LIST/STATUS handled separately (GET).
_ACTION_PATH = {
    "START": "/supervisor/wake/",
    "STOP": "/supervisor/sleep/",
    "RESTART": "/supervisor/restart/",
}


def _supervisor_call(method: str, path: str) -> dict:
    """Sync HTTP call to supervisor :8765. Returns {ok, status, data|error}."""
    url = SUPERVISOR_URL.rstrip("/") + path
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                data = {"raw": body[:500]}
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "data": data}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": f"HTTP {exc.code}: {exc.reason}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "status": 0, "error": f"supervisor unreachable: {exc}"}


# Non-NSSM organs: launched via subprocess, identified by port
def _proxy_cmd(service: str) -> list[str]:
    return [
        LAFORGE_PYTHON,
        str(ROOT / "tools" / "forge_demand_proxy.py"),
        "--service",
        service,
    ]


_NETCFG_MCP_DIR = os.environ.get(
    "NETCFG_MCP_DIR",
    str(ROOT.parent / "netcfg-agent-mcp"),
)

PROCESS_ORGANS = {
    "llama-proxy": {
        "port": 8091,
        "cmd": _proxy_cmd("llama"),
        "cwd": str(ROOT),
        "log": str(ROOT / "sandbox" / "llama_proxy.log"),
    },
    "llama-server": {
        "port": 8092,
        "cmd": _LLAMA_CMD,
        "cwd": _LLAMA_DIR,
        "log": str(ROOT / "sandbox" / "llama_server.log"),
    },
    "netcfg-agent-mcp": {
        "port": 8768,
        "cmd": [
            LAFORGE_PYTHON,
            "-m",
            "netcfg_mcp.cli",
            "serve",
            "--port",
            "8768",
            "--standalone",
        ],
        "cwd": _NETCFG_MCP_DIR,
        "env_extra": {"PYTHONPATH": _NETCFG_MCP_DIR},
        "log": str(Path(_NETCFG_MCP_DIR) / "logs" / "mcp_8768.log"),
    },
}


def _process_action(organ: str, action: str) -> dict:
    """Handle START/STOP/RESTART/STATUS for non-NSSM process organs."""
    import psutil

    cfg = PROCESS_ORGANS[organ]
    port = cfg["port"]

    def find_pid() -> int | None:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr.port == port and conn.status == "LISTEN":
                return conn.pid
        return None

    pid = find_pid()

    if action == "STATUS":
        return {"ok": True, "organ_name": organ, "action": action, "message": f"UP pid={pid}" if pid else "DOWN"}

    # GATE world-model du corps (owner 2026-07-23) : ANTICIPER l'impact AVANT une
    # action destructive au lieu de la subir. On REFUSE un STOP qui cascade sur un
    # organe ESSENTIEL (verdict dangerous), sauf LAFORGE_LIFECYCLE_FORCE. RESTART =
    # recovery intentionnel -> autorise, prediction jointe (awareness). Best-effort :
    # world-model indispo -> ne JAMAIS bloquer l'ops. C'est le corps qui prevoit, pas
    # qui reagit apres coup (cf le keeper qui a tue un Docker sain le matin meme).
    _impact = None
    if action in {"STOP", "RESTART"}:
        try:
            from nokido_agent.app.forge_body_world_model import predict_impact

            _impact = predict_impact(organ, action)
            if (action == "STOP" and _impact.get("verdict") == "dangerous"
                    and not os.environ.get("LAFORGE_LIFECYCLE_FORCE")):
                return {"ok": False, "organ_name": organ, "action": action, "impact": _impact,
                        "message": f"REFUSE par world-model (dangerous): {_impact.get('reason')} "
                                   "-- LAFORGE_LIFECYCLE_FORCE=1 pour outrepasser"}
        except Exception:
            pass

    if action in {"STOP", "RESTART"} and pid:
        try:
            psutil.Process(pid).terminate()
        except Exception as e:
            return {"ok": False, "organ_name": organ, "action": action, "message": f"terminate: {e}"}

    if action == "STOP":
        return {"ok": True, "organ_name": organ, "action": action, "message": f"Stopped pid={pid}"}

    # START or RESTART
    import time

    if action == "RESTART" and pid:
        time.sleep(1)

    env = os.environ.copy()
    env.update(cfg.get("env_extra", {}))
    log_path = cfg.get("log")
    try:
        if log_path:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            log_f = open(log_path, "a", encoding="utf-8")
            proc = subprocess.Popen(
                cfg["cmd"],
                cwd=cfg["cwd"],
                env=env,
                stdout=log_f,
                stderr=log_f,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            proc = subprocess.Popen(
                cfg["cmd"],
                cwd=cfg["cwd"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        return {"ok": True, "organ_name": organ, "action": action, "message": f"Started pid={proc.pid}"}
    except Exception as e:
        return {"ok": False, "organ_name": organ, "action": action, "message": str(e)[:200]}


def handle_manage_forge_lifecycle(
    organ_name: str,
    action: str,
    priority: str = "NORMAL",
) -> dict:
    """MCP tool entry-point — façade unique pour tous les CLI tiers.

    - START/STOP/RESTART/STATUS sur 1 service → délègue supervisor :8765
      (POST /supervisor/{wake,sleep,restart}/{name}) sauf PROCESS_ORGANS
      (llama-server, netcfg-agent-mcp, ...) qui restent gérés par psutil.
    - LIST → liste tous services connus du supervisor (GET /supervisor/status).
    - SHUTDOWN_ALL → POST /supervisor/shutdown (reverse-wave 5→1).
    - BOOT_ALL → wake itératif sur tous services en status=sleeping.
    """
    action = action.upper()
    organ_name_stripped = organ_name.strip()

    if action not in VALID_ACTIONS:
        return {
            "ok": False,
            "organ_name": organ_name_stripped,
            "action": action,
            "message": f"Invalid action. Use: {sorted(VALID_ACTIONS)}",
        }

    # Bulk actions — organ_name ignored
    if action == "LIST":
        r = _supervisor_call("GET", "/supervisor/status")
        return {"ok": r["ok"], "action": "LIST", "data": r.get("data") or r.get("error")}
    if action == "SHUTDOWN_ALL":
        r = _supervisor_call("POST", "/supervisor/shutdown")
        return {"ok": r["ok"], "action": "SHUTDOWN_ALL", "data": r.get("data") or r.get("error")}
    if action == "BOOT_ALL":
        st = _supervisor_call("GET", "/supervisor/status")
        if not st["ok"]:
            return {"ok": False, "action": "BOOT_ALL", "message": st.get("error", "status fetch failed")}
        services = (st.get("data") or {}).get("services", {})
        woken = []
        for name, info in services.items():
            if info.get("status") == "sleeping":
                rw = _supervisor_call("POST", f"/supervisor/wake/{name}")
                woken.append({"name": name, "ok": rw["ok"]})
        return {"ok": True, "action": "BOOT_ALL", "woken": woken}

    # Per-service actions below need a name
    if not organ_name_stripped:
        return {
            "ok": False,
            "organ_name": "",
            "action": action,
            "message": "organ_name required for action " + action,
        }

    if action == "STOP" and organ_name_stripped in PROTECTED:
        return {
            "ok": False,
            "organ_name": organ_name_stripped,
            "action": action,
            "message": f"{organ_name_stripped} is protected — STOP refused.",
        }

    # PROCESS_ORGANS = launched outside supervisor (llama-server etc.) — psutil path
    if organ_name_stripped in PROCESS_ORGANS:
        return _process_action(organ_name_stripped, action)

    # Resource gate on START (skip if priority=HIGH)
    if action == "START":
        try:
            from nokido_agent.app.forge_resource_manager import should_throttle

            if should_throttle() and priority.upper() != "HIGH":
                return {
                    "ok": False,
                    "organ_name": organ_name_stripped,
                    "action": action,
                    "message": "Resources throttled. Use priority=HIGH to force.",
                }
        except ImportError:
            pass

    # STATUS = read-only filter on /supervisor/status
    if action == "STATUS":
        st = _supervisor_call("GET", "/supervisor/status")
        if not st["ok"]:
            return {
                "ok": False,
                "organ_name": organ_name_stripped,
                "action": action,
                "message": st.get("error", "status fetch failed"),
            }
        services = (st.get("data") or {}).get("services", {})
        info = services.get(organ_name_stripped)
        if info is None:
            return {
                "ok": False,
                "organ_name": organ_name_stripped,
                "action": action,
                "message": "unknown service in supervisor",
            }
        return {"ok": True, "organ_name": organ_name_stripped, "action": action, "data": info}

    # START/STOP/RESTART → POST /supervisor/{wake,sleep,restart}/<name>
    path = _ACTION_PATH[action] + organ_name_stripped
    r = _supervisor_call("POST", path)
    return {
        "ok": r["ok"],
        "organ_name": organ_name_stripped,
        "action": action,
        "data": r.get("data"),
        "message": r.get("error") or ("OK" if r["ok"] else "supervisor refused"),
    }
