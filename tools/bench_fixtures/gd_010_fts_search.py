import sqlite3

conn = sqlite3.connect(__import__("os").path.expanduser("~/Script python IA/LaForge/RAG/embeddings.db"))
rows = conn.execute("SELECT source FROM rag_fts WHERE rag_fts MATCH 'CostNet' LIMIT 3").fetchall()
print(f"fts_hits: {len(rows)}")
