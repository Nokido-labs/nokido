#!/usr/bin/env python3
"""tools/gemini_notify.py — Envoyer taches/messages a agt_gemini via state_manager.

Usage:
  python gemini_notify.py --msg "texte libre"
  python gemini_notify.py --tasks tasks.json
  python gemini_notify.py --task "titre" --desc "description" --priority 2

tasks.json format:
  [{"id":"wj_x","priority":1,"title":"...","desc":"..."}]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_state_manager import get_state_manager


def send(payload: dict, from_agent: str = "claude") -> None:
    import hashlib
    import sqlite3

    msg_text = json.dumps(payload, ensure_ascii=False)
    sm = get_state_manager()
    # 1. pending_notifications (hub poll)
    sm.add_notification(f"[GEMINI] {msg_text}", source=from_agent)
    # 2. agent_messages (Gemini SQL direct + session hook)
    frame_id = (
        "frm_" + hashlib.md5(f"{from_agent}agt_gemini{time.time()}".encode()).hexdigest()[:12]
    )
    try:
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
                "agt_gemini",
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
        print(f"[gemini_notify] warn agent_messages: {e}", file=sys.stderr)
    print(f"[gemini_notify] OK — {payload.get('type', 'msg')} -> agt_gemini ({frame_id})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--msg", help="Message libre")
    ap.add_argument("--task", help="Titre d une tache unique")
    ap.add_argument("--desc", help="Description de la tache")
    ap.add_argument("--priority", type=int, default=3)
    ap.add_argument("--id", default=None)
    ap.add_argument("--tasks", help="Fichier JSON liste de taches")
    ap.add_argument("--from", dest="sender", default="claude")
    args = ap.parse_args()

    base = {"from": args.sender, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}

    if args.tasks:
        tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
        send(
            tasks if isinstance(tasks, dict) else {**base, "type": "task_batch", "tasks": tasks},
            args.sender,
        )

    elif args.task:
        import uuid

        tid = args.id or f"wj_{args.sender[:2]}_{uuid.uuid4().hex[:8]}"
        send(
            {
                **base,
                "type": "task_batch",
                "tasks": [
                    {
                        "id": tid,
                        "priority": args.priority,
                        "title": args.task,
                        "desc": args.desc or "",
                    }
                ],
            },
            args.sender,
        )

    elif args.msg:
        send({**base, "type": "message", "text": args.msg}, args.sender)

    else:
        ap.error("--msg | --task | --tasks requis")


if __name__ == "__main__":
    main()
