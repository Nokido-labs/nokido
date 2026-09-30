"""forge_db_instant_swap.py — swap instantane (rename) de la good DB pre-stagee.

Pre-requis : RAG/embeddings.db.new deja copiee (good, depuis backup pristine).
A lancer HUB STOPPE. Verifie le verrou, purge la live cassee + WAL/SHM perimes,
rename .new -> live (instantane, meme volume). Verifie integrity.
"""
import os
import sqlite3

# Chemin DERIVE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
LIVE = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
NEW = LIVE + ".new"


def locked(p):
    if not os.path.exists(p):
        return False
    try:
        os.rename(p, p + ".lt")
        os.rename(p + ".lt", p)
        return False
    except OSError:
        return True


def main():
    if not (os.path.exists(NEW) and os.path.getsize(NEW) > 6_000_000_000):
        print("ABORT: .new absente ou incomplete (copie pas finie ?)")
        return
    if locked(LIVE):
        print("ABORT: hub tient encore la DB. Stoppe-le et NE le relance PAS.")
        return
    for ext in ("", "-wal", "-shm"):
        f = LIVE + ext
        if os.path.exists(f):
            os.remove(f)
            print("  rm", os.path.basename(f), flush=True)
    os.rename(NEW, LIVE)
    print("  renamed .new -> embeddings.db", flush=True)
    d = sqlite3.connect(LIVE, timeout=60)
    print("  rag_chunks :", d.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0], flush=True)
    print("  quick_check:", d.execute("PRAGMA quick_check(2)").fetchall(), flush=True)
    print("  islink     :", os.path.islink(LIVE), flush=True)
    d.close()
    print("INSTANT SWAP DONE -> relance le hub", flush=True)


if __name__ == "__main__":
    main()
