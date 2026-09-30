import datetime
import os
import sqlite3

DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")
LOG = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "sandbox" / "purge_delete_snaps.log")


def log(msg):
    ts = datetime.datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


log("=== PURGE DELETE ORPHELINS ===")
conn = sqlite3.connect(DB, timeout=600)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
conn.execute("PRAGMA cache_size=-256000")

total_del = 0
batch = 0
while True:
    # Récupérer 10000 snap_id d'orphelins
    rows = conn.execute("""
        SELECT s.snap_id FROM rag_snapshots s
        WHERE s.op = 'delete'
        AND NOT EXISTS (SELECT 1 FROM rag_chunks r WHERE r.id = s.chunk_id)
        LIMIT 10000
    """).fetchall()
    if not rows:
        break
    ids = [r[0] for r in rows]
    ph = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM rag_snapshots WHERE snap_id IN ({ph})", ids)
    conn.commit()
    total_del += len(ids)
    batch += 1
    if batch % 10 == 0:
        remaining = conn.execute("SELECT COUNT(*) FROM rag_snapshots WHERE op='delete'").fetchone()[
            0
        ]
        log(f"Batch {batch}: {total_del} supprimes | delete restants: {remaining}")

n_final = conn.execute("SELECT COUNT(*) FROM rag_snapshots").fetchone()[0]
ops = dict(conn.execute("SELECT op, COUNT(*) FROM rag_snapshots GROUP BY op").fetchall())
log(f"Purge terminee: {total_del} supprimes | total: {n_final} | ops: {ops}")
conn.execute("PRAGMA synchronous=FULL")
conn.commit()

# VACUUM final
log("VACUUM final...")
conn.close()
conn2 = sqlite3.connect(DB, timeout=600)
conn2.execute("VACUUM")
conn2.close()
mb = os.path.getsize(DB) // 1024 // 1024
log(f"VACUUM done — DB: {mb}MB")
log("=== FIN ===")
