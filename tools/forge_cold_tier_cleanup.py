"""
forge_cold_tier_cleanup.py — Suppression du vrai dechet du RAG.
=================================================================
Etape 2 du plan two-tier RAG (etape 1 = blocklist COLD_DOMAINS dans
forge_rebuild_local.py).

Supprime definitivement les chunks du repo repo_hermes_agent (NO-GO confirme,
~46k chunks, doublon instable) de RAG/embeddings.db :
  1. Backup compact des lignes dans sandbox/hermes_backup_<date>.db (table
     restaurable via INSERT ... SELECT).
  2. DELETE FROM rag_chunks — le trigger auto_snapshot_before_delete les
     snapshote en plus dans rag_snapshots (double filet de securite).
  3. Rebuild de l'index FTS5 external-content rag_chunks_fts (pas de triggers
     de sync : rebuild explicite obligatoire).
  4. Rapport d'integrite avant/apres.

Run       : __import__("os").path.expanduser("~/miniforge3/python.exe") tools/forge_cold_tier_cleanup.py
Dry-run   : ... tools/forge_cold_tier_cleanup.py --dry-run   (compte seul, 0 ecriture)
"""

import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
TARGET_DOMAIN = "repo_hermes_agent"
DRY = "--dry-run" in sys.argv


def main() -> None:
    if not DB.exists():
        print(f"[cleanup] DB introuvable: {DB}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB), timeout=60)
    conn.execute("PRAGMA busy_timeout=30000")
    q = conn.execute

    total_before = q("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
    n_target = q("SELECT COUNT(*) FROM rag_chunks WHERE domain=?", (TARGET_DOMAIN,)).fetchone()[0]
    print(f"[cleanup] rag_chunks total        : {total_before}")
    print(f"[cleanup] domain={TARGET_DOMAIN} : {n_target} a supprimer")

    if n_target == 0:
        print("[cleanup] rien a supprimer — STOP")
        conn.close()
        return

    if DRY:
        print("[cleanup] --dry-run : aucune ecriture effectuee")
        conn.close()
        return

    # --- 1. Backup compact dans un fichier SQLite separe ---
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / "sandbox" / f"hermes_backup_{stamp}.db"
    backup.parent.mkdir(exist_ok=True)
    q("ATTACH DATABASE ? AS bk", (str(backup),))
    q(
        "CREATE TABLE bk.rag_chunks_hermes AS SELECT * FROM rag_chunks WHERE domain=?",
        (TARGET_DOMAIN,),
    )
    n_bk = q("SELECT COUNT(*) FROM bk.rag_chunks_hermes").fetchone()[0]
    conn.commit()
    q("DETACH DATABASE bk")
    assert n_bk == n_target, f"backup incomplet {n_bk} != {n_target}"
    print(f"[cleanup] backup ecrit : {backup} ({n_bk} lignes)")

    # --- 2. DELETE (trigger auto_snapshot_before_delete snapshote aussi) ---
    t0 = time.time()
    cur = q("DELETE FROM rag_chunks WHERE domain=?", (TARGET_DOMAIN,))
    deleted = cur.rowcount
    conn.commit()
    print(f"[cleanup] DELETE rag_chunks : {deleted} lignes en {time.time() - t0:.1f}s")

    # --- 3. Rebuild FTS5 external-content (pas de triggers de sync) ---
    t0 = time.time()
    q("INSERT INTO rag_chunks_fts(rag_chunks_fts) VALUES('rebuild')")
    conn.commit()
    print(f"[cleanup] rag_chunks_fts rebuild OK en {time.time() - t0:.1f}s")

    # --- 4. Rapport integrite ---
    total_after = q("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
    fts_after = q("SELECT COUNT(*) FROM rag_chunks_fts").fetchone()[0]
    leftover = q("SELECT COUNT(*) FROM rag_chunks WHERE domain=?", (TARGET_DOMAIN,)).fetchone()[0]
    print(f"[cleanup] rag_chunks    : {total_before} -> {total_after}")
    print(f"[cleanup] rag_chunks_fts: {fts_after} (doit == {total_after})")
    print(f"[cleanup] residu {TARGET_DOMAIN} : {leftover} (doit == 0)")

    ok = total_after == total_before - n_target and fts_after == total_after and leftover == 0
    print(f"[cleanup] {'OK — coherent' if ok else 'ECHEC — incoherence detectee'}")
    conn.close()
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
