"""forge_db_swap.py — swap de la DB recoveree en live, relocalisee sur C: (marge).

Cause racine corruption = V: (17GB) saturé → write SQLite tronqué → malformed.
On relocalise la DB sur C:\\LaForge_data (259GB libres) et on repointe le symlink
RAG/embeddings.db. La DB corrompue est conservée en backup forensic (jamais delete).

Etapes : mkdir -> copy final->live -> repoint symlink (fallback copie réelle si
pas le privilège symlink) -> forensic move corrupt off V: -> verif integrity.
"""
import os
import shutil
import sqlite3

TS = "20260602"
NEWDIR = r"C:\LaForge_data"
LIVE = os.path.join(NEWDIR, "embeddings.db")
FINAL = r"C:\tmp\embeddings_final.db"
CORRUPT_V = r"%NOKIDO_DATA%\embeddings.db"
FORENSIC = os.path.join(NEWDIR, f"embeddings_corrupt_{TS}.db")
# Chemin DERIVE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
SYMLINK = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")


def main():
    os.makedirs(NEWDIR, exist_ok=True)

    # 1. copy final -> live (sur C:, volume avec marge)
    print("copie final -> live ...", flush=True)
    shutil.copyfile(FINAL, LIVE)
    print(f"  live = {LIVE} ({round(os.path.getsize(LIVE)/1e9,2)}GB)", flush=True)

    # 2. repoint symlink RAG/embeddings.db -> live
    if os.path.islink(SYMLINK) or os.path.exists(SYMLINK):
        os.unlink(SYMLINK)
        print("ancien symlink retire", flush=True)
    used_symlink = True
    try:
        os.symlink(LIVE, SYMLINK)
        print(f"symlink -> {os.path.realpath(SYMLINK)}", flush=True)
    except OSError as e:
        used_symlink = False
        print(f"SYMLINK refuse ({str(e)[:60]}) -> fallback copie reelle", flush=True)
        shutil.copyfile(LIVE, SYMLINK)
        print("fichier reel place a RAG/embeddings.db", flush=True)

    # 3. forensic move de la corrompue hors de V: (libere V:)
    for ext in ("", "-wal", "-shm"):
        src = CORRUPT_V + ext
        if os.path.exists(src):
            dst = FORENSIC + ext
            shutil.move(src, dst)
            print(f"forensic: {src} -> {dst}", flush=True)

    # 4. verif via le chemin canonique (symlink)
    d = sqlite3.connect(SYMLINK, timeout=180)
    print("via path rag_chunks   :", d.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0], flush=True)
    print("via path cold_storage :", d.execute("SELECT COUNT(*) FROM rag_chunks_cold_storage").fetchone()[0], flush=True)
    print("via path snapshots    :", d.execute("SELECT COUNT(*) FROM rag_snapshots").fetchone()[0], flush=True)
    print("quick_check           :", d.execute("PRAGMA quick_check(3)").fetchall(), flush=True)
    print("realpath canonique    :", os.path.realpath(SYMLINK), flush=True)
    d.close()
    print(f"SWAP DONE (symlink={used_symlink})", flush=True)


if __name__ == "__main__":
    main()
