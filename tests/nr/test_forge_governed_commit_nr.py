# -*- coding: utf-8 -*-
"""NR -- le commit gouverne joue les NR IMPACTES et refuse sur un rouge (methode A, 20/10).

Le brouillon OPENCODE_GLM (a56a8577f) n'appelait jamais le contrat : il lancait le script sur un depot
temporaire alors que le script vise SA racine, et ne testait que `rc != 0` (un refus quelconque le satisfaisait).
Contrat reecrit :
  1. un NR impacte rouge -> refus, le NOM du test rouge figure dans le refus ;
  2. tous verts -> accepte ;
  3. selection illisible (diff illisible, selecteur absent) -> refus motive, jamais accepte par defaut ;
  4. plafond depasse -> refus motive + commande run_job, rien n'est joue en silence ;
  5. le selecteur est celui de forge_ci_selection (pas de second selecteur) ;
  6. aucun commit (git add) n'a lieu quand le refus tombe.
Hermetique : runner pytest et selection injectes, aucun reseau, aucun git.
"""
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_governed_commit as gc  # noqa: E402
import forge_ci_selection as sel  # noqa: E402

pytestmark = pytest.mark.timeout(60)

PURE = ["tests/nr/test_a_nr.py", "tests/nr/test_b_nr.py", "tests/nr/test_c_nr.py"]
LUS = {"tests/nr/test_a_nr.py": "import forge_x", "tests/nr/test_b_nr.py": "import forge_x",
       "tests/nr/test_c_nr.py": "import autre"}


def _lire(p):
    return LUS[str(p).replace("\\", "/")]


def _eval(fichiers, runner, **kw):
    return gc.evaluer_nr(fichiers, pure_tests=PURE, lancer=runner, lire=_lire, **kw)


def test_nr_impacte_rouge_refuse_avec_le_nom():
    vus = []

    def runner(retenus):
        vus.append(list(retenus))
        return 1, "FAILED tests/nr/test_b_nr.py::test_regression - assert 0\n1 failed, 1 passed"

    ok, msg = _eval(["app/forge_x.py"], runner)
    assert ok is False
    assert "tests/nr/test_b_nr.py::test_regression" in msg
    assert vus == [["tests/nr/test_a_nr.py", "tests/nr/test_b_nr.py"]]  # c non impacte : non joue


def test_tous_verts_accepte():
    ok, msg = _eval(["app/forge_x.py"], lambda r: (0, "2 passed"))
    assert ok is True


def test_rouge_sans_nom_lisible_refuse_quand_meme():
    ok, msg = _eval(["app/forge_x.py"], lambda r: (2, "INTERNALERROR"))
    assert ok is False and "rc=2" in msg


def test_selection_illisible_refuse_motive():
    def runner(r):
        raise AssertionError("rien ne doit etre joue sur une selection illisible")

    ok, msg = _eval([], runner)  # aucun fichier lu -> le selecteur se replie sur TOUT
    assert ok is False
    assert "selection" in msg.lower()


def test_selecteur_absent_refuse():
    ok, msg = gc.evaluer_nr(["app/forge_x.py"], pure_tests=None, lancer=lambda r: (0, ""))
    assert ok is False and "illisible" in msg.lower()


def test_fichier_global_refuse_car_perimetre_non_reduit():
    ok, msg = _eval(["conftest.py"], lambda r: (0, ""))
    assert ok is False and "run_job" in msg


def test_plafond_depasse_refuse_avec_commande_run_job():
    def runner(r):
        raise AssertionError("au-dessus du plafond rien n'est joue en silence")

    ok, msg = _eval(["app/forge_x.py"], runner, plafond=1)
    assert ok is False
    assert "plafond" in msg.lower() and "run_job" in msg
    assert "--impacte" in msg and "ci_local" in msg


def test_aucun_nr_impacte_accepte_sans_rien_jouer():
    def runner(r):
        raise AssertionError("rien a jouer")

    ok, msg = _eval(["app/forge_zzz.py"], runner)
    assert ok is True and "0" in msg


def test_selecteur_reutilise_pas_de_second():
    assert gc.selectionner is sel.selectionner


def test_refus_ne_stage_rien(monkeypatch, capsys):
    appels = []
    monkeypatch.setattr(gc, "_git", lambda *a: appels.append(a) or (0, ""))
    monkeypatch.setattr(gc, "evaluer_nr", lambda f, **k: (False, "REFUS test"))
    monkeypatch.setattr(sys, "argv", ["x", "--message", "m", "--files", "app/forge_x.py"])
    assert gc.main() == 1
    assert appels == []
    assert "REFUS test" in capsys.readouterr().out


def test_declare_dans_pure_tests():
    src = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert '"tests/nr/test_forge_governed_commit_nr.py"' in src
