#!/usr/bin/env python3
"""
claude_session_stop.py — Hook Stop Claude Code

Quand session Claude termine son tour :
1. Publish event topic=agent.claude.idle pour signaler dispo à Gemini
2. (optionnel) flush dernier message dans PANORAMA si pas commit

Configuré via ~/.claude/settings.json :
  {"hooks": {"Stop": [{"matcher":"*","hooks":[{
      "type":"command","command":"python.exe",
      "args":["...claude_session_stop.py"], "timeout":3000}]}]}}
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from forge_jeton_hook import jeton_du_hook  # noqa: E402

HUB = "http://127.0.0.1:8766/mcp"


def load_token() -> str:
    return jeton_du_hook(ROOT)


def main() -> int:
    # Lire l'input du hook (session_id / transcript_path) AVANT tout.
    sid, tpath = "", ""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            hi = json.loads(raw)
            sid = hi.get("session_id", "")
            tpath = hi.get("transcript_path", "")
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/claude_session_stop.py', 86, exc_info=True)

    # #6 roadmap hermes : fork post-turn LOCAL (auto-anchor solution + propose skill),
    # lancé DÉTACHÉ → ne bloque JAMAIS les 3s du Stop-hook. LLM local uniquement
    # (0 token Claude, 0 API). Throttle 300s côté review. Fail-soft. cf forge_background_review.py
    if sid:
        try:
            import subprocess

            _script = Path(__file__).resolve().parent / "forge_background_review.py"
            _flags = (
                (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
                if os.name == "nt"
                else 0
            )
            subprocess.Popen(
                [sys.executable, str(_script), sid, tpath],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_flags,
                close_fds=True,
            )
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/claude_session_stop.py', 110, exc_info=True)

    token = load_token()
    if not token:
        return 0
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "event",
                    "arguments": {
                        "action": "publish",
                        "topic": "agent.claude.idle",
                        "kind": "info",
                        "data": {"ts": now, "msg": "claude turn complete, listening"},
                    },
                },
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            HUB,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "LaForge-Agent-Name": "CLAUDE_HOOK",
                "X-Agent-Name": "CLAUDE_HOOK",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/claude_session_stop.py', 146, exc_info=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
