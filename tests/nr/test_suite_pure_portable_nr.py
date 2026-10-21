# -*- coding: utf-8 -*-
"""NR : suite pure PORTABLE sur runner GitHub heberge -- second observateur de la CI de reference.

P1 p1_suite_pure_runners_github_publics_2026-10-14 (GO owner 14/10, apres la release 0.20.11) : la
suite pure de tools/ci_local.py saturait le disque du poste owner. Le lanceur rejoue la MEME liste
(lue par AST, jamais recopiee), ecarte ET NOMME les tests qui supposent le poste, et une suite
incomplete n'est jamais verte. Le workflow tourne en OBSERVATION, sans secret, actions epinglees.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OUTIL = ROOT / "tools" / "forge_suite_pure_portable.py"
WF = ROOT / ".github" / "workflows" / "suite-pure.yml"


def _module():
    assert OUTIL.is_file(), "outil absent : %s" % OUTIL
    spec = importlib.util.spec_from_file_location("forge_suite_pure_portable", OUTIL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_lit_la_meme_liste_que_ci_local():
    pure, isoles = _module().lire_listes()
    assert isinstance(pure, list) and len(pure) > 500, len(pure)
    assert "tests/nr/test_suite_pure_portable_nr.py" in pure
    assert isoles and all(isinstance(t, str) and t.startswith("tests/") for t in isoles), isoles[:3]


def test_liste_illisible_refusee(tmp_path):
    faux = tmp_path / "ci_local.py"
    faux.write_text("PURE_TESTS = autre()\n", encoding="utf-8")
    with pytest.raises((SystemExit, ValueError)):
        _module().lire_listes(faux)


def test_ecart_poste_sans_raison_refuse_avec_raison_garde(tmp_path):
    m = _module()
    f = tmp_path / "poste.txt"
    f.write_text("tests/nr/test_x_nr.py\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        m.lire_poste_requis(f)
    f.write_text("# commentaire\n\ntests/nr/test_y_nr.py  # lit %NOKIDO_DATA%\n", encoding="utf-8")
    assert m.lire_poste_requis(f) == {"tests/nr/test_y_nr.py": "lit V:"}
    assert m.lire_poste_requis(tmp_path / "absent.txt") == {}


def test_junit_totalise_et_illisible_vaut_none(tmp_path):
    m = _module()
    j = tmp_path / "j.xml"
    j.write_text('<testsuites><testsuite tests="3" failures="1" errors="0" skipped="1"/>'
                 '<testsuite tests="2" failures="0" errors="1" skipped="0"/></testsuites>', encoding="utf-8")
    assert m.lire_junit(j) == {"tests": 5, "failures": 1, "errors": 1, "skipped": 1}
    (tmp_path / "k.xml").write_text("<pas fini", encoding="utf-8")
    assert m.lire_junit(tmp_path / "k.xml") is None
    assert m.lire_junit(tmp_path / "absent.xml") is None


def test_workflow_en_observation_sans_secret_et_epingle():
    assert WF.is_file(), "workflow absent : %s" % WF
    t = WF.read_text(encoding="utf-8")
    assert "tools/forge_suite_pure_portable.py" in t and "--observation" in t
    assert "contents: read" in t
    assert "secrets." not in t
    uses = re.findall(r"uses:\s*(\S+)", t)
    assert uses and all(re.search(r"@[0-9a-f]{40}$", u) for u in uses), uses


def test_embarque_dans_le_dist():
    # Charge par FICHIER : `import forge_dist_publish` ne passait que si un test precedent avait mis tools/ dans
    # sys.path (echec joue seul, mesure 18/10) -- un test ne depend pas de l'ordre de la suite.
    spec = importlib.util.spec_from_file_location("forge_dist_publish", ROOT / "tools" / "forge_dist_publish.py")
    D = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(D)
    assert ".github/workflows/suite-pure.yml" in D.WORKFLOWS_DIST
