#!/usr/bin/env python3
"""Check gemini inbox by rowid (insertion order) to avoid UTC/local timestamp issue."""

import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nokido_agent.app.forge_db_path import m2m_path   # scission M2M : suit l'interrupteur sandbox/m2m.switch
DB = Path(m2m_path())
c = sqlite3.connect(str(DB))

print("=== agt_gemini unread, by rowid DESC (insertion order) ===")
rows = c.execute(
    "SELECT rowid, id, from_agent, status, created_at, substr(payload,1,100) "
    "FROM agent_messages WHERE to_agent='agt_gemini' AND status='unread' "
    "ORDER BY rowid DESC LIMIT 10"
).fetchall()
for r in rows:
    print(f"  rowid={r[0]} [{r[4]}] {r[2]} status={r[3]}")
    print(f"    {r[5]}")

print("\n=== agt_gemini ALL (any status), rowid DESC, last 10 ===")
rows2 = c.execute(
    "SELECT rowid, from_agent, to_agent, status, created_at, substr(payload,1,80) "
    "FROM agent_messages WHERE to_agent='agt_gemini' "
    "ORDER BY rowid DESC LIMIT 10"
).fetchall()
for r in rows2:
    print(f"  rowid={r[0]} [{r[4]}] {r[1]}->{r[2]} status={r[3]} | {r[5]}")
