"""
forge_db_compact.py — Cleanup + VACUUM embeddings.db.

Actions (modulaire via flags) :
  --drop-janitor      DROP snapshot_janitor_* tables orphelines
  --purge-snapshots   DELETE rag_snapshots WHERE op IN (delete,update) AND timecode < CUTOFF
  --vacuum            VACUUM (lock DB 5-15 min, besoin ~espace libre = taille DB)
  --analyze           ANALYZE (recompute stats)
  --auto-vacuum-incr  PRAGMA auto_vacuum=INCREMENTAL (active futur compactage)
  --all               toutes les actions ci-dessus

  --cutoff YYYY-MM-DD (default = il y a 30 jours)
  --dry-run           simulation seulement

Privilégié via trusted_script (LaForgeTrusted).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"


def _hr(b: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.2f} {u}"
        b /= 1024
    return f"{b:.2f} TB"


def db_size() -> int:
    return DB.stat().st_size if DB.exists() else 0


def freelist_bytes(c) -> int:
    fl = c.execute("PRAGMA freelist_count").fetchone()[0]
    psz = c.execute("PRAGMA page_size").fetchone()[0]
    return fl * psz


def drop_janitor(c, dry_run=False) -> dict:
    rows = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'snapshot_janitor_%'"
    ).fetchall()
    out = {"dropped": [], "rows_freed": 0}
    for (name,) in rows:
        try:
            n = c.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        except Exception:
            n = 0
        if dry_run:
            print(f"  [DRY] DROP TABLE {name} ({n:,} rows)")
        else:
            c.execute(f'DROP TABLE "{name}"')
            print(f"  DROP {name} ({n:,} rows)")
        out["dropped"].append(name)
        out["rows_freed"] += n
    if not dry_run:
        c.commit()
    return out


def purge_snapshots(c, cutoff: str, ops=("delete", "update"), dry_run=False) -> dict:
    placeholders = ",".join("?" for _ in ops)
    sql_count = f"SELECT COUNT(*) FROM rag_snapshots WHERE op IN ({placeholders}) AND timecode < ?"
    n = c.execute(sql_count, (*ops, cutoff)).fetchone()[0]
    if dry_run:
        print(
            f"  [DRY] DELETE {n:,} rows from rag_snapshots "
            f"WHERE op IN {ops} AND timecode < {cutoff}"
        )
    else:
        t0 = time.time()
        c.execute(
            f"DELETE FROM rag_snapshots WHERE op IN ({placeholders}) AND timecode < ?",
            (*ops, cutoff),
        )
        c.commit()
        print(f"  DELETED {n:,} rows in {time.time() - t0:.1f}s")
    return {"deleted": n}


def set_auto_vacuum_incremental(c) -> dict:
    """Note : auto_vacuum mode ne peut être changé que VACUUM-ready DB.
    On set + VACUUM derrière pour appliquer."""
    cur_av = c.execute("PRAGMA auto_vacuum").fetchone()[0]
    if cur_av == 2:
        return {"already": "INCREMENTAL"}
    c.execute("PRAGMA auto_vacuum = INCREMENTAL")
    return {"set": "INCREMENTAL", "previous": cur_av, "note": "actif après VACUUM"}


def vacuum_db(c, dry_run=False) -> dict:
    if dry_run:
        return {"dry_run": True, "note": "VACUUM would compact + reclaim freelist"}
    fl_before = freelist_bytes(c)
    db_before = db_size()
    print(f"  freelist before: {_hr(fl_before)}, DB: {_hr(db_before)}")
    print("  VACUUM start (peut prendre plusieurs minutes)...")
    t0 = time.time()
    c.execute("VACUUM")
    elapsed = time.time() - t0
    db_after = db_size()
    fl_after = freelist_bytes(c)
    saved = db_before - db_after
    print(f"  VACUUM done in {elapsed:.1f}s")
    print(f"  DB: {_hr(db_before)} -> {_hr(db_after)} (reclaimed {_hr(saved)})")
    print(f"  freelist after: {_hr(fl_after)}")
    return {
        "elapsed_s": round(elapsed, 1),
        "db_before": db_before,
        "db_after": db_after,
        "reclaimed_bytes": saved,
    }


def analyze_db(c, dry_run=False) -> dict:
    if dry_run:
        return {"dry_run": True}
    t0 = time.time()
    c.execute("ANALYZE")
    return {"elapsed_s": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description="embeddings.db cleanup + vacuum")
    ap.add_argument("--drop-janitor", action="store_true")
    ap.add_argument("--purge-snapshots", action="store_true")
    ap.add_argument("--vacuum", action="store_true")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--auto-vacuum-incr", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--cutoff", default=None, help="YYYY-MM-DD pour purge (default = il y a 30j)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.all:
        args.drop_janitor = True
        args.purge_snapshots = True
        args.auto_vacuum_incr = True
        args.vacuum = True
        args.analyze = True

    cutoff = args.cutoff or (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")

    print("=" * 64)
    print(f" forge_db_compact — DB: {DB.name}")
    print("=" * 64)
    print(f" size before: {_hr(db_size())}")
    print(f" cutoff date: {cutoff}")
    print(f" dry_run    : {args.dry_run}")
    print()

    c = sqlite3.connect(str(DB), timeout=60, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    print(f" freelist before: {_hr(freelist_bytes(c))}\n")

    if args.drop_janitor:
        print("[A] DROP snapshot_janitor_* tables")
        drop_janitor(c, dry_run=args.dry_run)
        print()

    if args.purge_snapshots:
        print(f"[B] PURGE rag_snapshots op IN (delete,update) AND timecode < {cutoff}")
        purge_snapshots(c, cutoff, dry_run=args.dry_run)
        print()

    if args.auto_vacuum_incr:
        print("[C] PRAGMA auto_vacuum = INCREMENTAL")
        r = set_auto_vacuum_incremental(c)
        print(f"   {r}\n")

    if args.vacuum:
        print("[D] VACUUM")
        vacuum_db(c, dry_run=args.dry_run)
        print()

    if args.analyze:
        print("[E] ANALYZE")
        r = analyze_db(c, dry_run=args.dry_run)
        print(f"   {r}\n")

    c.close()
    print("=" * 64)
    print(f" size after : {_hr(db_size())}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
