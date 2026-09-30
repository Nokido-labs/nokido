"""forge_retier_corpus.py — Aligne le tier vectoriel sur la politique d'origin.

Met embedding=NULL pour tout chunk vectorise dont l'`origin` (cf. forge_tier_policy)
n'est PAS un tier chaud -> sort du vectoriel l'externe (libs, docs, PRs, sorties
d'outils, datasets, cold-legacy). Ces chunks restent cherchables via FTS.

Idempotent : a re-lancer pour faire respecter la politique apres toute derive.

Run     : run action=trusted_script path=tools/forge_retier_corpus.py
Dry-run : ... forge_retier_corpus.py script_args="--dry-run"
"""

import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nokido_agent.tools.forge_tier_policy import HOT_ORIGINS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
DRY = "--dry-run" in sys.argv
# Chunk vectorise dont l'origin n'est pas hot -> a sortir du vectoriel.
WHERE = "embedding IS NOT NULL AND origin NOT IN (" + ", ".join(f"'{o}'" for o in HOT_ORIGINS) + ")"


def main() -> None:
    if not DB.exists():
        raise SystemExit(f"[retier] DB introuvable: {DB}")
    con = sqlite3.connect(str(DB), timeout=60)
    con.execute("PRAGMA busy_timeout=30000")
    q = con.execute

    try:
        q("SELECT origin FROM rag_chunks LIMIT 1")
    except sqlite3.OperationalError:
        raise SystemExit("[retier] colonne origin absente -- lancer forge_migrate_origin.py")

    emb_before = q("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL").fetchone()[0]
    n_ext = q(f"SELECT COUNT(*) FROM rag_chunks WHERE {WHERE}").fetchone()[0]
    print(f"[retier] tier vectoriel actuel : {emb_before:,}")
    print(f"[retier] hors-politique (origin froid) a sortir : {n_ext:,}")
    print(f"[retier] resteront embeddes : {emb_before - n_ext:,} (tier chaud)")

    if DRY:
        print("[retier] --dry-run : aucune ecriture")
        con.close()
        return
    if n_ext == 0:
        print("[retier] deja aligne — rien a faire")
        con.close()
        return

    # Retire le trigger snapshot pour l'UPDATE de masse, recree apres.
    trg = q(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='auto_snapshot_before_update'"
    ).fetchone()
    t0 = time.time()
    try:
        if trg and trg[0]:
            con.execute("DROP TRIGGER auto_snapshot_before_update")
        cur = q(f"UPDATE rag_chunks SET embedding=NULL WHERE {WHERE}")
        con.commit()
    finally:
        if trg and trg[0]:
            con.execute(trg[0])
            con.commit()
            print("[retier] trigger auto_snapshot_before_update recree")

    emb_after = q("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL").fetchone()[0]
    con.close()
    print(f"[retier] embedding=NULL sur {cur.rowcount:,} chunks en {time.time() - t0:.1f}s")
    print(f"[retier] tier vectoriel : {emb_before:,} -> {emb_after:,}")


if __name__ == "__main__":
    main()
