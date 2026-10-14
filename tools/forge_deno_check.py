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
import tempfile

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
    except Exception as exc:  # noqa: BLE001 -- dernier repli : on le DIT, l'appelant conclura « deno introuvable »
        print(f"[deno_check] repli processus illisible ({type(exc).__name__}: {exc}) -- deno non localise par ce chemin")
    return None


def _inscriptible(dossier: str | None) -> bool:
    """Le dossier existe (ou se cree) ET ce compte peut y ecrire -- prouve par une ecriture, jamais deduit."""
    if not dossier:
        return False
    try:
        os.makedirs(dossier, exist_ok=True)
        with tempfile.TemporaryFile(dir=dossier):
            return True
    except OSError:
        return False


def _env_deno() -> dict:
    """Mesure 2026-10-12 : sous LaForgeTrusted, l'environnement herite place le cache deno dans le profil de l'owner
    (AppData\\Local\\deno), en lecture seule pour ce compte -- `deno check` mourait a la mise en cache (os error 5).
    Un DENO_DIR inscriptible est garde ; sinon un cache propre au compte, dans son dossier temporaire inscriptible."""
    env = dict(os.environ)
    if not _inscriptible(env.get("DENO_DIR")):
        env["DENO_DIR"] = os.path.join(tempfile.gettempdir(), "nokido_deno_dir")
        print(f"[deno_check] DENO_DIR={env['DENO_DIR']} (cache propre a ce compte)")
    return env


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
            capture_output=True, text=True, cwd=ROOT, timeout=120, env=_env_deno(),
        errors="replace")
    except PermissionError as exc:
        # Mesure 2026-10-12 : LaForgeTrusted n'executait plus ~/.deno/bin/deno.exe (WinError 5). `deno upgrade`
        # REMPLACE l'exe : une autorisation posee sur l'ancien fichier part avec lui. Le remede tient s'il est
        # HERITABLE et pose sur le dossier -- geste owner, c'est son profil. Rien n'a ete verifie : ILLISIBLE, pas OK.
        dossier = os.path.dirname(os.path.dirname(deno)) if deno.lower().endswith("deno.exe") else os.path.dirname(deno)
        print(f"ILLISIBLE: le compte {os.environ.get('USERNAME', '?')} ne peut pas executer {deno} ({exc}).")
        print("  Rien n'a ete verifie. Remede (owner, dans son terminal, une fois -- survit aux `deno upgrade`) :")
        print(f'  icacls "{dossier}" /grant "LaForgeTrusted:(OI)(CI)RX"')
        return 4
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
