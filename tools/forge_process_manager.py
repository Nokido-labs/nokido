"""forge_process_manager.py - Gestionnaire unifie des process Nokido v18.3
Remplace: launcher.py + restart_claude.py + tray Popen + services_launcher (partiel)
"""

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
PID_FILE = ROOT / ".nokido_pids.json"
BRIDGE_TMP = ROOT / ".bridge_tmp"
RUN_TMP = ROOT / ".run_tmp"
CLAUDE_EXE = r"C:\Program Files\WindowsApps\Claude_1.4758.0.0_x64__pzs8sxrjxfjjc\app\Claude.exe"
HUB_PORT = 8766
HUB_SERVICE = "NokidoMCP"


# --- PID FILE JSON ---
def _load_pids() -> dict:
    try:
        return json.loads(PID_FILE.read_text(encoding="utf-8"))
    except:
        return {}


def _save_pids(data: dict):
    PID_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _is_alive(pid: int) -> bool:
    """Verifie si un PID existe et tourne (Windows)."""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
        , errors="replace")
        return str(pid) in r.stdout
    except:
        return False


# --- PORT UTILS ---
def port_pid(port: int) -> int | None:
    """Retourne le PID qui ecoute sur le port, ou None."""
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-NetTCPConnection -LocalPort {port} -State Listen -EA SilentlyContinue).OwningProcess",
        ],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    errors="replace")
    s = r.stdout.strip()
    return int(s) if s.isdigit() else None


def kill_port(port: int) -> bool:
    """Kill le process sur le port. Retourne True si libere."""
    pid = port_pid(port)
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        for _ in range(10):
            time.sleep(0.5)
            if not port_pid(port):
                return True
        return False
    return True  # deja libre


# --- HUB ---
def restart_hub(purge_pyc: bool = True) -> dict:
    """Kill port 8766 -> purge pyc -> nssm start -> wait. Retourne status."""
    t0 = time.monotonic()
    kill_port(HUB_PORT)
    if purge_pyc:
        for d in ["app/__pycache__", "tools/__pycache__"]:
            try:
                shutil.rmtree(ROOT / d)
            except:
                pass
    subprocess.run(["nssm", "start", HUB_SERVICE], capture_output=True)
    # Wait hub UP
    for _ in range(30):
        time.sleep(0.5)
        pid = port_pid(HUB_PORT)
        if pid:
            pids = _load_pids()
            pids["hub"] = {"pid": pid, "port": HUB_PORT, "started": datetime.now().isoformat()}
            _save_pids(pids)
            return {"ok": True, "pid": pid, "ms": round((time.monotonic() - t0) * 1000)}
    return {"ok": False, "error": "hub timeout 15s"}


# --- WORKERS ---
def worker_status() -> list:
    """Lit le statut des workers depuis forge_python_runner."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_python_runner import get_runner

        return get_runner().worker_status()
    except Exception as e:
        return [{"error": str(e)}]


# --- TMPFILE ISOLATION ---
def ensure_tmp_dirs():
    """Cree les dossiers tmp isoles pour bridge et runner."""
    BRIDGE_TMP.mkdir(exist_ok=True)
    RUN_TMP.mkdir(exist_ok=True)
    # Purger les fichiers > 5min
    cutoff = time.time() - 300
    for d in [BRIDGE_TMP, RUN_TMP]:
        for f in d.glob("*.py"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except:
                pass


# --- CLAUDE DESKTOP ---
def restart_claude() -> bool:
    """Kill claude.exe -> attendre hub UP -> relancer."""
    subprocess.run(["taskkill", "/F", "/IM", "claude.exe"], capture_output=True)
    time.sleep(2)
    hub_up = any(port_pid(HUB_PORT) for _ in range(10) if not time.sleep(0.5))
    subprocess.Popen([CLAUDE_EXE])
    return hub_up


# --- STATUS GLOBAL ---
def status() -> dict:
    """Snapshot complet de tous les process Nokido."""
    pids = _load_pids()
    return {
        "hub": {"pid": port_pid(HUB_PORT), "port": HUB_PORT, "alive": bool(port_pid(HUB_PORT))},
        "workers": worker_status(),
        "bridge_tmp": len(list(BRIDGE_TMP.glob("*.py"))),
        "run_tmp": len(list(RUN_TMP.glob("*.py"))),
        "pid_file": pids,
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "cmd", choices=["status", "restart_hub", "restart_claude", "workers", "clean_tmp"]
    )
    args = ap.parse_args()
    if args.cmd == "status":
        print(json.dumps(status(), indent=2, default=str))
    elif args.cmd == "restart_hub":
        print(json.dumps(restart_hub(), indent=2))
    elif args.cmd == "restart_claude":
        print("OK" if restart_claude() else "ERR")
    elif args.cmd == "workers":
        print(json.dumps(worker_status(), indent=2))
    elif args.cmd == "clean_tmp":
        ensure_tmp_dirs()
        print("cleaned")
