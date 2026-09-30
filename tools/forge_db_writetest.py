"""forge_db_writetest.py — Diagnostic : pourquoi les writes embedding ne persistent pas.

Liste les triggers de rag_chunks, puis teste un UPDATE embedding sur un chunk
laforge-code NULL : rowcount, persistance post-commit, persistance post-reopen.

Run : run action=trusted_script path=tools/forge_db_writetest.py
"""

import sqlite3
import struct
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"


def main() -> None:
    con = sqlite3.connect(str(DB), timeout=60)
    con.execute("PRAGMA busy_timeout=30000")

    print("=== triggers ===")
    for name, sql in con.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger'"):
        print(f"--- {name} ---")
        print((sql or "")[:600])
        print()

    row = con.execute(
        "SELECT id FROM rag_chunks WHERE embedding IS NULL AND origin='laforge-code' LIMIT 1"
    ).fetchone()
    if not row:
        print("aucun chunk laforge-code NULL")
        con.close()
        return
    cid = row[0]
    print(f"=== write test sur id={cid!r} ===")
    blob = struct.pack("1024f", *([0.0123] * 1024))
    cur = con.execute("UPDATE rag_chunks SET embedding=? WHERE id=?", (blob, cid))
    print(f"rowcount UPDATE : {cur.rowcount}")
    con.commit()
    chk = con.execute(
        "SELECT embedding IS NOT NULL, LENGTH(embedding) FROM rag_chunks WHERE id=?", (cid,)
    ).fetchone()
    print(f"post-commit (meme conn) : not_null={chk[0]}, length={chk[1]}")
    con.close()

    con2 = sqlite3.connect(str(DB), timeout=30)
    chk2 = con2.execute(
        "SELECT embedding IS NOT NULL, LENGTH(embedding) FROM rag_chunks WHERE id=?", (cid,)
    ).fetchone()
    print(f"fresh reopen : not_null={chk2[0]}, length={chk2[1]}")
    con2.close()


if __name__ == "__main__":
    main()
