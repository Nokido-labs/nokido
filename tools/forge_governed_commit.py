#!/usr/bin/env python3
"""
forge_governed_commit.py — Commit gouverne, appelable par un agent ring 1.

POURQUOI ce script existe (constate le 2026-08-12, apres avoir delegue a tort) :
un agent ne peut PAS committer autrement.
  - `run action=shell` s'execute en LaForgeSbxOffline, non proprietaire du depot
    -> git refuse : `fatal: detected dubious ownership in repository`.
  - `run action=github` et `run action=python` exigent le ring 0 ; un agent est ring 1.
  - `run action=trusted_script` tourne en LaForgeTrusted, qui a l'ecriture depot,
    mais n'accepte QUE des scripts identiques a HEAD -> il faut donc un committeur
    DEJA commite. Ce fichier est ce committeur.

Le pendant existait deja pour la publication (`forge_push_sovereign.py --push`) ;
il manquait l'etage d'avant. Sequence complete cote agent :

    run action=trusted_script path=tools/forge_governed_commit.py
        script_args="--message 'fix(x): sujet' --files tools/a.py .claude/b.json"
    run action=trusted_script path=tools/forge_push_sovereign.py
        script_args="--branch alpha --push"

AUCUN contournement de garde : les hooks de pre-commit (scan de secrets, gate
d'alignement) tournent normalement. `--no-verify` n'est pas expose, volontairement.
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : commit gouverne pour un agent ring 1"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_S = 180


def _git(*args: str) -> tuple[int, str]:
    """git -C <repo> ... ; rend (rc, sortie fusionnee et strippee).

    `-c safe.directory=<repo>` est INDISPENSABLE : le depot appartient a l'owner,
    ce script tourne en LaForgeTrusted, et git refuse alors avec
    `fatal: detected dubious ownership` (constate 2026-08-12). La garde safe.directory
    protege contre le depot d'un AUTRE utilisateur dans un repertoire partage ; ici
    LaForgeTrusted est un compte de service du meme proprietaire, deliberement
    autorise en ecriture sur ce depot. On leve donc le controle PAR COMMANDE, jamais
    par `--global` : la portee reste ce depot, et rien n'est modifie sur le poste.
    """
    try:
        p = subprocess.run(
            ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), *args],
            capture_output=True, text=True, errors="replace", timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return 124, f"timeout {TIMEOUT_S}s sur: git {' '.join(args)}"
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Commit gouverne (hooks actifs).")
    ap.add_argument("--message", required=True, help="sujet du commit")
    ap.add_argument("--body", action="append", default=[],
                    help="paragraphe de corps, repetable")
    ap.add_argument("--files", nargs="+", required=True,
                    help="chemins a stager, relatifs a la racine du depot")
    a = ap.parse_args()

    rc, out = _git("add", "--", *a.files)
    if rc != 0:
        print(f"[commit] add rc={rc} : {out}", flush=True)
        return 1

    _, staged = _git("diff", "--cached", "--name-only")
    if not staged:
        _, st = _git("status", "--short")
        print("[commit] RIEN de stage -- aucun des fichiers demandes ne differe de HEAD.",
              flush=True)
        print(f"[commit] status :\n{st}", flush=True)
        return 1
    print(f"[commit] stage :\n{staged}", flush=True)

    argv = ["commit", "-m", a.message]
    for para in a.body:
        argv += ["-m", para]
    rc, out = _git(*argv)
    print(f"[commit] rc={rc}\n{out}", flush=True)
    if rc != 0:
        return 1

    _, head = _git("log", "--oneline", "-1")
    print(f"[commit] HEAD = {head}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
