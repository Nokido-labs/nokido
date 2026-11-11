"""NR 6/11 : git et gh passent par Nokido. Le passthrough approuvait le NOM du binaire.

Test d'EFFET : le hook est lance tel qu'il est invoque (voir test_bash_guard_substitution_nr).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_VOISIN = Path(__file__).with_name("test_bash_guard_substitution_nr.py")
_spec = importlib.util.spec_from_file_location("_voisin_bash_guard", _VOISIN)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
verdict = _mod.verdict
AUTORISE, BLOQUE = _mod.AUTORISE, _mod.BLOQUE


@pytest.mark.parametrize("commande", [
    "git push",
    "git push origin alpha",
    "git -C /x push origin alpha",
    'git -c safe.directory=* -C "C:/a b" push origin alpha',
    "git push --force origin alpha",
    "git lfs push origin",
    "git subtree push --prefix x origin y",
    'git commit --no-verify -m "x"',
    'git commit --no-ver -m "x"',
    'git commit -n -m "x"',
    'git commit -anm "x"',
    "git push --no-verify --dry-run",
    "git -c core.hooksPath=/dev/null commit -m x",
    "git -c alias.x=push x",
    "git config core.hooksPath /dev/null",
    "git status && git push",
    "gh repo create x --public",
    "gh pr create --title x",
    "gh pr merge 12",
    "gh workflow run ci.yml",
    "gh run rerun 12",
    "gh secret list",
    "gh variable list",
    "gh api -X POST repos/a/b/issues",
    "gh api --method=DELETE repos/a/b",
    "gh api repos/a/b/issues -f title=x",
    "gh api graphql -f query=x",
    "gh auth login",
])
def test_ecriture_ou_contournement_bloque(commande):
    assert verdict(commande) == BLOQUE, commande


@pytest.mark.parametrize("commande", [
    "git status",
    "git log -n 5 --oneline",
    "git push --dry-run origin alpha",
    "git push -n origin alpha",
    'git commit -m "parle de git push et de --no-verify"',
    'git -c safe.directory=* -C "C:/a b" commit -q -m "x" -- a.py',
    "git add a.py",
    "git config core.hooksPath",
    "gh pr view 12",
    "gh pr list --repo a/b",
    "gh pr checks 12",
    "gh run view 12 --log",
    "gh run list",
    "gh repo view a/b",
    "gh auth status",
    "gh api repos/a/b",
    "gh api -X GET repos/a/b",
    "gh search code x",
    "gh --version",
])
def test_lecture_et_commit_ordinaire_passent(commande):
    assert verdict(commande) == AUTORISE, commande
