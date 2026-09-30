# -*- coding: utf-8 -*-
"""NR — garde `laforge-global-incomplet` (forge_golden_rules_ast).

Angle mort mesure le 2026-08-19 : forge_llama_keeper assignait un global dans une
fonction sans le declarer au `global`, le rendant LOCAL, avec une lecture avant
liaison -> UnboundLocalError a chaque tick, keeper en crash-loop. `ast.parse`,
`compile` et `flake8 F82` passaient tous ; seul l'import le revelait.

Ce test verifie l'EFFET du garde : qu'il MORD sur le motif certain et se TAIT sur
le code correct (un garde qui accuse du code correct se fait desarmer).
"""
import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

import forge_golden_rules_ast as G  # noqa: E402


def _scan(src: str):
    return G._scan_global_incomplet("t.py", ast.parse(src))


def test_mord_sur_lecture_avant_liaison():
    src = ("_ZC = 0.0\n_O = 0.0\n"
           "def d():\n    global _O\n    x = _ZC or None\n    _O = 1\n    _ZC = 0.0\n")
    r = _scan(src)
    assert len(r) == 1
    assert r[0]["rule"] == "laforge-global-incomplet"
    assert r[0]["severity"] == "ERROR"
    assert "_ZC" in r[0]["message"]


def test_mord_sur_augassign_nu():
    r = _scan("compteur = 0\ndef b():\n    compteur += 1\n")
    assert len(r) == 1
    assert "compteur" in r[0]["message"]


def test_muet_si_global_complet():
    r = _scan("_ZC = 0.0\ndef d():\n    global _ZC\n    x = _ZC or None\n    _ZC = 0.0\n")
    assert r == []


def test_muet_shadowing_legitime_store_puis_aug():
    # total lie AVANT usage -> local legitime, pas un bug.
    r = _scan("total = 0\ndef f():\n    total = 0\n    total += 1\n    return total\n")
    assert r == []


def test_muet_lecture_seule_du_global():
    r = _scan("CONST = 42\ndef k():\n    return CONST + 1\n")
    assert r == []


def test_muet_branche_conditionnelle_conservateur():
    # store avant load lexicalement -> non flague (conservateur : evite les faux
    # positifs sur les liaisons conditionnelles).
    r = _scan("x = 0\ndef g(c):\n    if c:\n        x = 1\n    return x\n")
    assert r == []


def test_muet_parametre_homonyme_d_un_global():
    r = _scan("cfg = 0\ndef p(cfg):\n    cfg = cfg + 1\n    return cfg\n")
    assert r == []


def test_muet_cible_de_comprehension():
    # la cible d'une comprehension a son propre scope.
    r = _scan("item = None\ndef h(seq):\n    return [item for item in seq]\n")
    assert r == []


def test_muet_variable_purement_locale():
    # z n'existe pas au niveau module -> hors du perimetre de CE garde.
    r = _scan("def g():\n    y = z\n    z = 1\n")
    assert r == []


def test_le_garde_est_bien_cable_dans_le_scan():
    """Contre-epreuve : le scan complet remonte bien la regle (pas juste la
    fonction isolee)."""
    src = "_g = 0\ndef d():\n    v = _g\n    _g = 1\n    return v\n"
    # Les regles AST transitent par _scan_noms_non_lies (le point d'entree qui
    # agrege appel-nom-non-lie + usage-avant-liaison + global-incomplet).
    findings = G._scan_noms_non_lies("t.py", ast.parse(src))
    assert any(f["rule"] == "laforge-global-incomplet" for f in findings)
