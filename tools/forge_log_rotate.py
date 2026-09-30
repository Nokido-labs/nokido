"""
forge_log_rotate.py — Rotate logs Nokido volumineux (truncate-safe).

Garde les N derniers MB de chaque .log dans logs/ (+ supervisor/).
Évite supprimer le file (handles ouverts) — utilise copy_truncate pattern.

CLI :
    LAFORGE_PYTHON tools/forge_log_rotate.py [--max-mb 50] [--dry-run]

Privilégié : compte LaForgeTrusted (ACL Modify sur logs/) via trusted_script.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"


def _hr(b: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} TB"


def rotate_file(p: Path, max_bytes: int, dry_run: bool = False) -> dict:
    """Garde les `max_bytes` derniers octets dans `p`, **in-place via mode r+b**.

    Pourquoi `r+b` truncate au lieu de `replace()` :
        Le hub Nokido maintient un handle ouvert en write sur ses .log.
        `replace()` sous Windows = rename atomique qui demande exclusive
        access → PermissionError. Au lieu : mode `r+b` ne crée pas un
        nouveau handle exclusif, on peut écrire + truncate en place.
    """
    if not p.exists():
        return {"file": str(p), "ok": False, "reason": "absent"}
    size = p.stat().st_size
    if size <= max_bytes:
        return {"file": p.name, "ok": True, "skipped": True, "size_before": size}
    if dry_run:
        return {
            "file": p.name,
            "ok": True,
            "dry_run": True,
            "size_before": size,
            "would_truncate_to": max_bytes,
        }
    try:
        # 1. Lire les derniers max_bytes
        with open(p, "rb") as f:
            f.seek(size - max_bytes)
            keep = f.read()
        # 2. Marker file rotation (best-effort)
        ts = time.strftime("%Y%m%d-%H%M%S")
        archive = p.with_name(f"{p.stem}.{ts}.archive")
        try:
            archive.write_text(
                f"# log rotated at {ts} — original size {size} bytes "
                f"-> kept last {len(keep)} bytes\n",
                encoding="utf-8",
            )
        except Exception:
            pass
        # 3. In-place : open en r+b (NE crée pas exclusif), write + truncate
        with open(p, "r+b") as f:
            f.seek(0)
            f.write(keep)
            f.truncate(len(keep))
        return {
            "file": p.name,
            "ok": True,
            "size_before": size,
            "size_after": len(keep),
            "archive": archive.name,
            "method": "in_place_truncate",
        }
    except Exception as e:
        return {"file": p.name, "ok": False, "error": f"{type(e).__name__}: {e}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--max-mb", type=int, default=50, help="garde les N derniers MB par fichier (default 50)"
    )
    ap.add_argument(
        "--min-mb", type=int, default=100, help="ne rotate que les files > N MB (default 100)"
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    max_bytes = args.max_mb * 1024 * 1024
    min_bytes = args.min_mb * 1024 * 1024

    candidates = []
    for d in (LOGS, LOGS / "supervisor"):
        if d.is_dir():
            for f in d.glob("*.log"):
                try:
                    if f.stat().st_size > min_bytes:
                        candidates.append(f)
                except Exception:
                    pass

    print(f"Found {len(candidates)} log file(s) > {args.min_mb} MB")
    total_before = 0
    total_after = 0
    for f in sorted(candidates, key=lambda x: -x.stat().st_size):
        r = rotate_file(f, max_bytes, dry_run=args.dry_run)
        before = r.get("size_before", 0)
        after = r.get("size_after", before)
        total_before += before
        total_after += after
        if r.get("skipped"):
            continue
        if not r.get("ok"):
            print(f"  FAIL {r['file']}: {r.get('error', r.get('reason'))}")
            continue
        if args.dry_run:
            print(f"  [DRY] {r['file']}: {_hr(before)} -> would be {_hr(max_bytes)}")
        else:
            print(f"  OK  {r['file']}: {_hr(before)} -> {_hr(after)}")

    print(
        f"\nTotal: {_hr(total_before)} -> {_hr(total_after)} "
        f"(freed {_hr(total_before - total_after)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
