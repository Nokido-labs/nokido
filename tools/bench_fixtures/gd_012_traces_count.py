import sqlite3

conn = sqlite3.connect(__import__("os").path.expanduser("~/Script python IA/LaForge/RAG/execution_traces.db"))
n = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
print(f"traces: {n}")
