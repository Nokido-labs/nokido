#!/usr/bin/env python3
import json
import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nokido_agent.app.forge_db_path import m2m_path   # scission M2M : chemin absolu (plus relatif au cwd), suit l'interrupteur
DB = Path(m2m_path())
conn = sqlite3.connect(str(DB))
rows = conn.execute(
    "SELECT id, from_agent, created_at, substr(payload,1,1000) FROM agent_messages "
    "WHERE to_agent='agt_claude' AND from_agent='agt_gemini' ORDER BY rowid DESC LIMIT 5"
).fetchall()
for r in rows:
    print(f"--- [{r[2]}] FROM {r[1]} id={r[0]} ---")
    try:
        print(json.dumps(json.loads(r[3]), indent=2, ensure_ascii=False)[:800])
    except Exception:
        print(r[3])
    print()
conn.close()
