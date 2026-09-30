#!/usr/bin/env python3
"""tools/session_anchor.py — Hook Stop Claude: session_summary + resync Gemini + daemons."""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = __import__("os").path.expanduser(r"~\miniforge3\python.exe")
sys.path.insert(0, str(ROOT))

# 1. session_summary → lessons_learned.md
try:
    from nokido_agent.app.forge_self_correction import session_summary

    session_summary(commits=[], tests="auto-hook", notes="Session Claude end")
    print("[session_anchor] session_summary OK")
except Exception as e:
    print(f"[session_anchor] session_summary skip: {e}", file=sys.stderr)

# 2. resync gemini — écrit sandbox/resume_prompt_gemini.md + notify hub
try:
    r = subprocess.run(
        [PYTHON, str(ROOT / "tools" / "forge_rescue.py"), "--resync", "gemini"],
        capture_output=True,
        text=True,
        timeout=20,
        cwd=str(ROOT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    errors="replace")
    print("[session_anchor] resync gemini:", r.stdout.strip()[:120] or r.stderr.strip()[:80])
except Exception as e:
    print(f"[session_anchor] resync gemini skip: {e}", file=sys.stderr)

# 3. vérifier daemons critiques — relancer si morts (heartbeat > 5 min)
DAEMONS = [
    ("multi_llm_daemon", ROOT / "tools" / "multi_llm_daemon.py"),
    ("gemini_poll_daemon", ROOT / "tools" / "gemini_poll_daemon.py"),
]
for name, script in DAEMONS:
    hb = ROOT / "sandbox" / f"{name}.heartbeat"
    dead = True
    if hb.exists():
        try:
            d = json.loads(hb.read_text(encoding="utf-8"))
            ts = d.get("ts", "")
            if ts:
                age = (
                    datetime.datetime.now() - datetime.datetime.fromisoformat(ts[:19])
                ).total_seconds()
                dead = age > 300
        except Exception:
            pass
    if dead:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        p = subprocess.Popen(
            [PYTHON, str(script)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        print(f"[session_anchor] relancé {name} PID={p.pid}")
    else:
        print(f"[session_anchor] {name} OK")
