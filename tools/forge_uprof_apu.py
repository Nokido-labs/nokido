#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_uprof_apu.py — collecte des compteurs APU via AMD uProf CLI.

Zone d'ombre hardware (roadmap chantier #7, niche) : sur APU AMD (Ryzen + iGPU
780M), la RAM est UNIFIÉE (CPU/iGPU/NPU partagent) et le thermal throttle peut
être le vrai goulot plutôt que la saturation logicielle. AMD uProf expose ces
compteurs (timechart) que ni psutil ni py-spy ne voient.

INERTE + FAIL-OPEN si AMDuProfCLI absent (uProf = install AMD séparé).
Roadmap : « niche ». Modes : check | collect [--seconds N].

Install : https://www.amd.com/en/developer/uprof.html → AMDuProfCLI.exe.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "sandbox", "uprof")
CANDIDATES = [
    r"C:\Program Files\AMD\AMDuProf\bin\AMDuProfCLI.exe",
    r"C:\Program Files\AMD\AMD uProf\bin\AMDuProfCLI.exe",
    r"C:\Program Files (x86)\AMD\AMDuProf\bin\AMDuProfCLI.exe",
]


def find_cli() -> str | None:
    w = shutil.which("AMDuProfCLI")
    if w:
        return w
    for c in CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def _run(cmd: list[str], timeout: float):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return -1, "", f"{type(exc).__name__}: {exc}"


def cmd_check() -> int:
    cli = find_cli()
    print(f"[uprof] AMDuProfCLI = {cli or 'INTROUVABLE (install AMD uProf)'}")
    if not cli:
        return 2
    rc, out, err = _run([cli, "--version"], 20)
    print(f"[uprof] version rc={rc} {out.strip()[:200]} {err.strip()[:200]}")
    rc2, out2, _ = _run([cli, "info", "--system"], 30)
    if rc2 == 0:
        print("[uprof] system info :")
        print("\n".join(out2.splitlines()[:20]))
    return 0 if rc == 0 else 3


def cmd_collect(seconds: int) -> int:
    cli = find_cli()
    if not cli:
        print("[uprof] INTROUVABLE — collecte impossible")
        return 2
    os.makedirs(OUT_DIR, exist_ok=True)
    out_base = os.path.join(OUT_DIR, f"apu_timechart_{int(time.time())}")
    # timechart : compteurs power/thermal/freq (les events exacts dépendent du
    # profil uProf ; -e power couvre socket/core/igpu sur APU récents).
    cmd = [cli, "timechart", "--event", "power",
           "--interval", "1000", "--duration", str(seconds),
           "-o", out_base]
    print(f"[uprof] collecte {seconds}s → {out_base} ...")
    rc, out, err = _run(cmd, seconds + 60)
    if rc == 0:
        print(f"[uprof] OK : {out_base}")
        return 0
    print(f"[uprof] rc={rc}\n{(err or out)[:600]}")
    return rc or 5


def main() -> int:
    ap = argparse.ArgumentParser(description="Collecte compteurs APU via AMD uProf")
    ap.add_argument("mode", choices=["check", "collect"])
    ap.add_argument("--seconds", type=int, default=15)
    args = ap.parse_args()
    if args.mode == "check":
        return cmd_check()
    return cmd_collect(args.seconds)


if __name__ == "__main__":
    raise SystemExit(main())
