#!/usr/bin/env python
"""send_agent_task.py — Envoie une tâche dans agent_messages.
Usage: python send_agent_task.py <to_agent> <prompt>
Ex:    python send_agent_task.py agt_ollama "Résume en 3 points le rôle de Nokido"
"""

import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nokido_agent.app.forge_db_path import m2m_path   # scission M2M : suit l'interrupteur sandbox/m2m.switch
DB_PATH = Path(m2m_path())


def send(to_agent: str, prompt: str, from_agent: str = "agt_claude") -> str:
    msg_id = hashlib.sha256(f"{from_agent}{to_agent}{time.time()}".encode()).hexdigest()[:16]
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "INSERT INTO agent_messages "
        "(id, from_agent, to_agent, correlation_id, method, payload, status, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            msg_id,
            from_agent,
            to_agent,
            f"test_{int(time.time())}",
            "task.ask",
            json.dumps({"prompt": prompt}, ensure_ascii=False),
            "unread",
            now,
        ),
    )
    conn.commit()
    conn.close()
    print(f"[send] {from_agent} -> {to_agent} id={msg_id} prompt={prompt[:60]}")
    return msg_id


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    send(sys.argv[1], " ".join(sys.argv[2:]))
