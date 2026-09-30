"""
snapshot_now.py — Snapshot RAG manuel
Utilise PRAGMA busy_timeout pour attendre que le MCP stdio libère.
Lance depuis terminal : python tools/snapshot_now.py
"""

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(str(__import__("pathlib").Path(__file__).resolve().parents[1]))
DB = ROOT / "RAG" / "embeddings.db"

print("Tentative snapshot avec busy_timeout=60s...")
for attempt in range(6):
    try:
        conn = sqlite3.connect(str(DB), timeout=60)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("""
            INSERT INTO rag_snapshots
            (timecode,session_id,agent_id,chunk_id,text,source,domain,meta,op,sequence_id)
            SELECT datetime('now'),'claude','CLAUDE',id,text,source,domain,meta,
                   'snapshot',COALESCE(sequence_id,0)
            FROM rag_chunks WHERE id IS NOT NULL
        """)
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM rag_snapshots").fetchone()[0]
        conn.close()
        print(f"OK — {n} snapshots au total")
        sys.exit(0)
    except sqlite3.OperationalError as e:
        print(f"  attempt {attempt + 1}/6: {e} — retry in 5s")
        time.sleep(5)

print("FAIL — DB toujours verrouillée après 6 tentatives")
print("Solution : ferme Claude, lance snapshot_now.py, rouvre Claude")
sys.exit(1)
