# -*- coding: utf-8 -*-
"""NR (G2 de bb:P1_executeurs_preservation_et_arbre_partage_20261019 ; bug bb:active_bugs/bug_scorecard_faux_rouge_nr_illisibles_20261019)
-- des NR livres dont la mesure est ILLISIBLE ne font pas un ROUGE.

Mesure 19/10 : deux livraisons justes (OPENCODE_GPTOSS job_c67eb508, 69 NR verts ; OPENCODE_NEMOTRON job_d4e2061c,
66 NR verts, rejoues par CLAUDE puis integres 1ad5425fd et 5a7c3ce91) ont ete REFUSEES par
app/forge_scorecard.scorecard_de_livraison avec « det-diff: NR livres ROUGES (?) » : le « ? » est l'absence de toute
ligne de bilan pytest (demarrage impossible dans le bac a sable, conftest casse, interruption), rangee du cote ROUGE.
Trois fois de suite, la tache G2 elle-meme est morte chez les executeurs ; CLAUDE la code. Contrat :
  1. pytest sans aucune ligne de bilan (rc != 0) -> UNRATED (non note, jamais vert), motif « NON MESURES » ;
  2. rc 2 / 3 / 4 (interrompu, erreur interne, usage) -> UNRATED, meme avec une ligne trompeuse ;
  3. un vrai echec mesure (rc 1 et un bilan « N failed ») -> REJECTED, comme avant ; vert -> OPTIMAL, comme avant.
"""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from nokido_agent.app import forge_scorecard as sc  # noqa: E402


@pytest.fixture()
def livraison(tmp_path):
    t = tmp_path / "tests" / "nr" / "test_livre_nr.py"
    t.parent.mkdir(parents=True)
    t.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    return tmp_path, ["tests/nr/test_livre_nr.py"]


def _pytest_rend(monkeypatch, rc, stdout):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=rc, stdout=stdout, stderr=""))


@pytest.mark.parametrize("rc,sortie", [(1, ""), (1, "ImportError while loading conftest"), (4, ""),
                                      (2, "1 passed, 1 error in 0.1s"), (3, "INTERNALERROR> boom")])
def test_une_mesure_illisible_n_est_pas_un_rouge(livraison, monkeypatch, rc, sortie):
    wt, chemins = livraison
    _pytest_rend(monkeypatch, rc, sortie)
    s = sc.scorecard_de_livraison(wt, chemins)
    assert s.grade == sc.QualityGrade.UNRATED, (rc, sortie, s.critique)
    assert "NON MESURE" in s.critique


def test_un_vrai_rouge_reste_rouge(livraison, monkeypatch):
    wt, chemins = livraison
    _pytest_rend(monkeypatch, 1, "FAILED tests/nr/test_livre_nr.py::test_x\n1 failed in 0.1s")
    assert sc.scorecard_de_livraison(wt, chemins).grade == sc.QualityGrade.REJECTED


def test_un_vert_reste_vert(livraison, monkeypatch):
    wt, chemins = livraison
    _pytest_rend(monkeypatch, 0, "1 passed in 0.1s")
    assert sc.scorecard_de_livraison(wt, chemins).grade == sc.QualityGrade.OPTIMAL
