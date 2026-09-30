#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_deno_check.py — type-check d'un fichier Deno/TS via `deno check`.

Le sandbox (offline/online) ne peut pas atteindre le binaire deno (profil
%USERPROFILE%\\.deno refusé). Lancé en trusted_script (LaForgeTrusted,
privilégié) il accède au deno du user et valide un .ts AVANT commit/restart —
critique pour proxy_deno/core/supervisor.ts (un .ts cassé = plus de superviseur,
pas de fallback contrairement à services.toml).

Usage :
    forge_deno_check.py [chemin/relatif.ts]   # défaut: proxy_deno/core/supervisor.ts
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DENO_CANDIDATES = [
    __import__("os").path.expanduser(r"~\.deno\bin\deno.exe"),
    __import__("os").path.expanduser(r"~\scoop\shims\deno.exe"),
    r"C:\ProgramData\chocolatey\bin\deno.exe",
    r"C:\Program Files\deno\deno.exe",
    "deno",
]


def _find_deno() -> str | None:
    # 1. Chemins explicites connus.
    for c in DENO_CANDIDATES:
        if c != "deno" and os.path.exists(c):
            return c
    # 2. PATH.
    import shutil
    w = shutil.which("deno")
    if w:
        return w
    # 3. Process deno EN COURS (le superviseur tourne) -> son exe.
    try:
        import psutil  # type: ignore
        for p in psutil.process_iter(["name", "exe"]):
            if (p.info.get("name") or "").lower() == "deno.exe" and p.info.get("exe"):
                return p.info["exe"]
    except Exception:
        pass
    return None


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "proxy_deno/core/supervisor.ts"
    abs_target = os.path.join(ROOT, target)
    deno = _find_deno()
    if not deno:
        print("ERR: deno introuvable parmi", DENO_CANDIDATES)
        return 2
    print(f"[deno_check] deno={deno}")
    print(f"[deno_check] target={abs_target}")
    try:
        r = subprocess.run(
            [deno, "check", abs_target],
            capture_output=True, text=True, cwd=ROOT, timeout=120,
        errors="replace")
    except Exception as exc:  # noqa: BLE001
        print(f"ERR: deno check failed to run: {exc}")
        return 3
    print(f"[deno_check] rc={r.returncode}")
    out = (r.stdout or "")[-3000:]
    err = (r.stderr or "")[-3000:]
    if out:
        print("--- stdout ---\n" + out)
    if err:
        print("--- stderr ---\n" + err)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
