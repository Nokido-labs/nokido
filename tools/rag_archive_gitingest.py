"""Archive chunks domain='gitingest*' dans rag_chunks_cold_storage.

Conservation totale (pas DELETE). Permet :
- restaurer si besoin futur
- garder source pour grep/AST search direct (pas RAG)
- alleger FAISS / future backfill

CRITERE : domain LIKE 'gitingest%' AND embedding IS NULL
(les gitingests deja embeddes Modal restent dans rag_chunks principale)
"""

import sqlite3

DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # Create cold_storage table (clone schema)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS rag_chunks_cold_storage AS
    SELECT * FROM rag_chunks WHERE 0
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cold_storage_id ON rag_chunks_cold_storage(id)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_cold_storage_domain ON rag_chunks_cold_storage(domain)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_cold_storage_source ON rag_chunks_cold_storage(source)"
    )
    print("[init] table rag_chunks_cold_storage ready")

    # Count targets
    n_target = cur.execute("""
    SELECT COUNT(*) FROM rag_chunks
    WHERE embedding IS NULL AND domain LIKE 'gitingest%'
    """).fetchone()[0]
    print(f"[targets] {n_target:,} chunks gitingest NULL to archive")

    # Move
    cur.execute("""
    INSERT INTO rag_chunks_cold_storage
    SELECT * FROM rag_chunks
    WHERE embedding IS NULL AND domain LIKE 'gitingest%'
    """)
    n_archived = cur.execute("SELECT COUNT(*) FROM rag_chunks_cold_storage").fetchone()[0]
    print(f"[archived] {n_archived:,} rows in cold_storage")

    cur.execute("""
    DELETE FROM rag_chunks
    WHERE embedding IS NULL AND domain LIKE 'gitingest%'
    """)
    print(f"[delete] {cur.rowcount:,} rows removed from rag_chunks main")

    con.commit()

    # Stats post
    print("\n[post-archive rag_chunks domain distribution NULL]")
    for r in cur.execute(
        "SELECT COALESCE(domain,'NULL'), COUNT(*) FROM rag_chunks WHERE embedding IS NULL GROUP BY domain ORDER BY 2 DESC LIMIT 15"
    ).fetchall():
        print(f"  {r[1]:7,}  {r[0]}")

    n_null_remaining = cur.execute(
        "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL"
    ).fetchone()[0]
    total_remaining = cur.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
    print(f"\n[NULL restant rag_chunks] {n_null_remaining:,} / {total_remaining:,}")

    # Token estimation pour reste
    avg_chars = (
        cur.execute("SELECT AVG(length(text)) FROM rag_chunks WHERE embedding IS NULL").fetchone()[
            0
        ]
        or 0
    )
    est_tok = (n_null_remaining * avg_chars) / 4  # ~4 chars per token rough
    print(f"[est tokens reste a embed] {est_tok:,.0f} (avg {avg_chars:.0f} chars/chunk)")

    con.close()


if __name__ == "__main__":
    main()
