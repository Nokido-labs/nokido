"""forge_fix_null_ids.py — Assigne un id deterministe aux chunks rag_chunks id=NULL.

Des chunks (ancien domaine forge_core / app/_attic) ont `id IS NULL` : SQLite
autorise NULL dans un TEXT PRIMARY KEY. Consequence : non referencables, et
`UPDATE ... WHERE id=NULL` matche 0 ligne silencieusement (le rebuild croyait
embedder mais n'ecrivait rien).

Assigne id = sha256(source+text)[:16], resout les collisions. Le trigger
auto_snapshot_before_update a `WHEN OLD.id IS NOT NULL` -> ne fire pas sur ces
lignes, pas de snapshot a gerer.

Run     : run action=trusted_script path=tools/forge_fix_null_ids.py
Dry-run : ... forge_fix_null_ids.py script_args="--dry-run"
"""

import hashlib
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
DRY = "--dry-run" in sys.argv


def main() -> None:
    con = sqlite3.connect(str(DB), timeout=60)
    con.execute("PRAGMA busy_timeout=30000")
    rows = con.execute("SELECT rowid, source, text FROM rag_chunks WHERE id IS NULL").fetchall()
    print(f"[fix-id] chunks id=NULL : {len(rows):,}")
    if not rows:
        con.close()
        return
    if DRY:
        for r in rows[:6]:
            print(f"  rowid={r[0]}  source={(r[1] or '')[:55]}")
        print("[fix-id] --dry-run : aucune ecriture")
        con.close()
        return

    existing = {r[0] for r in con.execute("SELECT id FROM rag_chunks WHERE id IS NOT NULL")}
    assigned = coll = 0
    for rowid, source, text in rows:
        base = hashlib.sha256(
            ((source or "") + (text or "")).encode("utf-8", "replace")
        ).hexdigest()[:16]
        new = base
        n = 0
        while new in existing:
            n += 1
            new = base[:13] + f"{n:03d}"
            coll += 1
        existing.add(new)
        con.execute("UPDATE rag_chunks SET id=? WHERE rowid=?", (new, rowid))
        assigned += 1
    con.commit()
    left = con.execute("SELECT COUNT(*) FROM rag_chunks WHERE id IS NULL").fetchone()[0]
    con.close()
    print(f"[fix-id] {assigned:,} ids assignes ({coll} collisions resolues)")
    print(f"[fix-id] id=NULL restants : {left}")


if __name__ == "__main__":
    main()
