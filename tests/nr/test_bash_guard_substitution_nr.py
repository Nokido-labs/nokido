"""Tests NR : une substitution de commande perd le benefice de l'approbation.

Lecon tiree de l'ingestion de `openai/codex` (2026-08-30). Ses gabarits
d'approbation (`codex-rs/prompts/templates/permissions/`) posent qu'une regle
d'auto-approbation n'est PAS evaluee quand la commande porte une substitution,
une variable d'environnement ou un wildcard, « to limit the scope of what an
approved rule allows ».

`bash_guard` souffrait du meme trou : son routage validait un segment sur
`startswith("git ")` sans jamais examiner le reste, si bien que
`git log --format=$(...)` etait approuve -- alors que la substitution s'execute
AVANT git. L'approbation portait sur le nom du binaire, pas sur ce qui allait
reellement tourner.

Test d'EFFET : on lance le hook TEL QU'IL EST INVOQUE (JSON sur stdin, code de
sortie lu). Importer `bash_guard` ne marche pas -- c'est un hook, il sort au
niveau module -- et recopier sa fonction validerait la copie, pas le garde.
Hermetique : aucun acces au working tree, au reseau ni a une base.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _ROOT / "tools" / "bash_guard.py"

AUTORISE = 0
BLOQUE = 2


def verdict(commande: str) -> int:
    """Code de sortie du hook pour cette commande. 0 = laisse passer, 2 = bloque."""
    p = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps({"tool_input": {"command": commande}}),
        capture_output=True,
        text=True,
        errors="replace",  # anti-regression incident 47 Go : jamais de mode texte nu
        timeout=60,
    )
    return p.returncode


pytestmark = pytest.mark.skipif(not _HOOK.exists(), reason="bash_guard.py absent")

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.39)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = [pytestmark, pytest.mark.timeout(120)]


# --- le trou ferme ---------------------------------------------------------
def test_git_avec_substitution_dollar_est_bloque():
    """LE test : le prefixe `git ` ne suffit plus a approuver le segment."""
    assert verdict("git log --format=$(whoami)") == BLOQUE


def test_git_avec_backticks_est_bloque():
    assert verdict("git log `whoami`") == BLOQUE


def test_echo_avec_substitution_est_bloque():
    """`echo` est un marqueur inoffensif ; `echo $(...)` ne l'est pas."""
    assert verdict("echo $(id)") == BLOQUE


def test_gh_avec_substitution_est_bloque():
    assert verdict("gh api $(cat cible.txt)") == BLOQUE


# --- ce qui doit continuer a passer ----------------------------------------
def test_git_simple_reste_autorise():
    assert verdict("git status") == AUTORISE


def test_git_avec_options_reste_autorise():
    assert verdict("git -c safe.directory=* -C /repo log -1 --format=%H") == AUTORISE


def test_gh_simple_reste_autorise():
    assert verdict("gh run list") == AUTORISE


# --- precision : pas de faux positif sur l'expansion de variable -----------
def test_expansion_de_variable_nest_pas_une_substitution():
    """`${VAR}` n'execute rien : le refuser ferait crier le garde a faux.

    La fuite de secret par variable est la charge de la couche 1, pas du
    routage. Un garde qui crie a faux se fait desarmer.
    """
    assert verdict("git log --format=${FMT}") == AUTORISE


# --- l'exception documentee -------------------------------------------------
def test_curl_vers_le_hub_garde_le_droit_a_la_substitution():
    """RULES_SHARED prescrit cette forme pour ne JAMAIS afficher le jeton.

    L'interdire pousserait a ecrire le secret en clair : le remede serait pire
    que le mal. C'est le SEUL passthrough ou la substitution reste admise.
    """
    cmd = (
        'curl -s http://127.0.0.1:8766/api/x '
        '-H "Authorization: Bearer $(sed -n p cfg)"'
    )
    assert verdict(cmd) == AUTORISE
