import datetime
import os
import sqlite3
import time

DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")
LOG = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "sandbox" / "rotation_snapshots.log")


def log(msg):
    ts = datetime.datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


log("=== ROTATION DEMARRAGE ===")
conn = sqlite3.connect(DB, timeout=300)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
conn.execute("PRAGMA cache_size=-64000")  # 64MB cache

before = conn.execute("SELECT COUNT(*) FROM rag_snapshots").fetchone()[0]
log(f"Avant: {before} rows")

# 1. Purge orphelins DELETE (chunk supprime = snapshot inutile)
t0 = time.time()
conn.execute("""
    DELETE FROM rag_snapshots 
    WHERE op = 'delete'
    AND chunk_id NOT IN (SELECT id FROM rag_chunks)
""")
n1 = conn.total_changes
conn.commit()
log(f"[1] Orphelins DELETE purges: {n1} ({time.time() - t0:.1f}s)")

# 2. Garder max 3 UPDATE par chunk, supprimer les anciens
t0 = time.time()
conn.execute("""
    DELETE FROM rag_snapshots
    WHERE op = 'update'
    AND snap_id NOT IN (
        SELECT snap_id FROM (
            SELECT snap_id,
                   ROW_NUMBER() OVER (PARTITION BY chunk_id ORDER BY snap_id DESC) as rn
            FROM rag_snapshots WHERE op = 'update'
        ) x WHERE rn <= 3
    )
""")
n2 = conn.total_changes
conn.commit()
log(f"[2] UPDATE anciens purges: {n2} ({time.time() - t0:.1f}s)")

# 3. Purge snapshot/update > 90 jours (sauf anchors)
t0 = time.time()
cutoff = (datetime.datetime.now() - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
conn.execute(f"""
    DELETE FROM rag_snapshots
    WHERE op IN ('snapshot','update')
    AND SUBSTR(timecode,1,10) < '{cutoff}'
""")
n3 = conn.total_changes
conn.commit()
log(f"[3] >90j purges (cutoff={cutoff}): {n3} ({time.time() - t0:.1f}s)")

after = conn.execute("SELECT COUNT(*) FROM rag_snapshots").fetchone()[0]
ops = dict(conn.execute("SELECT op, COUNT(*) FROM rag_snapshots GROUP BY op").fetchall())
log(f"Apres purge: {after} rows | {before - after} supprimes")
log(f"Ops restants: {ops}")

conn.execute("PRAGMA synchronous=FULL")
conn.commit()
conn.close()

# VACUUM
log("VACUUM en cours...")
t0 = time.time()
conn2 = sqlite3.connect(DB, timeout=600)
conn2.execute("VACUUM")
conn2.close()
db_mb = os.path.getsize(DB) // 1024 // 1024
log(f"VACUUM done {time.time() - t0:.1f}s — DB: {db_mb}MB")
log("=== ROTATION TERMINEE ===")
