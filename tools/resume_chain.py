#!/usr/bin/env python3
"""tools/resume_chain.py — Resume chain nodes by chain_id. Resets failed→pending then executes."""

__FORGE_COLOR__ = "locomoteur/orchestr : reprend les chain_nodes d'une chain_id"  # organe declare le 2026-09-06 (audit de raccordement)

import asyncio
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_chain_executor import DB, ChainExecutor

chain_id = sys.argv[1] if len(sys.argv) > 1 else None

# Reset failed nodes to pending (retry)
conn = sqlite3.connect(str(DB), timeout=30)
conn.execute("PRAGMA journal_mode=WAL")
if chain_id:
    rows = conn.execute(
        "SELECT id, status, error FROM agent_chain_nodes WHERE chain_id=?", (chain_id,)
    ).fetchall()
    print(f"Chain {chain_id}: {len(rows)} nodes")
    for r in rows:
        print(f"  {r[0]} status={r[1]} err={str(r[2])[:80] if r[2] else ''}")
    n = conn.execute(
        "UPDATE agent_chain_nodes SET status='pending', error=NULL WHERE chain_id=? AND status='failed'",
        (chain_id,),
    ).rowcount
    print(f"Reset {n} failed→pending")
else:
    n = conn.execute(
        "UPDATE agent_chain_nodes SET status='pending', error=NULL WHERE status='failed'"
    ).rowcount
    print(f"Reset {n} failed→pending (all chains)")
conn.commit()
conn.close()

print("Running execute_pending()...")
asyncio.run(ChainExecutor().execute_pending())
print("Done.")
