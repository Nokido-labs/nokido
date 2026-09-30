
__FORGE_COLOR__ = "reseau/node : lance netcfg_mcp serve :8768 standalone, detache"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import subprocess
from pathlib import Path

root = Path(str(__import__("pathlib").Path(__file__).resolve().parents[2] / "netcfg-agent-mcp"))
log_file = root / "logs" / "mcp_8768.log"

cmd = [
    __import__("os").path.expanduser(r"~\miniforge3\python.exe"),
    "-m",
    "netcfg_mcp.cli",
    "serve",
    "--port",
    "8768",
    "--standalone",
]

env = os.environ.copy()
env["PYTHONPATH"] = str(root)

with open(log_file, "a", encoding="utf-8") as f:
    p = subprocess.Popen(
        cmd,
        cwd=str(root),
        stdout=f,
        stderr=f,
        env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008,
    )
print(f"OK:PID={p.pid}")
