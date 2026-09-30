#!/usr/bin/env python3
"""Run gitingest on Nokido repo → docs/gitingest_nokido.txt"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "gitingest_nokido.txt"

EXCLUDES = [
    "*.db",
    "*.gguf",
    "*.bin",
    "*.pyc",
    "*.whl",
    "*.exe",
    "*.dll",
    "*.pth",
    "*.onnx",
    "*.safetensors",
    "node_modules/*",
    "__pycache__/*",
    ".versions/*",
    "vllm-fork/*",
    "RAG/*",
    "logs/*.log",
    "sandbox/*",
    "_inception_archive/*",
    "data-Claude-Desktop*/*",
    ".run_tmp/*",
    "deno.lock",
]

args = [sys.executable, "-m", "gitingest", ".", "-o", str(OUT), "-s", "102400"]
for pat in EXCLUDES:
    args += ["-e", pat]

print(f"Running gitingest → {OUT}")
r = subprocess.run(args, capture_output=True, text=True, timeout=300, cwd=str(ROOT), errors="replace")
print(r.stdout[-800:] if r.stdout else "(no stdout)")
if r.stderr:
    print("STDERR:", r.stderr[-300:])
print("RC:", r.returncode)
if OUT.exists():
    print(f"Output size: {OUT.stat().st_size:,} bytes")
