"""forge_db_recover_chunks.py v2 — rattrape rag_chunks. Fixe 2 bugs du v1 :
(1) triggers FTS bloquaient les INSERT bulk -> on les DROP pendant le chargement,
    rebuild FTS + recreate triggers après.
(2) bytes non-UTF-8 dans des colonnes TEXT (corruption) -> text_factory tolérant
    (decode utf-8 'replace') sur la source.
Full-scan séquentiel (SELECT *, pas rowid) car COUNT marchait. stdout utf-8."""
import sqlite3
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SRC = r"%NOKIDO_DATA%\embeddings.db"
DST = r"%NOKIDO_DATA%\embeddings_recovered.db"

s = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True, timeout=60)
s.text_factory = lambda b: b.decode("utf-8", "replace")  # tolère les bytes corrompus
d = sqlite3.connect(DST, timeout=120)
d.execute("PRAGMA journal_mode=OFF")
d.execute("PRAGMA synchronous=OFF")

# triggers source (pour les recréer après) + DROP sur dst (bloquent le bulk)
trigs = s.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL").fetchall()
for (n,) in [(r[0],) for r in d.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()]:
    try:
        d.execute(f'DROP TRIGGER IF EXISTS "{n}"')
    except Exception as e:
        print(f"drop trig {n}: {str(e)[:60]}", flush=True)
d.execute("DELETE FROM rag_chunks")  # repart propre (était ~0)
d.commit()

cols = [r[1] for r in d.execute("PRAGMA table_info(rag_chunks)")]
ins = f'INSERT OR IGNORE INTO rag_chunks VALUES ({",".join("?" * len(cols))})'
print(f"rag_chunks cols={len(cols)} triggers_dropped={len(trigs)} ; full-scan…", flush=True)

cur = s.execute("SELECT * FROM rag_chunks")
copied = bad = 0
t0 = time.time()
while True:
    try:
        rows = cur.fetchmany(1000)
    except Exception as e:
        print(f"scan stop @ copied={copied}: {repr(e)[:100]}", flush=True)
        break
    if not rows:
        break
    try:
        d.executemany(ins, rows)
        copied += len(rows)
    except Exception:
        for r in rows:
            try:
                d.execute(ins, r)
                copied += 1
            except Exception:
                bad += 1
    if copied and copied % 20000 < 1000:
        print(f"  {copied} ({round(time.time() - t0)}s)", flush=True)
d.commit()
print(f"rag_chunks copied={copied} bad={bad} ({round(time.time() - t0)}s)", flush=True)

for n in ("rag_chunks_fts", "rag_fts"):
    try:
        d.execute(f'INSERT INTO "{n}"("{n}") VALUES(\'rebuild\')')
        print(f"fts {n}: rebuilt", flush=True)
    except Exception as e:
        print(f"fts {n}: {str(e)[:80]}", flush=True)
for n, sql in trigs:
    try:
        d.execute(sql)
    except Exception as e:
        print(f"recreate trig {n}: {str(e)[:60]}", flush=True)
d.commit()

print("final rag_chunks:", d.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0], flush=True)
print("integrity:", d.execute("PRAGMA integrity_check(3)").fetchall(), flush=True)
s.close()
d.close()
print("CHUNKS RECOVERY v2 DONE", flush=True)
