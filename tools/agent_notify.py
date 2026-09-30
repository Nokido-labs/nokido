#!/usr/bin/env python3
"""tools/agent_notify.py — Notification inter-agents bidirectionnelle.

Usage:
  # N'importe quel agent peut notifier n'importe quel autre
  python agent_notify.py --to claude --msg "texte libre"
  python agent_notify.py --to gemini --task "titre" --desc "desc" --priority 2
  python agent_notify.py --to claude --tasks tasks.json
  python agent_notify.py --to cline  --task "titre" --priority 1

Aliases acceptés pour --to: claude/agt_claude, gemini/agt_gemini, cline/agt_cline, daemon/agt_daemon

Appel depuis hub (Gemini, Cline, etc.):
  run action=shell commands=["LAFORGE_PYTHON tools/agent_notify.py --to claude --task '...' --desc '...'"]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

AGENT_ALIASES = {
    "claude": "agt_claude",
    "agt_claude": "agt_claude",
    "gemini": "agt_gemini",
    "agt_gemini": "agt_gemini",
    "cline": "agt_cline",
    "agt_cline": "agt_cline",
    "daemon": "agt_daemon",
    "agt_daemon": "agt_daemon",
    "hub": "agt_hub",
    "agt_hub": "agt_hub",
}

TAG_MAP = {
    "agt_claude": "CLAUDE",
    "agt_gemini": "GEMINI",
    "agt_cline": "CLINE",
    "agt_daemon": "DAEMON",
    "agt_hub": "HUB",
}


def resolve_agent(name: str) -> str:
    key = name.lower().strip()
    if key not in AGENT_ALIASES:
        raise ValueError(f"Agent inconnu: {name}. Valides: {list(AGENT_ALIASES)}")
    return AGENT_ALIASES[key]


def send(to_agent: str, payload: dict, from_agent: str = "claude") -> None:
    import sqlite3

    from nokido_agent.app.forge_state_manager import get_state_manager

    sm = get_state_manager()
    tag = TAG_MAP.get(to_agent, to_agent.upper())
    msg_text = json.dumps(payload, ensure_ascii=False)
    tagged = f"[{tag}] {msg_text}"

    # 1. state_manager notification (poll)
    sm.add_notification(tagged, source=from_agent)

    # 2. agent_messages (session hook Claude / archivage)
    frame_id = (
        "frm_" + hashlib.md5(f"{from_agent}{to_agent}{time.time()}".encode()).hexdigest()[:12]
    )
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_db_path import m2m_path   # scission M2M : suit l'interrupteur sandbox/m2m.switch
        db = Path(m2m_path())
        conn = sqlite3.connect(str(db), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT OR IGNORE INTO agent_messages"
            "(id,from_agent,to_agent,correlation_id,method,payload,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (
                frame_id,
                from_agent,
                to_agent,
                frame_id,
                "agent_notify.tool",
                msg_text,
                "unread",
                time.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[agent_notify] warn agent_messages: {e}", file=sys.stderr)

    print(f"[agent_notify] OK {from_agent} -> {to_agent} ({payload.get('type', 'msg')})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="Destinataire: claude|gemini|cline|daemon")
    ap.add_argument("--from", dest="sender", default="claude")
    ap.add_argument("--msg", help="Message libre")
    ap.add_argument("--task", help="Titre tache unique")
    ap.add_argument("--desc", default="", help="Description tache")
    ap.add_argument("--priority", type=int, default=3)
    ap.add_argument("--id", default=None)
    ap.add_argument("--tasks", help="Fichier JSON liste de taches [{id,priority,title,desc}]")
    args = ap.parse_args()

    to_agent = resolve_agent(args.to)
    base = {"from": args.sender, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}

    if args.tasks:
        tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
        send(to_agent, {**base, "type": "task_batch", "tasks": tasks}, args.sender)
    elif args.task:
        import uuid

        tid = args.id or f"wj_{args.sender[:2]}_{uuid.uuid4().hex[:8]}"
        send(
            to_agent,
            {
                **base,
                "type": "task_batch",
                "tasks": [
                    {
                        "id": tid,
                        "priority": args.priority,
                        "title": args.task,
                        "desc": args.desc,
                    }
                ],
            },
            args.sender,
        )
    elif args.msg:
        send(to_agent, {**base, "type": "message", "text": args.msg}, args.sender)
    else:
        ap.error("--msg | --task | --tasks requis")


if __name__ == "__main__":
    main()
