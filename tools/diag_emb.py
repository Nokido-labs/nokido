import sqlite3

# Chemin DERIVE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
c = sqlite3.connect(str(__import__("pathlib").Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"))
t = c.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
we = c.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL").fetchone()[0]
print(f"total={t} with_emb={we} pct={round(100 * we / t, 1)}%")
