#!/usr/bin/env python3
"""tools/restart_daemon.py — Kill all gemini_poll_daemon processes + start one fresh."""

__FORGE_COLOR__ = "vegetatif/restart : tue et relance gemini_poll_daemon"  # organe declare le 2026-09-06 (audit de raccordement)

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAEMON = ROOT / "tools" / "gemini_poll_daemon.py"


def kill_existing() -> int:
    """Kill all python processes running gemini_poll_daemon.py."""
    killed = 0
    try:
        import psutil

        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmd = proc.info.get("cmdline") or []
                if any("gemini_poll_daemon" in str(c) for c in cmd):
                    proc.kill()
                    killed += 1
                    print(f"killed PID={proc.info['pid']}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except ImportError:
        # Fallback Windows tasklist+taskkill
        out = subprocess.check_output(
            [
                "wmic",
                "process",
                "where",
                "name='python.exe' and CommandLine like '%gemini_poll_daemon%'",
                "get",
                "ProcessId",
            ],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="replace")
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                subprocess.run(["taskkill", "/F", "/PID", line], stdout=subprocess.DEVNULL)
                killed += 1
                print(f"killed PID={line}")
    return killed


killed = kill_existing()
print(f"total killed: {killed}")
time.sleep(1)  # let ports/locks release

proc = subprocess.Popen(
    [sys.executable, str(DAEMON)],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    cwd=str(ROOT),
    close_fds=True,
)
print(f"started PID={proc.pid}")
