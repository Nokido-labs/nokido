#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_orphan_branches.py — le patrimoine coince dans les branches.

POURQUOI. Le census (Phase 7) a laisse 114 disparitions « a motif inconnu » :
des fichiers nes dans l'histoire, absents du HEAD, sans commit de suppression
trace. Hypothese : ils vivent dans des branches JAMAIS mergees (hackathon, wip,
experimentations abandonnees). Un fichier d'une branche divergente n'a pas de
commit `D` sur la branche principale — il « disparait » sans trace de mort.

Cet outil liste, par depot, les branches non mergees dans la principale, les
commits qu'elles portent en propre, et les fichiers de CODE qu'elles seules
contiennent (nes dans la branche, absents du HEAD principal). LECTURE SEULE.

Sortie : sandbox/orphan_branches.json + resume.
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "observabilite/audit : le patrimoine coince dans les branches (census phase 7)"  # organe declare le 2026-09-06 (audit de raccordement)

import collections
import os

# Socle commun : la decouverte de depots et le wrapper git etaient recopies a
# l'identique ici et dans forge_history_census (cliquet de duplication, 18/08).
from nokido_agent.tools.forge_archeo_socle import ROOT, decouvrir_depots, ecrire_json
from nokido_agent.tools.forge_archeo_socle import git as _git

# Volontairement PLUS restreint que CODE_EXT du socle : une branche orpheline
# se juge sur du code compilable/executable, pas sur ses .sql ni ses .json.
CODE_EXT = {".py", ".ps1", ".ts", ".tsx", ".js", ".rs", ".go", ".c", ".cpp",
            ".swift", ".java", ".sh"}
PRINCIPALES = ("main", "master", "alpha", "beta")


def decouvrir():
    """Depots analysables. Le super-repo est exclu : ses branches sont celles
    des submodules, deja comptees une fois chacune."""
    return decouvrir_depots(inclure_workspace=False)[0]


def principale(depot):
    """La branche de TRAVAIL courante (HEAD), pas 'main' en dur.

    Nokido developpe sur `alpha` ; comparer a un `main` en retard faisait
    ressortir alpha et beta — branches vivantes — comme orphelines avec des
    milliers de faux fichiers exclusifs. La reference honnete est le HEAD."""
    cur = _git(depot, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if cur and cur != "HEAD":
        return cur
    refs = _git(depot, "branch", "-a", "--format=%(refname:short)").split()
    for p in PRINCIPALES:
        for r in refs:
            if r == p or r.endswith("/" + p):
                return p
    return refs[0] if refs else "HEAD"


def analyser(nom, depot):
    princ = principale(depot)
    brut = _git(depot, "branch", "-a", "--no-merged", princ,
                "--format=%(refname:short)")
    # On ignore les miroirs distants du travail courant (origin/<princ>,
    # codeberg/...) : ce ne sont pas des branches orphelines, juste des remotes.
    branches = [b.strip() for b in brut.splitlines()
                if b.strip() and "HEAD" not in b and b.strip() != princ
                and not b.strip().endswith("/" + princ)]
    res = {"principale": princ, "branches": {}}
    for br in branches:
        # commits portes en propre par la branche
        commits = _git(depot, "log", "%s..%s" % (princ, br), "--no-merges",
                       "--format=%h %ad %s", "--date=short").splitlines()
        # fichiers de code AJOUTES dans la branche et absents du HEAD principal
        ajouts = _git(depot, "diff", "--name-only", "--diff-filter=A",
                      princ + "..." + br).splitlines()
        vivants = set(l.strip() for l in
                      _git(depot, "ls-tree", "-r", princ, "--name-only").splitlines())
        exclusifs = sorted(
            f.strip() for f in ajouts
            if f.strip() and os.path.splitext(f)[1].lower() in CODE_EXT
            and f.strip() not in vivants)
        if not commits and not exclusifs:
            continue
        res["branches"][br] = {
            "commits_n": len(commits),
            "commits": commits[:8],
            "fichiers_code_exclusifs_n": len(exclusifs),
            "fichiers_code_exclusifs": exclusifs[:60],
        }
    return res


def _rendre(out):
    t = out["total"]
    print("\n[orphelines] %s branches non mergees, %s fichiers de code coinces"
          % (t["branches_orphelines"], t["fichiers_code_coinces"]))
    for nom, r in out["depots"].items():
        for br, info in sorted(r["branches"].items(),
                               key=lambda kv: -kv[1]["fichiers_code_exclusifs_n"]):
            if info["fichiers_code_exclusifs_n"]:
                print("  %-16s %-34s %3s commits | %3s fichiers exclusifs"
                      % (nom, br[:34], info["commits_n"],
                         info["fichiers_code_exclusifs_n"]))


def recenser(depots):
    """Un dict depot->chemin -> le rapport complet des branches orphelines."""
    out = {"depots": {}}
    branches = fichiers = 0
    for nom, chemin in depots.items():
        print("[orphelines] %s ..." % nom, flush=True)
        r = analyser(nom, chemin)
        out["depots"][nom] = r
        for info in r["branches"].values():
            branches += 1
            fichiers += info["fichiers_code_exclusifs_n"]
    out["total"] = {"branches_orphelines": branches,
                    "fichiers_code_coinces": fichiers}
    return out


def main():
    out = recenser(decouvrir())
    _rendre(out)
    print("[orphelines] ecrit : %s"
          % ecrire_json(os.path.join(ROOT, "sandbox", "orphan_branches.json"), out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
