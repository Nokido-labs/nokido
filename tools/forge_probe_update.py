# -*- coding: utf-8 -*-
"""Probe RCA writes fantomes (2026-07-06) : dans l'env exact du drain
(py314 + run_job offline), un UPDATE rag_chunks matche-t-il ?
SELECT 1 id -> UPDATE marqueur -> rowcount -> readback (meme conn + conn neuve)
-> revert. Aucune donnee sensible affichee (ids de chunks seulement)."""

__FORGE_COLOR__ = "observabilite/probe : sonde RCA des ecritures fantomes (2026-07-06)"  # organe declare le 2026-09-06 (audit de raccordement)
import sqlite3
import sys

DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")
print("python:", sys.version, flush=True)
print("sqlite:", sqlite3.sqlite_version, flush=True)

conn = sqlite3.connect(DB, timeout=60)
conn.execute("PRAGMA journal_mode=WAL")
print("database_list:", conn.execute("PRAGMA database_list").fetchall(), flush=True)

row = conn.execute(
    "SELECT id FROM rag_chunks WHERE embedding IS NULL AND embedding_model IS NULL "
    "AND text IS NOT NULL AND length(text) > 50 LIMIT 1"
).fetchone()
print("selected id:", repr(row[0]) if row else None, flush=True)

cur = conn.execute("UPDATE rag_chunks SET embedding_model='PROBE_X' WHERE id=?", (row[0],))
print("update rowcount:", cur.rowcount, flush=True)
conn.commit()

back = conn.execute("SELECT embedding_model FROM rag_chunks WHERE id=?", (row[0],)).fetchone()
print("readback same conn:", back, flush=True)

c2 = sqlite3.connect(DB, timeout=30)
back2 = c2.execute("SELECT embedding_model FROM rag_chunks WHERE id=?", (row[0],)).fetchone()
print("readback fresh conn:", back2, flush=True)
c2.close()

conn.execute("UPDATE rag_chunks SET embedding_model=NULL WHERE id=? AND embedding_model='PROBE_X'", (row[0],))
conn.commit()
conn.close()
print("PROBE DONE", flush=True)
