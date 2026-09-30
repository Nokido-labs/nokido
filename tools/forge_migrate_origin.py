"""forge_migrate_origin.py — Migration : ajoute la colonne `origin` a rag_chunks.

Fix structurel RAG. Ajoute `origin` comme colonne GENEREE VIRTUELLE = ORIGIN_EXPR
de forge_tier_policy (provenance derivee de source+domain). Zero maintenance,
toujours coherente, queryable, indexee. Idempotent.

Run : run action=trusted_script path=tools/forge_migrate_origin.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nokido_agent.tools.forge_tier_policy import ORIGIN_EXPR  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


def main() -> None:
    if not DB.exists():
        raise SystemExit(f"[migrate] DB introuvable: {DB}")
    con = sqlite3.connect(str(DB), timeout=60)
    con.execute("PRAGMA busy_timeout=30000")

    # PRAGMA table_info ne liste PAS les colonnes generees -> test par SELECT.
    try:
        con.execute("SELECT origin FROM rag_chunks LIMIT 1")
        print("[migrate] colonne origin deja presente")
    except sqlite3.OperationalError:
        con.execute(
            f"ALTER TABLE rag_chunks ADD COLUMN origin TEXT "
            f"GENERATED ALWAYS AS ({ORIGIN_EXPR}) VIRTUAL"
        )
        con.commit()
        print("[migrate] colonne origin (generee virtuelle) ajoutee")

    con.execute("CREATE INDEX IF NOT EXISTS idx_rag_origin ON rag_chunks(origin)")
    con.commit()
    print("[migrate] index idx_rag_origin OK")

    print("[migrate] repartition par origin :")
    for o, n, e in con.execute(
        "SELECT origin, COUNT(*) c, "
        "SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) e "
        "FROM rag_chunks GROUP BY origin ORDER BY c DESC"
    ):
        print(f"  {o:<16} total={n:<8,} vectorise={e or 0:,}")
    con.close()


if __name__ == "__main__":
    main()
