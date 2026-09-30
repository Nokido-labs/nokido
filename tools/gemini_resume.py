#!/usr/bin/env python3
"""
gemini_resume.py — Relance Gemini CLI avec la derniere session du projet courant.

Usage :
    python tools/gemini_resume.py              # reprend la derniere session du CWD
    python tools/gemini_resume.py --list       # liste toutes les sessions
    python tools/gemini_resume.py --id <uuid>  # reprend une session specifique
"""

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

GEMINI_CMD = __import__("os").path.expanduser(r"~\AppData\Roaming\npm\gemini.cmd")
GEMINI_HOME = Path.home() / ".gemini"
TMP_DIR = GEMINI_HOME / "tmp"

PROJECT_MAP = {
    str(__import__("pathlib").Path(__file__).resolve().parents[1]): "laforge",
    str(__import__("pathlib").Path(__file__).resolve().parents[2]): "script-python-ia",
    __import__("os").path.expanduser(r"~"): "user",
}


def find_project_dir(cwd=None):
    cwd = cwd or os.getcwd()
    for path, name in sorted(PROJECT_MAP.items(), key=lambda x: -len(x[0])):
        if cwd.startswith(path):
            return name
    return None


def get_sessions(project):
    chats_dir = TMP_DIR / project / "chats"
    if not chats_dir.exists():
        return []
    sessions = []
    for f in sorted(chats_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            if not lines:
                continue
            data = json.loads(lines[0])
            sid = data.get("sessionId")
            if not sid:
                continue
            n_turns = sum(1 for l in lines if '"role":"user"' in l or '"role": "user"' in l)
            sessions.append(
                {
                    "sessionId": sid,
                    "file": f.name,
                    "size_kb": f.stat().st_size // 1024,
                    "mtime": datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "start": data.get("startTime", "?")[:19].replace("T", " "),
                    "turns": n_turns,
                }
            )
        except Exception:
            pass
    return sessions


def main():
    args = sys.argv[1:]
    cwd = os.getcwd()

    if "--list" in args:
        print("Sessions Gemini CLI disponibles:\n")
        for proj_name in sorted(p.name for p in TMP_DIR.iterdir() if p.is_dir()):
            sessions = get_sessions(proj_name)
            if not sessions:
                continue
            print(f"  {proj_name}/")
            for s in sessions[:5]:
                marker = "*" if s["turns"] > 0 else "."
                print(
                    f"    {marker} [{s['mtime']}] {s['turns']:3} turns  "
                    f"{s['size_kb']:4}kb  gemini --resume '{s['sessionId']}'"
                )
        return

    if "--id" in args:
        idx = args.index("--id")
        if idx + 1 < len(args):
            session_id = args[idx + 1]
            print(f"Reprise session: {session_id}")
            subprocess.run([GEMINI_CMD, "--resume", session_id], cwd=cwd)
            return

    project = find_project_dir(cwd)
    if not project:
        print(f"Projet inconnu pour: {cwd}")
        sys.exit(1)

    sessions = get_sessions(project)
    if not sessions:
        print(f"Aucune session pour le projet {project!r}")
        subprocess.run([GEMINI_CMD], cwd=cwd)
        return

    best = next((s for s in sessions if s["turns"] > 0), sessions[0])

    print(f"Projet : {project}")
    print(f"Session: {best['sessionId']}")
    print(f"Debut  : {best['start']}")
    print(f"Turns  : {best['turns']}")
    print(f"Taille : {best['size_kb']}kb")
    print(f"\n-> gemini --resume '{best['sessionId']}'\n")

    subprocess.run([GEMINI_CMD, "--resume", best["sessionId"]], cwd=cwd)


if __name__ == "__main__":
    main()
