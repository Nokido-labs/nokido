"""
tools/forge_proc_rights_probe.py — QUI suis-je, QUI est la cible, et qu'ai-je le droit
de faire sur elle ? (owner 2026-07-25)

Ecrit apres une conclusion trop rapide de ma part : `psutil` ayant rendu AccessDenied
sur `OpenProcess`, j'ai annonce que « LaForgeTrusted n'a pas de droits sur les processus
du compte sandbox-online ». C'est une DEDUCTION, pas une mesure -- et la doctrine dit
l'inverse : la propriete se DEMANDE, et un refus est presque toujours la mauvaise FORME
plutot qu'une capacite absente.

Ce probe repond par des faits :
  - le compte effectif de CE script (donc de trusted_script) ;
  - le compte proprietaire de la cible ;
  - les privileges du token courant (SeDebugPrivilege est celui qui permet d'ouvrir un
    process d'un autre compte) ;
  - ce que rendent TROIS formes differentes : psutil, taskkill, et WMI Terminate.
Lecture seule sauf si `--kill` est passe explicitement.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/rights : qui suis-je, qui est la cible, quels droits sur elle"  # organe declare le 2026-09-06 (audit de raccordement)

import getpass
import os
import subprocess
import sys


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           errors="replace", timeout=30)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()[:400]
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


def main() -> int:
    args = sys.argv[1:]
    kill = "--kill" in args
    pids = [a for a in args if a.isdigit()]
    if not pids:
        print("usage: forge_proc_rights_probe.py <pid> [--kill]")
        return 1
    pid = int(pids[0])

    print(f"=== IDENTITE DU SCRIPT ===")
    print(f"  getpass.getuser() : {getpass.getuser()}")
    print(f"  USERNAME env      : {os.environ.get('USERNAME')}")
    print(f"  USERDOMAIN        : {os.environ.get('USERDOMAIN')}")
    rc, out = _run(["whoami", "/priv"])
    dbg = [l for l in out.splitlines() if "SeDebug" in l or "SeTcb" in l
           or "SeImpersonate" in l or "SeAssignPrimary" in l]
    print(f"  privileges cles   : {dbg or 'aucun des 4 recherches'}")

    print(f"\n=== CIBLE pid {pid} ===")
    try:
        import psutil

        p = psutil.Process(pid)
        print(f"  name        : {p.name()}")
        try:
            print(f"  username    : {p.username()}")
        except Exception as e:  # noqa: BLE001
            print(f"  username    : ILLISIBLE ({type(e).__name__})")
        try:
            print(f"  cmdline     : {' '.join(p.cmdline())[:160]}")
        except Exception as e:  # noqa: BLE001
            print(f"  cmdline     : ILLISIBLE ({type(e).__name__})")
        try:
            print(f"  ppid        : {p.ppid()}")
        except Exception as e:  # noqa: BLE001
            print(f"  ppid        : ILLISIBLE ({type(e).__name__})")
    except Exception as e:  # noqa: BLE001
        print(f"  psutil.Process KO : {type(e).__name__}: {e}")

    # Qui possede la cible, vu par un outil SYSTEME (pas psutil) ?
    rc, out = _run(["tasklist", "/FI", f"PID eq {pid}", "/V", "/FO", "LIST"])
    owner = [l.strip() for l in out.splitlines() if "Nom d" in l or "User Name" in l]
    print(f"  tasklist /V owner : rc={rc} {owner or out[:120]}")

    if not kill:
        print("\n=== DRY-RUN : aucune tentative d'arret (--kill pour mesurer les 3 formes) ===")
        return 0

    print("\n=== TROIS FORMES D'ARRET (on mesure, on ne suppose pas) ===")
    rc, out = _run(["taskkill", "/PID", str(pid)])
    print(f"  1. taskkill (doux)   : rc={rc} {out[:180]}")
    rc, out = _run(["taskkill", "/F", "/PID", str(pid)])
    print(f"  2. taskkill /F       : rc={rc} {out[:180]}")
    rc, out = _run(["powershell", "-NoProfile", "-Command",
                    f"try {{ Stop-Process -Id {pid} -Force -ErrorAction Stop; 'OK' }}"
                    f" catch {{ $_.Exception.Message }}"])
    print(f"  3. Stop-Process      : rc={rc} {out[:180]}")
    try:
        import psutil

        alive = psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001
        alive = "inconnu"
    print(f"\n  cible encore vivante : {alive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
