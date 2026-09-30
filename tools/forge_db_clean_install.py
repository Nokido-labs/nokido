"""forge_db_clean_install.py — pose propre de la good DB a RAG/embeddings.db.

A lancer HUB STOPPE (sinon abort : fichier verrouille). Corrige la re-corruption
causee par un WAL/SHM perime laisse par le swap. Source = backup pristine
C:\\LaForge_data\\embeddings.db (integrity ok, 158312). Resultat = fichier reel
(PAS de symlink), AUCUN -wal/-shm perime.
"""
import os
import shutil
import sqlite3

# Chemin DERIVE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
LIVE = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
SRC = r"C:\LaForge_data\embeddings.db"


def locked(path):
    if not os.path.exists(path):
        return False
    try:
        os.rename(path, path + ".locktest")
        os.rename(path + ".locktest", path)
        return False
    except OSError:
        return True


def main():
    # garde : hub doit etre stoppe
    for p in (LIVE, LIVE + "-wal", LIVE + "-shm"):
        if locked(p):
            print(f"ABORT: {p} verrouille -> le hub tourne encore. Stoppe-le d'abord.", flush=True)
            return
    print("hub non verrouille -> OK pour clean install", flush=True)

    # 1. purge DB live corrompue + WAL/SHM perimes
    for ext in ("", "-wal", "-shm"):
        f = LIVE + ext
        if os.path.exists(f):
            os.remove(f)
            print(f"  removed {f}", flush=True)

    # 2. copie backup pristine -> live (fichier reel)
    print("copie backup pristine -> live ...", flush=True)
    shutil.copyfile(SRC, LIVE)
    print(f"  live = {LIVE} ({round(os.path.getsize(LIVE)/1e9,2)}GB)", flush=True)

    # 3. WAL checkpoint propre + verif : ouvre, force WAL, checkpoint, integrity
    d = sqlite3.connect(LIVE, timeout=120)
    jm = d.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    d.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    d.execute("PRAGMA synchronous=NORMAL")
    print("  journal_mode:", jm, flush=True)
    print("  rag_chunks  :", d.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0], flush=True)
    print("  integrity   :", d.execute("PRAGMA integrity_check(3)").fetchall(), flush=True)
    print("  islink      :", os.path.islink(LIVE), flush=True)
    print("  realpath    :", os.path.realpath(LIVE), flush=True)
    d.close()
    # checkpoint TRUNCATE laisse un -wal vide ; on le retire pour partir net
    for ext in ("-wal", "-shm"):
        f = LIVE + ext
        if os.path.exists(f):
            os.remove(f)
            print(f"  cleaned {f}", flush=True)
    print("CLEAN INSTALL DONE -> relance le hub", flush=True)


if __name__ == "__main__":
    main()
