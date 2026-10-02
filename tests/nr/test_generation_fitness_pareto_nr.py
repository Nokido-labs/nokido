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
    def poser(modules, tests, capacites=None):
        rec = {"generation": "GEN-00001", "environnement": {"empreinte": {"modules_forge": modules, "tests_nr": tests}}}
        if capacites is not None:
            rec["capacites"] = capacites
        monkeypatch.setattr(gen, "lister", lambda statut=None: [rec])
    return poser


# 2026-10-01 (revue claude.ai mission_rsi_soif, verifiee) : un compte de fichiers ne prouve JAMAIS un
# gain -- la table du 26/09 rendait AMELIORE pour un fichier de test VIDE. Sans mesure de capacite :
@pytest.mark.parametrize("modules, tests, verdict", [
    (100, 60, "NEUTRE"),                       # des tests en plus : pas une preuve de gain
    (95, 50, "NEUTRE"),                        # allegement : un cout en moins, pas un gain
    (100, 50, "NEUTRE"),
    (100, 40, "DEGRADE"),                      # des gardes NR ont disparu
    (90, 40, "DEGRADE"),                       # meme en allegeant
    (110, 60, "CROISSANCE_SANS_PREUVE"),       # croissance : un cout, aucun gain mesure
    (110, 50, "CROISSANCE_SANS_PREUVE"),       # le cas du 20/09
])
def test_sans_mesure_un_compte_de_fichiers_ne_gagne_jamais(prec, modules, tests, verdict):
    prec(100, 50)
    g = gen._gain_vs_precedente({"modules_forge": modules, "tests_nr": tests})
    assert g["verdict"] == verdict and g["mesure_de_capacite"] is False
    assert g["modules_forge"] == modules - 100 and g["tests_nr"] == tests - 50   # compteurs conserves


@pytest.mark.parametrize("avant, apres, verdict", [
    ({"ndcg10": 0.50}, {"ndcg10": 0.55}, "AMELIORE"),
    ({"ndcg10": 0.50}, {"ndcg10": 0.45}, "DEGRADE"),
    ({"ndcg10": 0.50}, {"ndcg10": 0.50}, "NEUTRE"),
    ({"ndcg10": {"score": 0.50, "bruit": 0.03}}, {"ndcg10": {"score": 0.52, "bruit": 0.03}}, "NEUTRE"),  # dans le bruit
    ({"ndcg10": 0.50, "bfcl": 0.70}, {"ndcg10": 0.60, "bfcl": 0.60}, "DEGRADE"),  # un recul suffit
])
def test_le_gain_se_lit_dans_les_capacites(prec, avant, apres, verdict):
    prec(100, 50, capacites=avant)
    g = gen._gain_vs_precedente({"modules_forge": 100, "tests_nr": 50}, capacites=apres)
    assert g["verdict"] == verdict and g["mesure_de_capacite"] is True


def test_ajouter_seulement_des_fichiers_reste_neutre_meme_mesure(prec):
    prec(100, 50, capacites={"ndcg10": 0.50})
    g = gen._gain_vs_precedente({"modules_forge": 100, "tests_nr": 80}, capacites={"ndcg10": 0.50})
    assert g["verdict"] == "NEUTRE"


def test_un_gain_ne_rachete_pas_des_gardes_perdues(prec):
    prec(100, 50, capacites={"ndcg10": 0.50})
    g = gen._gain_vs_precedente({"modules_forge": 100, "tests_nr": 40}, capacites={"ndcg10": 0.70})
    assert g["verdict"] == "DEGRADE"


def test_la_premiere_generation_n_a_pas_de_verdict_de_gain(monkeypatch):
    monkeypatch.setattr(gen, "lister", lambda statut=None: [])
    assert gen._gain_vs_precedente({"modules_forge": 5, "tests_nr": 3})["verdict"] == "PREMIERE"
