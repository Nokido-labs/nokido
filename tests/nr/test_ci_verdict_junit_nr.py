# -*- coding: utf-8 -*-
"""Non-regression — le verdict d'un gate ne depend pas d'un flux qui se ferme.

Mesure 2026-08-26, trois runs (32957444508, 32958735437, 32972075477) : le gate
« pytest (suite pure) » rendait rc=1 avec, dans le journal, TOUS les fichiers verts et
AUCUNE ligne de verdict — ni « N passed », ni « FAILED ». Le processus mourait APRES la
session, au shutdown de l'interpreteur (flux ferme sous Windows). La CI etait rouge
trois fois pour un travail entierement fait et mesure.

Le remede n'est pas d'ignorer le rc : c'est de faire reposer le verdict sur une PREUVE
ECRITE. pytest ecrit son rapport JUnit a la fin de la session, donc avant le shutdown —
il survit a la fermeture des flux.

Ce fichier verrouille la regle qui rend ce rachat sur : **un rapport qu'on n'a pas pu
lire ne rachete rien.** Sans elle, « je n'ai pas pu voir » deviendrait « il n'y a rien a
voir », et n'importe quel echec passerait pour peu que le rapport disparaisse.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

CI = pytest.importorskip("ci_local")


def ecrire(tmp_path, contenu, nom="junit.xml"):
    p = tmp_path / nom
    p.write_text(contenu, encoding="utf-8")
    return p


SUITE = ('<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" '
         'tests="{t}" failures="{f}" errors="{e}" skipped="{s}"/></testsuites>')


# ------------------------------------------------------ ce qui NE rachete PAS

def test_rapport_absent_rend_none(tmp_path):
    """LE test. Absent = illisible = on garde l'echec."""
    assert CI._lire_junit(tmp_path / "jamais_ecrit.xml") is None


def test_rapport_corrompu_rend_none(tmp_path):
    assert CI._lire_junit(ecrire(tmp_path, "<testsuite tests='3'")) is None


def test_rapport_vide_rend_none(tmp_path):
    assert CI._lire_junit(ecrire(tmp_path, "")) is None


def test_xml_sans_testsuite_rend_none(tmp_path):
    assert CI._lire_junit(ecrire(tmp_path, "<autre><chose/></autre>")) is None


def test_attribut_non_numerique_rend_none(tmp_path):
    """Un compteur qui n'est pas un nombre = rapport douteux, pas un rapport vert."""
    assert CI._lire_junit(ecrire(tmp_path, SUITE.format(t="beaucoup", f=0, e=0, s=0))) is None


# ---------------------------------------------------------- ce qui rachete

def test_suite_verte_est_lue_comme_verte(tmp_path):
    b = CI._lire_junit(ecrire(tmp_path, SUITE.format(t=101, f=0, e=0, s=0)))
    assert b is not None
    assert b["problemes"] == 0 and b["tests"] == 101


def test_racine_testsuite_directe_acceptee(tmp_path):
    """pytest ecrit parfois <testsuite> a la racine, sans <testsuites>."""
    xml = '<testsuite name="pytest" tests="7" failures="0" errors="0" skipped="0"/>'
    b = CI._lire_junit(ecrire(tmp_path, xml))
    assert b is not None and b["tests"] == 7 and b["problemes"] == 0


# ------------------------------------------------------- ce qui reste rouge

def test_echec_reste_un_echec(tmp_path):
    b = CI._lire_junit(ecrire(tmp_path, SUITE.format(t=101, f=2, e=0, s=0)))
    assert b["problemes"] == 2, "un vrai echec ne doit jamais etre rachete"


def test_erreur_compte_comme_probleme(tmp_path):
    b = CI._lire_junit(ecrire(tmp_path, SUITE.format(t=10, f=0, e=1, s=0)))
    assert b["problemes"] == 1


def test_les_ignores_ne_comptent_pas_comme_executes(tmp_path):
    """Un rapport ou tout est ignore n'a rien prouve : il ne doit rien racheter."""
    b = CI._lire_junit(ecrire(tmp_path, SUITE.format(t=5, f=0, e=0, s=5)))
    assert b["tests"] == 0, "5 ignores = 0 test execute"
    assert b["problemes"] == 0


def test_plusieurs_suites_additionnees(tmp_path):
    xml = ('<testsuites>'
           '<testsuite tests="3" failures="1" errors="0" skipped="0"/>'
           '<testsuite tests="4" failures="0" errors="2" skipped="1"/>'
           '</testsuites>')
    b = CI._lire_junit(ecrire(tmp_path, xml))
    assert b["tests"] == 6 and b["failures"] == 1 and b["errors"] == 2
    assert b["problemes"] == 3


def test_le_gate_declare_le_rapport_junit():
    """Sans --junitxml, il n'y a aucune preuve ecrite a lire."""
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    assert "--junitxml=" in src

# ------------------------------------- un compte SANS nom n'est pas exploitable

CAS = ('<testsuites><testsuite name="pytest" tests="3" failures="1" errors="1" '
       'skipped="0">'
       '<testcase classname="tests.nr.test_a" name="test_vert"/>'
       '<testcase classname="tests.nr.test_b" name="test_casse">'
       '<failure message="assert 1 == 2">trace</failure></testcase>'
       '<testcase classname="tests.nr.test_c" name="test_explose">'
       '<error message="ImportError: absent">trace</error></testcase>'
       '</testsuite></testsuites>')

def test_les_cas_en_echec_sont_nommes(tmp_path):
    """Mesure 2026-08-29, run 33256914855 : le journal disait « 2 test(s) en echec »
    sans dire lesquels, et le rapport JUnit vit dans le basetemp du runner, detruit
    entre deux runs et jamais publie en artefact. La seule preuve disparaissait avec
    le run : il a fallu rejouer 5804 tests en local pour retrouver deux noms."""
    b = CI._lire_junit(ecrire(tmp_path, CAS))
    noms = [cas for cas, _genre, _msg in b["rates"]]
    assert noms == ["tests.nr.test_b::test_casse", "tests.nr.test_c::test_explose"]
    assert [g for _c, g, _m in b["rates"]] == ["failure", "error"]
    assert b["rates"][0][2] == "assert 1 == 2", "le message porte le pourquoi"

def test_une_suite_verte_ne_nomme_personne(tmp_path):
    b = CI._lire_junit(ecrire(tmp_path, SUITE.format(t=9, f=0, e=0, s=0)))
    assert b["rates"] == []

def test_le_gate_imprime_les_noms():
    """Le garde ne vaut que branche : nommer les cas sans les imprimer ne sert a rien
    (motif « garde sans emetteur » — le calcul existe, personne ne le lit)."""
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    assert '_bilan.get("rates")' in src, "les noms doivent etre imprimes dans le journal"
