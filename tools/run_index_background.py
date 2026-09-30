#!/usr/bin/env python3
"""Launch index_gitingest_rag.py in background, write log to logs/index_gitingest.log."""

__FORGE_COLOR__ = "digestif/ingest : lance index_gitingest_rag en arriere-plan"  # organe declare le 2026-09-06 (audit de raccordement)

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
script = ROOT / "tools" / "index_gitingest_rag.py"
logfile = ROOT / "logs" / "index_gitingest.log"
logfile.parent.mkdir(exist_ok=True)

args = sys.argv[1:]  # forward: repo name or --force

with open(logfile, "w", encoding="utf-8") as f:
    proc = subprocess.Popen(
        [__import__("os").path.expanduser("~/miniforge3/python.exe"), str(script)] + args,
        stdout=f,
        stderr=f,
        cwd=str(ROOT),
        creationflags=0x00000008,  # DETACHED_PROCESS
    )
print(f"PID={proc.pid} log={logfile}")
