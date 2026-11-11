"""NR -- git diff / git show non bornes refuses, formes bornees permises (levier (c), 9/11).

Mesure 9/11 (session a 720K jetons) : sorties natives Bash 3,8 % du cout, git diff/show
rapatries en entier (CRLF compris). On ne coupe pas l'acces : la forme bornee reste permise
(--stat & co, chemin cible apres `--`, blob `rev:chemin`, `-s`).
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from app.forge_git_shell_guard import refus_git_gh  # noqa: E402

C = 'git -c safe.directory=* -C "C:/x/Nokido" '


def test_diff_et_show_nus_refuses_avec_forme_permise():
    for seg in (C + "diff", C + "diff HEAD~3", C + "show 3aceedf75", "git diff --cached"):
        motif = refus_git_gh(seg)
        assert motif and "--stat" in motif, seg


def test_formes_bornees_permises():
    for seg in (C + "diff --stat", C + "diff --name-only HEAD~1", C + "show --stat 3aceedf75",
                C + "diff HEAD~1 -- tools/x.py", C + "show 3aceedf75:docs/a.md",
                C + "show -s --format=%h 3aceedf75", "git diff --shortstat", "git diff --quiet",
                "git diff A B > C:/tmp/p.patch", "git diff A B >> p.patch"):
        assert refus_git_gh(seg) is None, seg


def test_autres_sous_commandes_inchangees():
    for seg in (C + "log --oneline -5", C + "status --short", C + "branch -a --contains 3aceedf75"):
        assert refus_git_gh(seg) is None, seg
