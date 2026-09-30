#!/usr/bin/env python3
"""Check recent agent_messages + hub notify routing for claude."""

import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nokido_agent.app.forge_db_path import m2m_path   # scission M2M : suit l'interrupteur sandbox/m2m.switch
DB = Path(m2m_path())
c = sqlite3.connect(str(DB))

# Check schema first
cols = [r[1] for r in c.execute("PRAGMA table_info(agent_messages)").fetchall()]
print("agent_messages columns:", cols)

# Recent messages involving claude or gemini
rows = c.execute("""
    SELECT * FROM agent_messages
    ORDER BY rowid DESC LIMIT 10
""").fetchall()
print("\nLast 10 messages:")
for r in rows:
    print(dict(zip(cols, r)))
    print()
