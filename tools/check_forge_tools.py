#!/usr/bin/env python3
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
c = sqlite3.connect(str(DB))

print("=== ALL forge_tools (tool_name, min_ring, is_active) ===")
rows = c.execute(
    "SELECT tool_name, min_ring, is_active, category FROM forge_tools ORDER BY min_ring, tool_name"
).fetchall()
for r in rows:
    print(f"  {r[0]:20s} min_ring={r[1]} active={r[2]} cat={r[3]}")

print("\n=== Tools blocking ring=3 agents (min_ring < 3) ===")
rows2 = c.execute(
    "SELECT tool_name, min_ring FROM forge_tools WHERE min_ring < 3 AND is_active=1"
).fetchall()
for r in rows2:
    print(f"  BLOCKED for Gemini: {r[0]} (min_ring={r[1]})")
