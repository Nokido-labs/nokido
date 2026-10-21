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

# Le hook Stop tire a CHAQUE FIN DE TOUR, pas en fin de session. Mesure du 2026-10-14 : une entree vide
# « Session Claude end » par tour dans lessons_learned.md, et un message RESCUE que Claude s'adressait a lui-meme a
# chaque tour (18 non lus en une matinee). Resume et resync : une fois par fenetre de 30 min ; les daemons (3.) a
# chaque passage, c'est une simple lecture de pouls.
ANCRE = ROOT / "sandbox" / "session_anchor.dernier"
PERIODE_S = 1800


def _recent(maintenant: float) -> bool:
    try:
        return maintenant - float(ANCRE.read_text(encoding="utf-8").strip()) < PERIODE_S
    except (OSError, ValueError):
        return False  # muet-ok : ancre absente ou illisible = on agit, comme avant le 2026-10-14


_maintenant = __import__("time").time()
if _recent(_maintenant):
    print("[session_anchor] resume + resync SAUTES : dernier passage il y a moins de %d min" % (PERIODE_S // 60))
else:
    try:
        ANCRE.write_text("%.0f" % _maintenant, encoding="utf-8")
    except OSError as e:
        print(f"[session_anchor] ancre NON ecrite ({type(e).__name__}) : le prochain tour refera le resume",
              file=sys.stderr)
    # 1. session_summary → lessons_learned.md
    try:
        from nokido_agent.app.forge_self_correction import session_summary

        session_summary(commits=[], tests="auto-hook", notes="Session Claude end")
        print("[session_anchor] session_summary OK")
    except Exception as e:
        print(f"[session_anchor] session_summary skip: {e}", file=sys.stderr)

    # 2. resync gemini — écrit sandbox/resume_prompt_gemini.md ; --sans-notifier : c'est Claude qui l'appelle, il
    #    n'a pas a se prevenir lui-meme.
    try:
        r = subprocess.run(
            [PYTHON, str(ROOT / "tools" / "forge_rescue.py"), "--resync", "gemini", "--sans-notifier"],
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
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/session_anchor.py', 82, exc_info=True)
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
