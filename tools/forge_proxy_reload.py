"""forge_proxy_reload — recharge un service proxy local (defaut forge_openai_proxy :7777).

Tue le detenteur du port (netstat + taskkill) puis relance le script DETACHE = prend le nouveau
code. A lancer PRIVILEGE via `run action=trusted_script` : le RESTART superviseur renvoie 401 et
le kill cote sandbox/job = 'Access denied' (process owned SYSTEM). Reutilisable :
  LAFORGE_PYTHON tools/forge_proxy_reload.py [--port 7777] [--script tools/forge_openai_proxy.py]
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/service : recharge un service proxy local (defaut :7777)"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = __import__("os").path.expanduser(r"~/miniforge3/python.exe")


def _sh(cmd: str) -> str:
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=25, errors="replace").stdout
    except Exception as e:  # noqa: BLE001
        return f"ERR {e!r}"


def reload_proxy(port: int, script: str) -> dict:
    out: dict = {"port": port, "script": script}
    ns = _sh(f'netstat -ano | findstr ":{port}"')
    pids = sorted({ln.split()[-1] for ln in ns.splitlines()
                   if "LISTENING" in ln and ln.split() and ln.split()[-1].isdigit()})
    out["listen_pids"] = pids
    out["kill"] = {pid: _sh(f"taskkill /F /PID {pid}").strip()[:90] for pid in pids}
    time.sleep(3)
    try:
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        env = {**os.environ, "PYTHONNOUSERSITE": "1", "PYTHONIOENCODING": "utf-8"}
        p = subprocess.Popen([PY, script], cwd=str(ROOT), env=env, creationflags=flags,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        out["launched_pid"] = p.pid
    except Exception as e:  # noqa: BLE001
        out["launch_err"] = repr(e)
    time.sleep(8)
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=8)
        out["health"] = json.loads(r.read()).get("status")
    except Exception as e:  # noqa: BLE001
        out["health_err"] = repr(e)[:120]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--script", default="tools/forge_openai_proxy.py")
    args = ap.parse_args()
    print(json.dumps(reload_proxy(args.port, args.script), default=str))


if __name__ == "__main__":
    main()
