#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_recover_from_branch.py — recuperer un fichier d'une branche.

Le census des branches (forge_orphan_branches) a montre que le seul patrimoine
unique coince dans une branche non mergee est dans `hackathon/v17-microsoft` :
deux outils CTF/recon. Cet outil les extrait FIDELEMENT (legacy preserve, regle
owner) vers la zone de review, avec un en-tete de provenance — sans rien
modifier a la logique, qu'on ne peut pas tester ici (chemins Exegol /workspace/).

Ecrit sous sandbox/recovery/branches/ (revue, hors suivi). La promotion vers un
dossier suivi reste une decision owner, apres modernisation.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/git : recuperer un fichier d'une branche orpheline"  # organe declare le 2026-09-06 (audit de raccordement)

import os
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "sandbox", "recovery", "branches")

# (ref, chemin_source, note d'etat)
RECOVERIES = [
    ("origin/hackathon/v17-microsoft", "tools/laforge_netmap.py",
     "TUI curses de cartographie reseau ; chemins /workspace/ Exegol en dur"),
    ("origin/hackathon/v17-microsoft", "tools/laforge_pipeline.py",
     "Orchestrateur pentest 5 phases ; refs regles LaForge #30-#35, agent Exegol"),
]


def _show(ref: str, chemin: str) -> str:
    p = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", ROOT, "show", "%s:%s" % (ref, chemin)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    return p.stdout if p.returncode == 0 else ""


def main() -> int:
    os.makedirs(DEST, exist_ok=True)
    ecrits = 0
    for ref, src, note in RECOVERIES:
        contenu = _show(ref, src)
        if not contenu:
            print("[recover] VIDE %s:%s" % (ref, src))
            continue
        entete = (
            "# --- RECUPERE d'une branche non mergee le %s ---\n"
            "# Provenance : %s:%s\n"
            "# Etat : %s\n"
            "# Legacy preserve tel quel (regle owner). NON teste, NON branche.\n"
            "# Moderniser avant activation ; ne PAS promouvoir en suivi sans revue.\n\n"
            % (time.strftime("%Y-%m-%d"), ref, src, note)
        )
        cible = os.path.join(DEST, os.path.basename(src))
        with open(cible, "w", encoding="utf-8") as fh:
            fh.write(entete + contenu)
        ecrits += 1
        print("[recover] %s -> %s (%d octets)"
              % (src, os.path.relpath(cible, ROOT), len(contenu)))
    print("[recover] %d/%d extraits sous %s" % (ecrits, len(RECOVERIES),
                                                os.path.relpath(DEST, ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
