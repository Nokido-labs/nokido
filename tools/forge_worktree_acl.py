#!/usr/bin/env python3
"""forge_worktree_acl.py -- droit de TRAVERSEE des worktrees pour le compte hors ligne (owner 6/11).

Cause mesuree a l'icacls le 6/11 : `LaForgeSbxOffline` est en (R) sur nokido_worktrees, sans droit d'execution
sur les dossiers. pytest y tourne car le processus y demarre ; `git status` rend `rc 128`, git ne peut pas s'y placer
(`cannot change to ... Permission denied`). Remede minimal : (R) devient (RX). Ni ecriture ni reseau en plus : ce
compte lisait deja ces fichiers et lancait python dessus.

Securite : cibles limitees a la racine des worktrees et a ses arbres git directs ; aucune recursion ; essai a blanc
par defaut ; `--retirer` rend le droit d'origine. Trace : chaque cible ecrit avant, apres, rc, utilisateur et date
dans logs/worktree_acl.jsonl. Se lance sous le compte de l'owner, seul a pouvoir changer ces droits.

Usage : forge_worktree_acl.py [--appliquer | --retirer]
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/acl : traversee tracee des worktrees pour le compte hors ligne"

import argparse
import getpass
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _racine_donnees():
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return ROOT
    return racine_donnees()


RACINE = ROOT.parent / "nokido_worktrees"
JOURNAL = _racine_donnees() / "logs" / "worktree_acl.jsonl"
COMPTE = "LaForgeSbxOffline"
DROITS = {"appliquer": "(OI)(CI)(RX)", "retirer": "(OI)(CI)(R)"}


def cibles(racine=RACINE) -> list:
    """La racine des worktrees et ses arbres git directs, rien d'autre."""
    r = Path(racine)
    if r.name != "nokido_worktrees" or not r.is_dir():
        raise ValueError("racine inattendue : %s" % r)
    return [r] + sorted(p for p in r.iterdir() if p.is_dir() and (p / ".git").exists())


def commande(cible, mode: str) -> list:
    return ["icacls", str(cible), "/grant:r", "%s:%s" % (COMPTE, DROITS[mode])]


def _lire(cible) -> str:
    r = subprocess.run(["icacls", str(cible)], capture_output=True, text=True, errors="replace", timeout=30)
    lignes = [x.strip() for x in (r.stdout or "").splitlines() if COMPTE in x]
    return " ; ".join(lignes) or "ILLISIBLE rc=%s" % r.returncode


def executer(racine=RACINE, mode: str = "essai", journal=JOURNAL) -> int:
    """0 si tout est fait (ou essai), 1 si une cible a echoue. Toute cible est journalisee, echec compris."""
    echecs = 0
    journal = Path(journal)
    journal.parent.mkdir(parents=True, exist_ok=True)
    for c in cibles(racine):
        ligne = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "utilisateur": getpass.getuser(), "mode": mode,
                 "cible": str(c), "avant": _lire(c)}
        if mode != "essai":
            r = subprocess.run(commande(c, mode), capture_output=True, text=True, errors="replace", timeout=30)
            ligne.update(rc=r.returncode, apres=_lire(c))
            echecs += r.returncode != 0
        with journal.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        print(c.name, mode, ligne.get("rc", "-"), "|", ligne.get("apres", ligne["avant"])[:110])
    return 1 if echecs else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--appliquer", action="store_true")
    g.add_argument("--retirer", action="store_true")
    a = ap.parse_args()
    mode = "appliquer" if a.appliquer else "retirer" if a.retirer else "essai"
    rc = executer(mode=mode)
    print("BILAN: %s rc=%d, journal %s" % (mode, rc, JOURNAL))
    return rc


if __name__ == "__main__":
    sys.exit(main())
