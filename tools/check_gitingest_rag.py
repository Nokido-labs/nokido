#!/usr/bin/env python3
"""Deep check: what's actually in RAG vs what should be from gitingest."""

import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
c = sqlite3.connect(str(DB))

total = c.execute("SELECT count(*) FROM rag_chunks").fetchone()[0]
print(f"Total chunks: {total}")

# Check sources containing gitingest file names
print("\n=== Sources matching gitingest filenames ===")
files = [
    "rank-bm25",
    "sentence-transformers",
    "faiss",
    "pydantic",
    "httpx",
    "pyzmq",
    "aiohttp",
    "ruff",
    "gitpython",
    "networkx",
]
for f in files:
    n = c.execute("SELECT count(*) FROM rag_chunks WHERE source LIKE ?", (f"%{f}%",)).fetchone()[0]
    if n > 0:
        rows = c.execute(
            "SELECT DISTINCT source FROM rag_chunks WHERE source LIKE ? LIMIT 2", (f"%{f}%",)
        ).fetchall()
        print(f"  {f}: {n} chunks — {[r[0] for r in rows]}")
    else:
        print(f"  {f}: NOT IN RAG")

# Check data/gitingest/ path pattern
print("\n=== Sources with 'gitingest' in path ===")
rows = c.execute(
    "SELECT DISTINCT source FROM rag_chunks WHERE source LIKE '%gitingest%' LIMIT 20"
).fetchall()
if rows:
    for r in rows:
        print(f"  {r[0]}")
else:
    print("  NONE")

# Check what the bulk of 123K chunks actually is
print("\n=== Top 10 source prefixes (by chunk count) ===")
rows = c.execute("""
    SELECT substr(source,1,40) prefix, count(*) n
    FROM rag_chunks
    GROUP BY substr(source,1,40)
    ORDER BY n DESC LIMIT 10
""").fetchall()
for r in rows:
    print(f"  [{r[1]:6d}] {r[0]}")

c.close()
