"""forge_db_check.py — Checkpoint WAL + etat reel du tier vectoriel.

Diagnostic : connexion RW (voit le WAL), checkpoint TRUNCATE (fusionne WAL ->
DB principale), puis compte les embeddings par origin. Verite terrain.

Run : run action=trusted_script path=tools/forge_db_check.py
"""

import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"


def main() -> None:
    con = sqlite3.connect(str(DB), timeout=60)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        ck = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        print(f"wal_checkpoint(TRUNCATE) = {ck}  (busy, log_frames, checkpointed)")
    except sqlite3.OperationalError as e:
        print(f"checkpoint impossible: {e}")
    emb = con.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL").fetchone()[0]
    print(f"tier vectoriel : {emb:,}")
    for o, t, e in con.execute(
        "SELECT origin, COUNT(*), "
        "SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) "
        "FROM rag_chunks GROUP BY origin ORDER BY 3 DESC"
    ):
        print(f"  {o:<16} embed={e or 0:<8,} total={t:,}")
    con.close()


if __name__ == "__main__":
    main()
