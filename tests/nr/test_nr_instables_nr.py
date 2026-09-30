"""NR -- le detecteur de tests instables NOMME un test dont le verdict change (veille lot_C_01b).

Quatre niveaux : comparaison pure, illisible compte, lecture d'un vrai JUnit, et CHEMIN REEL
(`main` lance pytest N fois sur un test qui alterne rouge/vert) -- un detecteur dont seule la
fonction est testee peut mourir sur son point d'entree sans que rien ne le voie.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_nr_instables as fni  # noqa: E402


def test_comparaison_trois_etats():
    r = fni.comparer([{"a": "passed", "b": "failed", "c": "passed"},
                      {"a": "failed", "b": "failed", "c": "passed"},
                      {"a": "passed", "b": "failed", "c": "passed"}])
    assert list(r["instables"]) == ["a"] and r["instables"]["a"] == "INSTABLE passed/failed/passed"
    assert r["stables_rouges"] == ["b"] and r["tests"] == 3


def test_une_passe_illisible_est_comptee_pas_ignoree():
    r = fni.comparer([{"a": "passed"}, None, {"a": "passed"}])
    assert r["passes_illisibles"] == 1 and not r["instables"]


def test_un_test_absent_d_une_passe_est_instable():
    r = fni.comparer([{"a": "passed"}, {}])
    assert "a" in r["instables"], "un test qui disparait d'une passe ne peut pas etre lu STABLE"


def test_lecture_junit(tmp_path):
    x = tmp_path / "j.xml"
    x.write_text('<testsuites><testsuite><testcase classname="m" name="ok"/>'
                 '<testcase classname="m" name="ko"><failure message="x"/></testcase>'
                 '<testcase classname="m" name="saut"><skipped/></testcase></testsuite></testsuites>',
                 encoding="utf-8")
    assert fni.issues_junit(x) == {"m::ok": "passed", "m::ko": "failed", "m::saut": "skipped"}
    assert fni.issues_junit(tmp_path / "absent.xml") is None


# Borne DEDIEE : ce test lance DEUX vraies sessions pytest en sous-processus (tous plugins,
# conftest racine) -- 15 s seul, mesure 2026-09-27. Sous la charge de la suite pure il franchissait
# la borne globale de 30 s ; pytest-timeout en methode `thread` arrete alors le PROCESSUS entier,
# et tout le bloc sortait sans preuve (SUITE_INCOMPLETE, 0 echec) : CI GitHub 36335602193 et
# ci_local du meme jour. 120 s couvre la charge, un vrai blocage reste attrape.
@pytest.mark.timeout(120)
def test_chemin_reel_nomme_le_test_qui_alterne(tmp_path, monkeypatch, capsys):
    compteur = tmp_path / "compteur.txt"
    t = tmp_path / "test_alterne_temoin.py"
    t.write_text(
        "import os, pathlib\n"
        "def test_alterne():\n"
        "    p = pathlib.Path(os.environ['NR_INSTABLES_COMPTEUR'])\n"
        "    n = int(p.read_text()) if p.exists() else 0\n"
        "    p.write_text(str(n + 1))\n"
        "    assert n % 2 == 0\n"
        "def test_toujours_vert():\n"
        "    assert True\n", encoding="utf-8")
    monkeypatch.setenv("NR_INSTABLES_COMPTEUR", str(compteur))
    rc = fni.main(["--passes", "2", str(t)])
    sortie = capsys.readouterr().out
    assert rc == 1, sortie
    assert "INSTABLE" in sortie and "test_alterne" in sortie
    assert "test_toujours_vert" not in sortie.split("BILAN")[0], "un test stable ne doit pas etre accuse"
