"""forge_db_restore_chunks.py — rag_chunks INRÉCUPÉRABLE de la corrompue (SELECT *
malformé, arité incohérente). On restaure rag_chunks depuis le backup 09:44 (propre)
dans la base recovered (qui a déjà toutes les AUTRES tables salvagées du courant).
Perte = ré-embeddings du jour (re-faisables eco) + rtk + access_count. Savoir préservé."""
import sqlite3
import time

# Chemin DERIVE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
BK = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "backups" / "cold_storage"
         / "20260602_094440_PRE_MASTER_memory_consolidator__consolidation_knowledge" / "embeddings.db")
DST = r"%NOKIDO_DATA%\embeddings_recovered.db"

t0 = time.time()
b = sqlite3.connect(f"file:{BK}?mode=ro", uri=True, timeout=60)
print("backup rag_chunks:", b.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0], flush=True)
print("backup quick_check:", b.execute("PRAGMA quick_check(1)").fetchall(), flush=True)
bcols = [r[1] for r in b.execute("PRAGMA table_info(rag_chunks)")]
b.close()

d = sqlite3.connect(DST, timeout=120)
d.execute("PRAGMA journal_mode=OFF")
d.execute("PRAGMA synchronous=OFF")
dcols = [r[1] for r in d.execute("PRAGMA table_info(rag_chunks)")]
common = [c for c in dcols if c in bcols]
print(f"dst cols={len(dcols)} backup cols={len(bcols)} common={len(common)}", flush=True)

trigs = [(r[0], r[1]) for r in d.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL")]
for n, _ in trigs:
    d.execute(f'DROP TRIGGER IF EXISTS "{n}"')
d.execute("DELETE FROM rag_chunks")
d.commit()

d.execute("ATTACH ? AS bk", (BK,))
collist = ",".join(f'"{c}"' for c in common)
# existence-verifiee : la table vient d'etre VIDEE et ses triggers RETIRES juste
# au-dessus -- aucun id existant, aucun trigger rag_chunks_fts_bi a armer (2026-10-01).
d.execute(f"INSERT OR IGNORE INTO rag_chunks ({collist}) SELECT {collist} FROM bk.rag_chunks")
d.commit()
n = d.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
print(f"rag_chunks restored={n} ({round(time.time()-t0)}s)", flush=True)
d.execute("DETACH bk")

for fts in ("rag_chunks_fts", "rag_fts"):
    try:
        d.execute(f'INSERT INTO "{fts}"("{fts}") VALUES(\'rebuild\')')
        print(f"fts {fts}: rebuilt", flush=True)
    except Exception as e:
        print(f"fts {fts}: {str(e)[:80]}", flush=True)
for nm, sql in trigs:
    try:
        d.execute(sql)
    except Exception as e:
        print(f"trig {nm}: {str(e)[:60]}", flush=True)
d.commit()

print("final rag_chunks:", d.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0], flush=True)
print("final embedded:", d.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL").fetchone()[0], flush=True)
print("integrity:", d.execute("PRAGMA integrity_check(3)").fetchall(), flush=True)
d.close()
print("RESTORE DONE", flush=True)
