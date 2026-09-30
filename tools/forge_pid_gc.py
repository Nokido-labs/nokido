#!/usr/bin/env python3
"""PID file garbage collector pour Nokido sandbox.

Scan sandbox/*.pid. Pour chaque entry :
  - PID < 0 ou non-numeric -> unlink
  - PID introuvable dans psutil.pids() -> unlink (stale)
  - PID vivant mais psutil.Process(pid).cmdline() ne contient pas
    le slug derive du nom de fichier (.pid sans extension) -> unlink
    (PID recycle sur un autre process)
  - PID vivant + cmdline match -> garde

Le fait que OpenProcess Windows reussisse NE SUFFIT PAS : un PID
recycle sur un service systeme inaccessible donne false positive.
Fail-safe : si AccessDenied -> on considere PID non lie a Nokido
=> unlink (sinon daemon refuse demarrer "Another instance").

Usage:
  LAFORGE_PYTHON forge_pid_gc.py             # report + suppression
  LAFORGE_PYTHON forge_pid_gc.py --dry-run   # report seul
  LAFORGE_PYTHON forge_pid_gc.py --json      # output JSON pour hub

A cabler dans :
  1. LaForge-Master :8765 supervisor au boot (avant spawn daemons)
  2. Wake-event resume from sleep (schtasks /onevent)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import psutil
except ImportError:
    print("ERROR: psutil missing", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"

SLUG_ALIASES = {
    "agt_deepseek": "agt_deepseek",
    "agt_gemini": "agt_gemini",
    "agt_groq": "agt_groq",
    "agt_local": "agt_local",
    "agt_mistral": "agt_mistral",
    "biblio_worker": "biblio_worker",
    "brain_worker_npu": "brain_worker",
    "forge_collab_broker": "forge_collab_broker",
    "forge_ping_monitor": "forge_ping_monitor",
    "gemini_poll_daemon": "gemini_poll_daemon",
    "hebbian_linker": "hebbian_linker",
    "homeostasis": "homeostasis",
    "hub": "nokido_hub",
    "mcp_NOKIDO": "mcp_NOKIDO",
}


def classify(pf: Path, live_pids: set) -> tuple[str, str, int | None]:
    """Returns (verdict, reason, pid)."""
    try:
        raw = pf.read_text().strip()
        if not raw:
            return "delete", "empty file", None
        pid = int(raw)
    except (OSError, ValueError) as e:
        return "delete", f"invalid content ({e})", None

    if pid <= 0:
        return "delete", "non-positive PID", pid

    if pid not in live_pids:
        return "delete", "PID not in live set", pid

    slug = SLUG_ALIASES.get(pf.stem, pf.stem)
    try:
        p = psutil.Process(pid)
        cmdline = " ".join(p.cmdline()).lower()
    except psutil.AccessDenied:
        return "delete", f"AccessDenied on pid {pid} (likely recycled system PID)", pid
    except psutil.NoSuchProcess:
        return "delete", "race: process died between pids() and Process()", pid
    except Exception as e:
        return "delete", f"unexpected error: {e}", pid

    if slug.lower() not in cmdline:
        return "delete", f"slug {slug!r} not in cmdline (PID recycled on '{cmdline[:60]}...')", pid

    return "keep", "alive + cmdline match", pid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not SANDBOX.is_dir():
        print(f"ERROR: sandbox not found: {SANDBOX}", file=sys.stderr)
        return 2

    live_pids = set(psutil.pids())
    results: list[dict] = []
    for pf in sorted(SANDBOX.glob("*.pid")):
        verdict, reason, pid = classify(pf, live_pids)
        action = "would-delete" if (args.dry_run and verdict == "delete") else verdict
        if verdict == "delete" and not args.dry_run:
            try:
                pf.unlink()
            except OSError as e:
                action = f"delete-failed: {e}"
        results.append(
            {
                "file": pf.name,
                "pid": pid,
                "verdict": verdict,
                "action": action,
                "reason": reason,
                "mtime": int(pf.stat().st_mtime) if pf.exists() else None,
            }
        )

    if args.json:
        print(
            json.dumps(
                {
                    "ts": int(time.time()),
                    "sandbox": str(SANDBOX),
                    "dry_run": args.dry_run,
                    "scanned": len(results),
                    "kept": sum(1 for r in results if r["verdict"] == "keep"),
                    "deleted": sum(1 for r in results if r["action"] in ("delete", "would-delete")),
                    "results": results,
                },
                indent=2,
            )
        )
    else:
        print(f"PID GC scan {SANDBOX} (dry_run={args.dry_run})")
        print(f"{'FILE':40s} {'PID':>7s}  ACTION       REASON")
        for r in results:
            pid_s = str(r["pid"]) if r["pid"] is not None else "-"
            print(f"  {r['file']:38s} {pid_s:>7s}  {r['action']:12s} {r['reason']}")
        kept = sum(1 for r in results if r["verdict"] == "keep")
        deleted = sum(1 for r in results if r["action"] in ("delete", "would-delete"))
        print(
            f"\nTotal: {len(results)} scanned, {kept} kept, {deleted} {'would-be-' if args.dry_run else ''}deleted"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
