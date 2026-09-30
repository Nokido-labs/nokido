#!/usr/bin/env python3
"""Restart hub: kill current process then start fresh. Must run detached."""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PID = int(sys.argv[1]) if len(sys.argv) > 1 else None

time.sleep(1)  # give hub time to send response before dying

if PID:
    subprocess.run(
        ["taskkill", "/F", "/PID", str(PID)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(2)

log = ROOT / "logs" / "hub.log"
log.parent.mkdir(exist_ok=True)

with open(log, "a", encoding="utf-8") as f:
    proc = subprocess.Popen(
        [__import__("os").path.expanduser("~/miniforge3/python.exe"), "tools/nokido_hub.py"],
        stdout=f,
        stderr=f,
        cwd=str(ROOT),
        creationflags=0x00000008,  # DETACHED_PROCESS
    )
    print(f"Hub restarted PID={proc.pid}", flush=True)
