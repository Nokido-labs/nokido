"""Migration : ADD COLUMN embedding_model + tag existing chunks BGE-M3.

Tous les chunks avec embedding NOT NULL ont ete generes par BGE-M3 (Modal A10G
+ historique brain_worker). Setting embedding_model='bge-m3' pour eviter
mixing latent spaces sur futurs INSERTs.
"""

import sqlite3

DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    cols = [r[1] for r in cur.execute("PRAGMA table_info(rag_chunks)").fetchall()]
    if "embedding_model" in cols:
        print("[skip] embedding_model column already exists")
    else:
        cur.execute("ALTER TABLE rag_chunks ADD COLUMN embedding_model TEXT DEFAULT NULL")
        print("[add] embedding_model column added")

    # Tag existing
    n_set = cur.execute(
        "UPDATE rag_chunks SET embedding_model='bge-m3' "
        "WHERE embedding IS NOT NULL AND (embedding_model IS NULL OR embedding_model='')"
    ).rowcount
    print(f"[tag] {n_set} existing chunks tagged 'bge-m3'")

    con.commit()

    # Stats
    print("\n[stats embedding_model distribution]")
    for r in cur.execute(
        "SELECT COALESCE(embedding_model,'NULL'), COUNT(*) FROM rag_chunks GROUP BY embedding_model"
    ).fetchall():
        print(f"  {r[0]:15} {r[1]:,}")
    con.close()


if __name__ == "__main__":
    main()
