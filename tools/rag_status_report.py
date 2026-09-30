#!/usr/bin/env python3
"""Rapport état RAG + gitingest + tâches pendantes."""

import sqlite3
from pathlib import Path

DB = Path("RAG/embeddings.db")
conn = sqlite3.connect(str(DB))

# Total chunks
total = conn.execute("SELECT count(*) FROM rag_chunks").fetchone()[0]
print(f"RAG total chunks: {total}")

# Chunks par source_type (gitingest = python_source/markdown depuis data/gitingest)
by_type = conn.execute("""
    SELECT json_extract(meta,'$.source_type') as st, count(*) as n
    FROM rag_chunks
    GROUP BY st ORDER BY n DESC LIMIT 10
""").fetchall()
print("\nPar source_type:")
for r in by_type:
    print(f"  {r[0]}: {r[1]}")

# Chunks gitingest spécifiquement (source contient gitingest)
gitingest = conn.execute("""
    SELECT count(*) FROM rag_chunks WHERE source LIKE '%gitingest%'
""").fetchone()[0]
print(f"\nChunks source gitingest: {gitingest}")

# Repos gitingest indexés (sources distinctes)
repos = conn.execute("""
    SELECT DISTINCT substr(source, 1, 80) FROM rag_chunks
    WHERE source LIKE '%gitingest%' LIMIT 20
""").fetchall()
print(f"Repos gitingest distincts: {len(repos)}")
for r in repos:
    print(f"  {r[0]}")

# Fichiers .rag_indexed dans data/gitingest
gi_dir = Path("data/gitingest")
indexed = list(gi_dir.glob("*.rag_indexed")) if gi_dir.exists() else []
processed = list(gi_dir.glob("*.processed")) if gi_dir.exists() else []
txt_files = list(gi_dir.glob("*.txt")) if gi_dir.exists() else []
print(
    f"\ndata/gitingest: {len(txt_files)} .txt | {len(processed)} .processed | {len(indexed)} .rag_indexed"
)

# Watch jobs status
wj = conn.execute("""
    SELECT status, count(*) FROM watch_jobs GROUP BY status
""").fetchall()
print("\nwatch_jobs:")
for r in wj:
    print(f"  {r[0]}: {r[1]}")

# Chain nodes status
cn = conn.execute("""
    SELECT status, count(*) FROM agent_chain_nodes GROUP BY status
""").fetchall()
print("\nagent_chain_nodes:")
for r in cn:
    print(f"  {r[0]}: {r[1]}")

# Messages non lus pour Claude
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nokido_agent.app.forge_db_path import m2m_path  # noqa: E402  # scission M2M : agent_messages a sa base
_m2m = sqlite3.connect(m2m_path())
unread = _m2m.execute("""
    SELECT count(*) FROM agent_messages
    WHERE to_agent='agt_claude' AND status='unread'
""").fetchone()[0]
_m2m.close()
print(f"\nagent_messages non lus (claude): {unread}")

conn.close()
