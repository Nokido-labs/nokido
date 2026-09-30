"""tools/restart_claude.py — Restart Claude Desktop + hub + clients.

⚠ WINDOWS-ONLY : utilise PowerShell (`Get-NetTCPConnection`), `taskkill`,
NSSM. Sur Linux/macOS, équivalent à implémenter (systemctl / launchctl +
`lsof -i` ou `ss -tnlp`). PR welcome.

Pour Linux/macOS, lance le hub directement :
    source .venv/bin/activate && python tools/nokido_hub.py
ou via Docker compose (cf README §Quick start).
"""

__FORGE_COLOR__ = "vegetatif/restart : redemarre Claude Desktop, hub et clients (Windows)"  # organe declare le 2026-09-06 (audit de raccordement)

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

if sys.platform != "win32":
    sys.exit(
        "[restart_claude] WINDOWS-ONLY. Sur Linux/macOS : relance manuellement "
        "le hub (`python tools/nokido_hub.py`) ou via systemd/launchd."
    )

HUB = "http://127.0.0.1:8766/health"
HUB_PORT = 8766
SVC = "NokidoMCP"
# LAFORGE_ROOT permet override (path multi-OS / sandbox). Fallback = parent du script.
BASE = os.environ.get("LAFORGE_ROOT", str(Path(__file__).resolve().parent.parent))

# Lanceurs identifies — chemins overridables via env vars pour portabilité
_USER_HOME = Path(os.environ.get("USERPROFILE", str(Path.home())))
CLAUDE_EXE = os.environ.get(
    "CLAUDE_EXE",
    r"C:\Program Files\WindowsApps\Claude_1.4758.0.0_x64__pzs8sxrjxfjjc\app\Claude.exe",
)
CLAUDE_CLI = os.environ.get("CLAUDE_CLI", str(_USER_HOME / "AppData/Roaming/npm/claude.cmd"))
GEMINI_CLI = os.environ.get("GEMINI_CLI", str(_USER_HOME / "AppData/Roaming/npm/gemini.cmd"))

# Tokens par agent — backed by DPAPI vault via forge_secrets
sys.path.insert(0, str(Path(BASE)))
from nokido_agent.app.forge_secrets import get_secret  # noqa: E402

TOKENS = {
    "CLAUDE": get_secret("FORGE_TOKEN_CLAUDE") or "",
    "GEMINI": get_secret("FORGE_TOKEN_GEMINI") or "",
    "CLAUDE_CLI": get_secret("FORGE_TOKEN_CLAUDE_CLI") or "",
    "GEMINI_CLI": get_secret("FORGE_TOKEN_GEMINI_HEADLESS") or "",
    "BRIDGE": get_secret("FORGE_TOKEN_BRIDGE") or "",
}


def _port_pid(port):
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-NetTCPConnection -LocalPort {port} -State Listen -EA SilentlyContinue).OwningProcess",
        ],
        capture_output=True,
        text=True,
    errors="replace")
    s = r.stdout.strip()
    return int(s) if s.isdigit() else None


def kill_port(port=HUB_PORT):
    pid = _port_pid(port)
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        for _ in range(10):
            time.sleep(0.5)
            if not _port_pid(port):
                return True
    return True


def restart_hub(purge_pyc=True):
    """Kill port -> purge pyc -> nssm start -> wait UP."""
    print(f"[restart_hub] kill port {HUB_PORT}...")
    kill_port(HUB_PORT)
    if purge_pyc:
        import shutil

        for d in ["app/__pycache__", "tools/__pycache__"]:
            try:
                shutil.rmtree(f"{BASE}/{d}")
            except:
                pass
    subprocess.run(["nssm", "start", SVC], capture_output=True)
    for _ in range(24):
        time.sleep(1)
        try:
            urllib.request.urlopen(HUB, timeout=2)
            print("[restart_hub] Hub UP")
            return True
        except:
            pass
    print("[restart_hub] Hub timeout")
    return False


def restart_claude():
    """Kill claude.exe -> relance avec bon path."""
    subprocess.run(["taskkill", "/f", "/im", "claude.exe"], capture_output=True)
    time.sleep(2)
    if os.path.exists(CLAUDE_EXE):
        subprocess.Popen([CLAUDE_EXE])
        print(f"[restart_claude] Lance: {CLAUDE_EXE}")
    else:
        print(f"[restart_claude] ERREUR: {CLAUDE_EXE} introuvable")
        return False
    return True


def full():
    print("[full] Restart hub + Claude...")
    if restart_hub():
        restart_claude()


if __name__ == "__main__":
    cmds = {"hub": restart_hub, "claude": restart_claude, "kill_port": kill_port}
    cmds.get(sys.argv[1] if len(sys.argv) > 1 else "", full)()
