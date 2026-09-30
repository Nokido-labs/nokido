"""forge_db_postswap.py — finalisation post-restart du hub (V: deverrouillee).

A lancer APRES que le launcher a redemarre le stack (hub sur RAG/embeddings.db = good).
1. Verifie la DB live (RAG/embeddings.db) = la good (rag_chunks=158312, integrity).
2. Delta-check best-effort sur %NOKIDO_DATA%\\embeddings.db corrompue : si des tables ont grossi
   depuis le dump .recover (writes du hub orphelin), on FLAGGE (pas d'auto-merge).
3. Forensic : move %NOKIDO_DATA%\\embeddings.db(+wal/shm) -> C:\\LaForge_data\\embeddings_corrupt_*.
4. Cleanup V: : supprime mes temps recover.sql + embeddings_recovered.db (libere V:).
5. Cleanup C:\\tmp : supprime recover_clean.sql + embeddings_gold.db (garde quarantine).
6. Garde C:\\LaForge_data\\embeddings.db comme backup pristine de la recoveree.
"""
import os
import shutil
import sqlite3

TS = "20260602"
# Chemin DERIVE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
LIVE = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
CORRUPT_V = r"%NOKIDO_DATA%\embeddings.db"
FORENSIC = rf"C:\LaForge_data\embeddings_corrupt_{TS}.db"
# valeurs recoverees de reference (pour delta-check)
REF = {
    "rag_chunks": 158312,
    "rag_chunks_cold_storage": 232194,
    "rag_snapshots": 2073184,
    "rag_graph_edges": 160478,
    "network_log": 307365,
    "agent_messages": 130661,
}
V_TEMPS = [r"%NOKIDO_DATA%\recover.sql", r"%NOKIDO_DATA%\embeddings_recovered.db"]
TMP_TEMPS = [r"C:\tmp\recover_clean.sql", r"C:\tmp\embeddings_gold.db"]


def safe_count(d, t):
    try:
        return d.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    except Exception as e:
        return f"ERR:{str(e)[:30]}"


def main():
    # 1. verif live DB
    print("=== LIVE DB (RAG/embeddings.db) ===", flush=True)
    print("  realpath:", os.path.realpath(LIVE), flush=True)
    d = sqlite3.connect(f"file:{LIVE}?mode=ro", uri=True, timeout=60)
    for t in REF:
        print(f"  {t} = {safe_count(d, t)}", flush=True)
    print("  quick_check:", d.execute("PRAGMA quick_check(2)").fetchall(), flush=True)
    d.close()

    # 2. delta-check sur la corrompue (best-effort)
    print("=== DELTA-CHECK corrompue V: ===", flush=True)
    delta = False
    if os.path.exists(CORRUPT_V):
        try:
            c = sqlite3.connect(f"file:{CORRUPT_V}?mode=ro", uri=True, timeout=30)
            for t, ref in REF.items():
                v = safe_count(c, t)
                flag = ""
                if isinstance(v, int) and v > ref:
                    flag = f"  <-- DELTA +{v-ref} (writes post-dump !)"
                    delta = True
                print(f"  corrupt {t} = {v} (ref {ref}){flag}", flush=True)
            c.close()
        except Exception as e:
            print(f"  corrompue illisible (normal, malformed): {str(e)[:50]}", flush=True)
    else:
        print("  %NOKIDO_DATA%\\embeddings.db absente (deja deplacee ?)", flush=True)
    if delta:
        print("  !!! DELTA detecte -> NE PAS archiver, re-recover requis. STOP.", flush=True)
        return

    # 3. forensic move corrompue hors V:
    print("=== FORENSIC ===", flush=True)
    for ext in ("", "-wal", "-shm"):
        src = CORRUPT_V + ext
        if os.path.exists(src):
            try:
                shutil.move(src, FORENSIC + ext)
                print(f"  moved {src} -> {FORENSIC+ext}", flush=True)
            except Exception as e:
                print(f"  move {src} ERR (encore verrouille ?): {str(e)[:50]}", flush=True)

    # 4 + 5. cleanup temps
    print("=== CLEANUP ===", flush=True)
    for f in V_TEMPS + TMP_TEMPS:
        if os.path.exists(f):
            try:
                sz = round(os.path.getsize(f) / 1e9, 2)
                os.remove(f)
                print(f"  removed {f} ({sz}GB)", flush=True)
            except Exception as e:
                print(f"  remove {f} ERR: {str(e)[:50]}", flush=True)

    # 6. recap espace
    import shutil as sh
    for vol in ("%NOKIDO_DATA%\", "C:/"):
        u = sh.disk_usage(vol)
        print(f"  {vol} free {round(u.free/1e9,1)}GB / {round(u.total/1e9,1)}GB", flush=True)
    print("POSTSWAP DONE", flush=True)


if __name__ == "__main__":
    main()
