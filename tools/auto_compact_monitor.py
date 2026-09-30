#!/usr/bin/env python
"""auto_compact_monitor.py — Détecte si le contexte Claude dépasse 800 lignes.

Usage (one-shot):
    %USERPROFILE%/miniforge3/python.exe tools/auto_compact_monitor.py
"""

import glob
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_PROJECTS = Path(__import__("os").path.expanduser("~/.claude/projects"))
TRIGGER_PATH = ROOT / "sandbox" / "compact_trigger.json"


def _newest_jsonl() -> Path | None:
    files = glob.glob(str(CLAUDE_PROJECTS / "**/*.jsonl"), recursive=True)
    if not files:
        return None
    return Path(max(files, key=os.path.getctime))


def main() -> None:
    f = _newest_jsonl()
    if not f:
        print("[compact_monitor] no .jsonl found")
        return

    lines = sum(1 for _ in f.open(encoding="utf-8", errors="replace"))
    trigger = lines > 800
    TRIGGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRIGGER_PATH.write_text(
        json.dumps({"trigger": trigger, "lines": lines, "file": str(f)}),
        encoding="utf-8",
    )
    print(f"[compact_monitor] {f.name}: {lines} lines, trigger={trigger}")


if __name__ == "__main__":
    main()
