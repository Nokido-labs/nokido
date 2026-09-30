"""NR — le moteur de mutation testing.

Cas fondateur : le premier passage a rendu « 0 mutant, 0 survivant, exit 0 »
parce que le recenseur et le muteur numerotaient les noeuds avec une unite
d'ecart. Un rapport vide qui se presente comme un succes est precisement ce que
cet outil sert a debusquer ailleurs — il devait donc etre teste sur ce point.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

_CODE = (
    "def f(a, b):\n"
    "    if a < b and not a:\n"
    "        return True\n"
    "    return a + b\n"
)


def _sites(code: str):
    import forge_mutation_test as M

    rec = M._Recenseur()
    rec.visit(ast.parse(code))
    return rec.sites


def test_les_cinq_familles_sont_reconnues():
    genres = {g for g, _, _ in _sites(_CODE)}
    assert genres == {"comparaison", "et_ou", "negation", "booleen", "arithmetique"}


def test_un_noeud_neutre_n_est_pas_un_site():
    import forge_mutation_test as M

    assert M._genre(ast.parse("x = 1").body[0]) == ""


def test_chaque_site_recense_est_reellement_mutable():
    """LE bug fondateur : recenseur et muteur numerotaient avec un decalage
    d'une unite, donc aucune cible ne correspondait et le rapport annoncait
    zero mutant. Chaque site promis doit produire une mutation appliquee."""
    import forge_mutation_test as M

    for genre, ident, _ligne in _sites(_CODE):
        muteur = M._Muteur(genre, ident)
        mute = muteur.visit(ast.parse(_CODE))
        assert muteur.applique, f"site {genre}#{ident} recense mais non mutable"
        ast.fix_missing_locations(mute)
        assert ast.unparse(mute) != _CODE, f"site {genre}#{ident} : code inchange"


def test_la_comparaison_glisse_bien_sur_la_frontiere():
    """`<` devient `<=` : l'erreur de frontiere est la faute qu'on cherche."""
    import forge_mutation_test as M

    genre, ident, _ = next(s for s in _sites(_CODE) if s[0] == "comparaison")
    mute = M._Muteur(genre, ident).visit(ast.parse(_CODE))
    ast.fix_missing_locations(mute)
    assert "a <= b" in ast.unparse(mute)


def test_la_negation_est_retiree_pas_doublee():
    import forge_mutation_test as M

    genre, ident, _ = next(s for s in _sites(_CODE) if s[0] == "negation")
    mute = M._Muteur(genre, ident).visit(ast.parse(_CODE))
    ast.fix_missing_locations(mute)
    assert "not a" not in ast.unparse(mute)


def test_un_git_muet_n_est_pas_un_fichier_sale():
    """Sous compte de service, git rend « dubious ownership » : le lire comme
    des modifications non commitees bloquait l'outil en permanence."""
    import subprocess

    import forge_mutation_test as M

    class _R:
        def __init__(self, rc, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    vrai = subprocess.run
    try:
        subprocess.run = lambda *a, **k: _R(0, "")
        assert M._git_propre("x.py") == (True, "")
        subprocess.run = lambda *a, **k: _R(0, " M x.py")
        propre, motif = M._git_propre("x.py")
        assert propre is False and "non commitees" in motif
        subprocess.run = lambda *a, **k: _R(128, "", "detected dubious ownership")
        propre, motif = M._git_propre("x.py")
        assert propre is False and "n'a pas pu repondre" in motif
    finally:
        subprocess.run = vrai


def test_l_interpreteur_choisi_existe():
    """Le chemin canonique derive de ~, qui vaut C:/Users/Default sous un compte
    de service : lancer les tests avec lui donnait FileNotFoundError."""
    import os

    import forge_mutation_test as M

    assert os.path.exists(M._PY)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
