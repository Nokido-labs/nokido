"""forge_db_merge_final.py — fusionne les 2 recoveries en UNE base finale complète.

Base = embeddings_recovered.db (Python row-copy : superset de ~50 tables — cold_storage,
snapshots 2.07M, graph_edges, network_log, agent_messages, configs… — MAIS rag_chunks=0).
Overlay depuis embeddings_gold.db (sqlite3 .recover) : rag_chunks (158312, le set live
irremplaçable) + l'index FTS own-content rag_fts (550k docs) que Python n'a pas pu lire.
Puis rebuild de rag_chunks_fts (external-content sur rag_chunks). Triggers off pendant
le bulk, recréés après. Résultat = C:\\tmp\\embeddings_final.db (TOUT préservé)."""
import sqlite3
import time
import shutil
import os

REC = r"%NOKIDO_DATA%\embeddings_recovered.db"
GOLD = r"C:\tmp\embeddings_gold.db"
FINAL = r"C:\tmp\embeddings_final.db"

t0 = time.time()
print("copie base recovered -> final ...", flush=True)
if os.path.exists(FINAL):
    os.remove(FINAL)
shutil.copyfile(REC, FINAL)
print(f"  copiee ({round(time.time()-t0)}s, {round(os.path.getsize(FINAL)/1e9,2)}GB)", flush=True)

d = sqlite3.connect(FINAL, timeout=600)
d.execute("PRAGMA journal_mode=OFF")
d.execute("PRAGMA synchronous=OFF")
d.execute("PRAGMA foreign_keys=OFF")

# colonnes STORED (non-generees) de rag_chunks : table_xinfo hidden==0
xinfo = d.execute("PRAGMA table_xinfo(rag_chunks)").fetchall()
stored = [r[1] for r in xinfo if r[6] == 0]
print("rag_chunks stored cols:", stored, flush=True)

# drop triggers (sync FTS) pendant le bulk insert
trigs = [
    (r[0], r[1])
    for r in d.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL"
    ).fetchall()
]
for n, _ in trigs:
    d.execute(f'DROP TRIGGER IF EXISTS "{n}"')
print(f"dropped {len(trigs)} triggers", flush=True)

d.execute("ATTACH ? AS g", (GOLD,))

# --- rag_chunks depuis gold ---
# meta JSON parfois invalide (rows .recover) -> colonne generee folder/lang
# (json_extract) indexee echoue a l'INSERT. Sanitize : json_valid sinon '{}'.
bad_meta = d.execute(
    "SELECT COUNT(*) FROM g.rag_chunks WHERE meta IS NOT NULL AND NOT json_valid(meta)"
).fetchone()[0]
print(f"rows meta JSON invalide (reset -> {{}}): {bad_meta}", flush=True)
d.execute("DELETE FROM rag_chunks")
col = ",".join(f'"{c}"' for c in stored)
sel = ",".join(
    "CASE WHEN meta IS NULL OR json_valid(meta) THEN meta ELSE '{}' END"
    if c == "meta"
    else f'"{c}"'
    for c in stored
)
d.execute(f"INSERT INTO rag_chunks ({col}) SELECT {sel} FROM g.rag_chunks")
d.commit()
n = d.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
print(f"rag_chunks merged = {n} ({round(time.time()-t0)}s)", flush=True)

# --- index FTS own-content rag_fts : copier les shadow tables depuis gold ---
for sh in ("rag_fts_content", "rag_fts_data", "rag_fts_idx", "rag_fts_docsize", "rag_fts_config"):
    try:
        d.execute(f'DELETE FROM "{sh}"')
        d.execute(f'INSERT INTO "{sh}" SELECT * FROM g."{sh}"')
        cnt = d.execute(f'SELECT COUNT(*) FROM "{sh}"').fetchone()[0]
        print(f"  {sh} = {cnt}", flush=True)
    except Exception as e:
        print(f"  {sh} ERR {str(e)[:70]}", flush=True)
d.commit()
d.execute("DETACH g")

# --- rebuild external-content FTS rag_chunks_fts (indexe rag_chunks) ---
try:
    d.execute("INSERT INTO rag_chunks_fts(rag_chunks_fts) VALUES('rebuild')")
    print("  rag_chunks_fts rebuilt", flush=True)
except Exception as e:
    print(f"  rag_chunks_fts rebuild ERR {str(e)[:90]}", flush=True)
d.commit()

# --- recreer triggers ---
for nm, sql in trigs:
    try:
        d.execute(sql)
    except Exception as e:
        print(f"  trig {nm} ERR {str(e)[:60]}", flush=True)
d.commit()

# --- verif ---
for t in (
    "rag_chunks",
    "rag_chunks_cold_storage",
    "rag_snapshots",
    "rag_graph_edges",
    "network_log",
    "agent_messages",
    "rag_fts_content",
    "rag_chunks_fts",
):
    try:
        print(f"final {t} = {d.execute(f'SELECT COUNT(*) FROM \"{t}\"').fetchone()[0]}", flush=True)
    except Exception as e:
        print(f"final {t} ERR {str(e)[:50]}", flush=True)
print("integrity:", d.execute("PRAGMA integrity_check(5)").fetchall(), flush=True)
d.close()
print(
    f"MERGE DONE total {round(time.time()-t0)}s size={round(os.path.getsize(FINAL)/1e9,2)}GB",
    flush=True,
)
