# -*- coding: utf-8 -*-
"""Traque QUI repose `llama.wanted` en boucle.

Le capteur de couplage nomme l'emetteur (`forge_llm_ondemand._poser_drapeau`,
279 poses) mais pas le LANCEUR : le module n'est appele depuis aucun code Python
(verifie le 2026-08-02 et redit ce jour), il n'est ni dans `services.toml` ni
dans le planificateur. Il est donc lance en ligne de commande par quelqu'un.

Methode : surveiller le mtime du drapeau et, a l'instant OU il bouge,
photographier les process python vivants AVEC leur parent. Un poseur qui ecrit
puis sort trop vite serait manque -- on echantillonne donc serre et on rapporte
aussi les process de moins de 60 s, dont la naissance encadre la pose.

    run action=trusted_script path=tools/forge_llm_ondemand_traqueur.py \
        --script_args="--secondes 90"
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
DRAPEAU = _ROOT / "sandbox" / "llama.wanted"

PS_SNAP = r"""
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='powershell.exe' OR Name='pwsh.exe' OR Name='cmd.exe'" |
  ForEach-Object {
    $par = $null
    try { $par = (Get-CimInstance Win32_Process -Filter ("ProcessId=" + $_.ParentProcessId) -ErrorAction SilentlyContinue) } catch {}
    $cl = if ($_.CommandLine) { $_.CommandLine } else { '(cmdline illisible)' }
    $pn = if ($par) { $par.Name } else { '?' }
    $pc = if ($par -and $par.CommandLine) { $par.CommandLine } else { '' }
    $age = 0
    try { $age = [int]((Get-Date) - $_.CreationDate).TotalSeconds } catch {}
    '{0}|{1}|{2}|{3}|{4}|{5}' -f $_.ProcessId, $age, $cl.Substring(0,[Math]::Min(180,$cl.Length)), $_.ParentProcessId, $pn, $pc.Substring(0,[Math]::Min(140,$pc.Length))
  }
"""


def _snap() -> list:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", PS_SNAP],
                           capture_output=True, text=True, errors="replace", timeout=60)
        return [l for l in (r.stdout or "").splitlines() if "|" in l]
    except Exception as e:  # noqa: BLE001
        print("  snapshot KO: %s" % type(e).__name__, flush=True)
        return []


def _interessant(ligne: str) -> bool:
    bas = ligne.lower()
    return any(m in bas for m in ("ondemand", "llama", "keeper", "wanted", "embed"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Traque le reposeur de llama.wanted")
    ap.add_argument("--secondes", type=int, default=90)
    args = ap.parse_args()

    if not DRAPEAU.is_file():
        print("drapeau absent : %s" % DRAPEAU, flush=True)
        return 2
    ref = DRAPEAU.stat().st_mtime
    print("drapeau     : %s" % DRAPEAU.name, flush=True)
    print("age initial : %.0f s" % (time.time() - ref), flush=True)
    print("surveillance %d s...\n" % args.secondes, flush=True)

    fin = time.time() + args.secondes
    bouge = False
    while time.time() < fin:
        try:
            m = DRAPEAU.stat().st_mtime
        except Exception:  # noqa: BLE001 - drapeau efface sous nos pieds
            m = ref
        if m != ref:
            bouge = True
            print("=== DRAPEAU REPOSE a %.1f (photo des process) ===" % m, flush=True)
            for l in _snap():
                ch = l.split("|")
                age = ch[1] if len(ch) > 1 else "?"
                if _interessant(l) or (age.isdigit() and int(age) < 60):
                    print("  pid=%-7s age=%-5ss %s" % (ch[0], age, ch[2][:150]), flush=True)
                    print("      parent pid=%-7s %s %s" % (
                        ch[3] if len(ch) > 3 else "?", ch[4] if len(ch) > 4 else "?",
                        (ch[5] if len(ch) > 5 else "")[:120]), flush=True)
            ref = m
        time.sleep(1.0)

    if not bouge:
        print("aucune repose observee sur la fenetre -- le cycle est plus long "
              "que %d s (mesure : ~300 s). Relancer plus longtemps." % args.secondes,
              flush=True)
        print("\n=== A DEFAUT : process candidats VIVANTS ===", flush=True)
        for l in _snap():
            if _interessant(l):
                ch = l.split("|")
                print("  pid=%-7s age=%-6ss %s" % (ch[0], ch[1], ch[2][:150]), flush=True)
                print("      parent pid=%-7s %s %s" % (
                    ch[3] if len(ch) > 3 else "?", ch[4] if len(ch) > 4 else "?",
                    (ch[5] if len(ch) > 5 else "")[:120]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
