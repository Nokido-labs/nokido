"""
forge_db_compact_full.py — Cycle complet purge+vacuum avec orchestration hub.

Séquence atomique :
  1. POST /supervisor/sleep/NokidoMCP (libère DB lock)
  2. Wait fin process NokidoMCP
  3. DELETE rag_snapshots agressif (cutoff configurable)
  4. VACUUM full (5-15 min)
  5. ANALYZE
  6. POST /supervisor/wake/NokidoMCP (respawn hub)
  7. Wait /health OK

Privilege LaForgeTrusted (via trusted_script depuis hub MAIS hub respawn
après VACUUM via wake — donc trusted_script doit terminer avant hub re-up).

Solution : ne respawn hub QU'À LA FIN du script (étape 6). Le trusted_script
report exit code direct au caller. Sans hub up pendant 10-15 min mais propre.

ATTENTION : si trusted_script lui-même nécessite hub pour démarrer, et que
script sleep hub immediately, le trusted_script peut être tué. Solution :
le script est lancé SANS dépendance hub runtime (sqlite + urllib stdlib).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"


def _post_supervisor(path: str, timeout: float = 10) -> dict:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:8765{path}", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _hub_health(timeout: float = 3) -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=timeout).read()
        return True
    except Exception:
        return False


def _hr(b: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.2f} {u}"
        b /= 1024
    return f"{b:.2f} TB"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", default=None, help="YYYY-MM-DD (default = il y a 3 semaines)")
    ap.add_argument("--ops", nargs="+", default=["delete", "update"])
    ap.add_argument("--vacuum", action="store_true", help="VACUUM après purge (lock 5-15 min)")
    ap.add_argument(
        "--no-sleep", action="store_true", help="ne sleep pas le hub (DANGER : conflit lock)"
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cutoff = args.cutoff or (datetime.utcnow() - timedelta(days=21)).strftime("%Y-%m-%d")

    print("=" * 64)
    print(" forge_db_compact_full — cycle complet")
    print("=" * 64)
    print(f" DB         : {DB.name}")
    print(f" size before: {_hr(DB.stat().st_size)}")
    print(f" cutoff     : {cutoff}")
    print(f" ops        : {args.ops}")
    print(f" vacuum     : {args.vacuum}")
    print(f" sleep_hub  : {not args.no_sleep}")
    print(f" dry_run    : {args.dry_run}")
    print()

    # Count à supprimer
    c = sqlite3.connect(str(DB), timeout=15)
    placeholders = ",".join("?" for _ in args.ops)
    n = c.execute(
        f"SELECT COUNT(*) FROM rag_snapshots WHERE op IN ({placeholders}) AND timecode < ?",
        (*args.ops, cutoff),
    ).fetchone()[0]
    print(f"[count] {n:,} rows match purge condition")
    c.close()

    if args.dry_run:
        print("\n[DRY-RUN] arrêt sans modification.")
        return 0

    if n == 0 and not args.vacuum:
        print("Rien à purger, pas de --vacuum demandé. Exit.")
        return 0

    # 1. Sleep hub
    if not args.no_sleep:
        print("\n[1] SLEEP NokidoMCP...")
        r = _post_supervisor("/supervisor/sleep/NokidoMCP")
        print(f"   {r}")
        # Wait hub vraiment down
        for i in range(20):
            time.sleep(2)
            if not _hub_health(timeout=2):
                print(f"   hub DOWN at +{(i + 1) * 2}s")
                break
        else:
            print("   hub still up after 40s — abort")
            return 1

    # 2. DELETE
    if n > 0:
        print(f"\n[2] DELETE {n:,} rag_snapshots rows...")
        c = sqlite3.connect(str(DB), timeout=60)
        c.execute("PRAGMA journal_mode=WAL")
        t0 = time.time()
        c.execute(
            f"DELETE FROM rag_snapshots WHERE op IN ({placeholders}) AND timecode < ?",
            (*args.ops, cutoff),
        )
        c.commit()
        print(f"   DELETE done in {time.time() - t0:.1f}s")
        c.close()

    # 3. VACUUM
    if args.vacuum:
        print("\n[3] VACUUM (peut prendre plusieurs minutes)...")
        c = sqlite3.connect(str(DB), timeout=900, isolation_level=None)
        size_before = DB.stat().st_size
        t0 = time.time()
        c.execute("VACUUM")
        c.execute("ANALYZE")
        size_after = DB.stat().st_size
        elapsed = time.time() - t0
        print(f"   VACUUM+ANALYZE done in {elapsed:.1f}s")
        print(
            f"   DB {_hr(size_before)} -> {_hr(size_after)} "
            f"(reclaimed {_hr(size_before - size_after)})"
        )
        c.close()

    # 4. Wake hub
    if not args.no_sleep:
        print("\n[4] WAKE NokidoMCP...")
        r = _post_supervisor("/supervisor/wake/NokidoMCP")
        print(f"   {r}")
        # Wait hub up
        for i in range(30):
            time.sleep(3)
            if _hub_health(timeout=3):
                print(f"   hub UP at +{(i + 1) * 3}s")
                break
        else:
            print("   hub still down after 90s — manual check")

    print("\n" + "=" * 64)
    print(f" size final : {_hr(DB.stat().st_size)}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
