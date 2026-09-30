"""NR -- le gain d'une generation est un verdict de PARETO : ajouter des modules n'est pas une victoire.

MESURE 2026-09-20 (bb architecture_rules/la_fitness_recompense_l_ajout) : `_gain_vs_precedente`
declarait VICTOIRE tout delta positif de {modules_forge, tests_nr} ; 30 generations, 1326 -> 1401
modules, toutes STABLE, aucune decroissance -- un score qui pousse a la croissance dans un corps dont le
defaut mesure est la DUPLICATION. Veille RSI 26/09 : openevolve `database.py:65` porte `complexity` ;
awesome-self-evolving `docs/primer.md:40` : frontiere de Pareto. Les modules sont un COUT (complexite),
les tests une COUVERTURE (benefice) ; seul un deplacement sur la frontiere est un gain.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_generation as gen  # noqa: E402


@pytest.fixture
def prec(monkeypatch):
    def poser(modules, tests):
        monkeypatch.setattr(gen, "lister", lambda statut=None: [
            {"generation": "GEN-00001", "environnement": {"empreinte": {"modules_forge": modules, "tests_nr": tests}}}])
    return poser


@pytest.mark.parametrize("modules, tests, verdict", [
    (100, 60, "AMELIORE"),                     # plus de couverture, complexite egale
    (95, 50, "AMELIORE"),                      # allegement a couverture egale
    (100, 50, "NEUTRE"),
    (100, 40, "DEGRADE"),                      # couverture perdue
    (90, 40, "DEGRADE"),                       # meme en allegeant
    (110, 60, "COMPROMIS"),                    # croissance ET couverture : pas une victoire d'office
    (110, 50, "CROISSANCE_SANS_COUVERTURE"),   # le cas du 20/09
])
def test_le_gain_est_un_verdict_de_pareto(prec, modules, tests, verdict):
    prec(100, 50)
    g = gen._gain_vs_precedente({"modules_forge": modules, "tests_nr": tests})
    assert g["verdict"] == verdict
    assert g["modules_forge"] == modules - 100 and g["tests_nr"] == tests - 50   # compteurs conserves


def test_la_premiere_generation_n_a_pas_de_verdict_de_gain(monkeypatch):
    monkeypatch.setattr(gen, "lister", lambda statut=None: [])
    assert gen._gain_vs_precedente({"modules_forge": 5, "tests_nr": 3})["verdict"] == "PREMIERE"
