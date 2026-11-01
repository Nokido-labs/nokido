"""NR du banc de traduction : masquage/restauration des identifiants et comptage (stdlib seule, aucun modele)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools import forge_bench_traduction as b  # noqa: E402

TEXTE = (
    "Lance `git status` puis edite %USERPROFILE%\\Nokido\\app\\x.py avec --dry-run, "
    "appelle mcp__nokido__hub sur le commit 544b3dc1a2bd (job_id job_ab12cd34).\n"
    "```python\nprint('bonjour')\n```\nFin."
)


def test_masquage_retire_les_identifiants():
    masque, table = b.masquer(TEXTE)
    for ident in ("git status", "mcp__nokido__hub", "--dry-run", "544b3dc1a2bd", "x.py", "print('bonjour')"):
        assert ident not in masque
    assert len(table) >= 6


def test_restauration_identique():
    masque, table = b.masquer(TEXTE)
    assert b.restaurer(masque, table) == TEXTE


def test_taux_intacts_total_puis_degrade():
    masque, table = b.masquer(TEXTE)
    assert b.taux_intacts(masque, table) == (len(table), len(table))
    casse = masque.replace(next(iter(table)), "", 1)
    ok, tot = b.taux_intacts(casse, table)
    assert ok == tot - 1


def test_comptage_sans_tiktoken_est_illisible():
    assert b.compter("abc", "encodage_inexistant") is None


def test_termes_critiques():
    r = b.termes_preserves("UNKNOWN n est pas NO ; palier ILLISIBLE", ["UNKNOWN", "NO", "STALE"])
    assert r == {"UNKNOWN": True, "NO": True, "STALE": False}
