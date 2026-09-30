import sqlite3

conn = sqlite3.connect(__import__("os").path.expanduser("~/Script python IA/LaForge/RAG/embeddings.db"))
n = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
print(f"chunks: {n}")
