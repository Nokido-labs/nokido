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

# Methode A (decision owner 20/10) : le commit joue les NR IMPACTES par ses fichiers et refuse sur un rouge.
# Le SELECTEUR est celui de `--impacte` (forge_ci_selection.selectionner), jamais un second.
sys.path.insert(0, str(ROOT / "tools"))
try:
    from forge_ci_selection import TOUT, selectionner
except ImportError:  # selecteur absent -> evaluer_nr refusera (jamais "accepte par defaut")
    TOUT, selectionner = "TOUT", None

# Plafond : 30 fichiers NR. Un NR dure ~2-5 s (suite pure, hors reseau) -> ~1-2 min, sous TIMEOUT_NR_S ;
# au-dela le commit bloquerait l'agent plus longtemps que son appel (timeout MCP) : on refuse avec la
# commande a jouer en run_job plutot que de committer sans avoir joue.
PLAFOND_NR = 30
TIMEOUT_NR_S = 600
_CHARGER = object()


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


def _lancer_pytest(retenus):
    """(rc, sortie) du pytest sur les NR retenus ; timeout -> rc 124."""
    try:
        p = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-rf", "--no-header", "-p", "no:cacheprovider", *retenus],
            capture_output=True, text=True, errors="replace", timeout=TIMEOUT_NR_S, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return 124, f"timeout {TIMEOUT_NR_S}s"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _commande_run_job(fichiers):
    liste = "sandbox/impacte_commit.txt"
    return (f"ecrire {liste} (un fichier par ligne : {', '.join(fichiers[:5])}) puis "
            f"run action=run_job script=tools/ci_local.py "
            f"script_args=\"--impacte --impacte-fichiers {liste}\"")


def evaluer_nr(fichiers, pure_tests=_CHARGER, lancer=None, lire=None, plafond=PLAFOND_NR):
    """(ok, message). Refuse sur tout doute : selection illisible, plafond, rouge, runner mort."""
    fichiers = [f for f in (fichiers or []) if f]
    if selectionner is None:
        return False, "REFUS : selection illisible (forge_ci_selection introuvable) -- pas de commit par defaut."
    motif = "liste absente"
    if pure_tests is _CHARGER:
        try:
            from ci_local import PURE_TESTS as pure_tests
        except Exception as e:  # noqa: BLE001
            pure_tests, motif = None, type(e).__name__
    if pure_tests is None:
        return False, f"REFUS : selection illisible (PURE_TESTS indisponible : {motif}) -- pas de commit par defaut."
    if lire is None:
        present = [t for t in pure_tests if (ROOT / t).exists()]
        lire = lambda p: (ROOT / p).read_text(encoding="utf-8", errors="replace")  # noqa: E731
    else:
        present = list(pure_tests)
    rapport = selectionner(present, fichiers, "PRESENT", lire=lire)
    retenus = rapport["retenus"]
    if rapport["mode"] == TOUT:
        return False, (f"REFUS : selection non reduite ({rapport['raison']}) : {len(retenus)} NR a jouer. "
                       f"Jouer en run_job : {_commande_run_job(fichiers)}")
    if len(retenus) > plafond:
        return False, (f"REFUS : plafond depasse, {len(retenus)} NR impactes > {plafond}. "
                       f"Jouer en run_job : {_commande_run_job(fichiers)}")
    if not retenus:
        return True, "0 NR impacte par ces fichiers -- rien a jouer."
    rc, sortie = (lancer or _lancer_pytest)(retenus)
    if rc == 0:
        return True, f"{len(retenus)} NR impactes verts."
    rouges = [l.split(" ", 1)[1].split(" - ")[0].strip() for l in sortie.splitlines() if l.startswith("FAILED ")]
    if rouges:
        return False, f"REFUS : NR impacte(s) ROUGE(S) : {', '.join(rouges)}"
    return False, f"REFUS : NR impactes non verts (rc={rc}), aucun nom lisible : {sortie[-300:]}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Commit gouverne (hooks actifs).")
    ap.add_argument("--message", required=True, help="sujet du commit")
    ap.add_argument("--body", action="append", default=[],
                    help="paragraphe de corps, repetable")
    ap.add_argument("--files", nargs="+", required=True,
                    help="chemins a stager, relatifs a la racine du depot")
    a = ap.parse_args()

    ok, msg = evaluer_nr(a.files)
    print(f"[commit] NR impactes : {msg}", flush=True)
    if not ok:
        return 1

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
