#!/usr/bin/env python3
"""NSSM hardening Nokido — anti crash-loop config.

Pour chaque service NSSM commencant par 'Nokido' ou matchant un slug
Nokido (gemini_poll_daemon, multi_llm_daemon) :

  * AppExit Default = Restart    (defaut implicite mais on rend explicite)
  * AppThrottle = 30000          (process doit vivre 30s pour reset crash-counter)
  * AppRestartDelay = 60000      (1min entre crash et nouveau spawn)
  * Si AppExitAction custom code 0/1 absent : set Exit pour code 0
    (clean exit ne doit pas relancer)

Detecte aussi les DOUBLONS : services differents pointant le meme script.
Liste sans modifier.

Usage:
  LAFORGE_PYTHON forge_nssm_hardening.py --dry-run   # report
  LAFORGE_PYTHON forge_nssm_hardening.py             # applique
  LAFORGE_PYTHON forge_nssm_hardening.py --remove-duplicate <svc>
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

NSSM = shutil.which("nssm") or r"C:\ProgramData\chocolatey\bin\nssm.EXE"

THROTTLE_MS = 30_000
RESTART_DELAY_MS = 60_000

KNOWN_NON_LAFORGE_PREFIXES = ()


def list_services() -> list[str]:
    out = subprocess.run([NSSM, "list"], capture_output=True, text=True, errors="replace")
    return [l.strip() for l in out.stdout.splitlines() if l.strip()]


def nssm_get(svc: str, key: str) -> str:
    p = subprocess.run([NSSM, "get", svc, key], capture_output=True, text=True, errors="replace")
    return (p.stdout or "").strip()


def nssm_get_exit(svc: str) -> str:
    p = subprocess.run([NSSM, "get", svc, "AppExit", "Default"], capture_output=True, text=True, errors="replace")
    return (p.stdout or "").strip()


def nssm_set(svc: str, *args: str, dry: bool) -> str:
    if dry:
        return f"DRY: nssm set {svc} {' '.join(args)}"
    p = subprocess.run([NSSM, "set", svc, *args], capture_output=True, text=True, errors="replace")
    if p.returncode != 0:
        err = (p.stderr or "").strip().replace("\n", " | ")[:200]
        return f"FAIL rc={p.returncode}: {err}"
    return (p.stdout or "").strip() or "ok"


def is_nokido_service(svc: str, app_params: str) -> bool:
    if svc.lower().startswith("laforge"):
        return True
    if svc in ("gemini_poll_daemon", "multi_llm_daemon"):
        return True
    if "laforge" in app_params.lower() or "script python ia" in app_params.lower():
        return True
    return False


def normalize_script(app: str, params: str) -> str:
    """Extract canonical script path from AppParameters."""
    combined = f"{app} {params}".lower()
    m = re.search(r"[\w/\\\.: ]+\.py", combined)
    if not m:
        return params.strip().strip('"')[:80]
    return Path(m.group(0).strip()).name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--remove-duplicate",
        metavar="SVC",
        help="Remove a specific duplicate service via nssm remove (confirm=yes)",
    )
    args = ap.parse_args()

    services = list_services()
    print(f"NSSM services total: {len(services)}")

    nokido_svcs: list[tuple[str, str, str]] = []  # (svc, app, params)
    for s in services:
        app = nssm_get(s, "Application")
        params = nssm_get(s, "AppParameters")
        if is_nokido_service(s, f"{app} {params}"):
            nokido_svcs.append((s, app, params))

    print(f"Nokido services: {len(nokido_svcs)}")

    # detect duplicates by canonical script name
    by_script: dict[str, list[str]] = defaultdict(list)
    for s, app, params in nokido_svcs:
        script = normalize_script(app, params)
        by_script[script].append(s)

    dups = {k: v for k, v in by_script.items() if len(v) > 1}
    if dups:
        print("\n=== DUPLICATES detected ===")
        for script, svcs in dups.items():
            print(f"  {script}: {svcs}")

    if args.remove_duplicate:
        target = args.remove_duplicate
        if target not in [s for s, _, _ in nokido_svcs]:
            print(f"ERROR: {target} not in Nokido services", file=sys.stderr)
            return 2
        if args.dry_run:
            print(f"DRY: nssm stop {target} & nssm remove {target} confirm")
        else:
            subprocess.run([NSSM, "stop", target], capture_output=True, text=True, errors="replace")
            r = subprocess.run([NSSM, "remove", target, "confirm"], capture_output=True, text=True, errors="replace")
            print(f"remove {target}: {r.stdout.strip() or r.stderr.strip()}")
        return 0

    print("\n=== HARDENING applied ===" if not args.dry_run else "\n=== HARDENING (dry-run) ===")
    for s, app, params in nokido_svcs:
        thr = nssm_get(s, "AppThrottle")
        delay = nssm_get(s, "AppRestartDelay")
        exit_def = nssm_get_exit(s)
        changes = []
        try:
            cur_thr = int(thr) if thr else 0
        except ValueError:
            cur_thr = 0
        try:
            cur_delay = int(delay) if delay else 0
        except ValueError:
            cur_delay = 0
        if cur_thr < THROTTLE_MS:
            r = nssm_set(s, "AppThrottle", str(THROTTLE_MS), dry=args.dry_run)
            changes.append(f"AppThrottle {cur_thr}->{THROTTLE_MS} ({r})")
        if cur_delay < RESTART_DELAY_MS:
            r = nssm_set(s, "AppRestartDelay", str(RESTART_DELAY_MS), dry=args.dry_run)
            changes.append(f"AppRestartDelay {cur_delay}->{RESTART_DELAY_MS} ({r})")
        if exit_def.lower() != "restart":
            r = nssm_set(s, "AppExit", "Default", "Restart", dry=args.dry_run)
            changes.append(f"AppExit Default '{exit_def}'->'Restart' ({r})")
        if changes:
            print(f"  [{s}] {'; '.join(changes)}")
        else:
            print(f"  [{s}] already hardened")

    return 0


if __name__ == "__main__":
    sys.exit(main())
