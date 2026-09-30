"""Adapter Services — supervisor :8765.

Lit /supervisor/status, propose actions wake/sleep/restart sur 1 service.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Optional

SUP_URL = "http://127.0.0.1:8765"


def _get(path: str, timeout: float = 5.0) -> dict:
    try:
        with urllib.request.urlopen(f"{SUP_URL}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)[:120]}


def _post(path: str, timeout: float = 8.0) -> dict:
    try:
        req = urllib.request.Request(f"{SUP_URL}{path}", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def list_services() -> list[dict]:
    """Retourne liste services avec status/pid/restarts/uptime/essential."""
    st = _get("/supervisor/status")
    services = st.get("services", {})
    if not isinstance(services, dict):
        return []
    out: list[dict] = []
    for name, s in services.items():
        if not isinstance(s, dict):
            continue
        out.append(
            {
                "name": name,
                "status": s.get("status", "?"),
                "pid": s.get("pid"),
                "restarts": s.get("restarts", 0),
                "uptime_s": s.get("uptime_s"),
                "essential": bool(s.get("essential")),
                "port": s.get("port"),
            }
        )
    # tri : running first, sleeping after, stopped last ; alpha intra-group
    order = {"running": 0, "starting": 1, "restarting": 2, "sleeping": 3, "stopped": 4, "disabled": 5}
    out.sort(key=lambda x: (order.get(x["status"], 9), x["name"]))
    return out


def wake(name: str) -> dict:
    return _post(f"/supervisor/wake/{name}")


def sleep_svc(name: str) -> dict:
    return _post(f"/supervisor/sleep/{name}")


def restart(name: str) -> dict:
    return _post(f"/supervisor/restart/{name}")


def supervisor_up() -> bool:
    return "error" not in _get("/supervisor/status", timeout=2.0)
