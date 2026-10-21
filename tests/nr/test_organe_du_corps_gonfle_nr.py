# -*- coding: utf-8 -*-
"""NR (audit pair F, mesure 19/10 bb:discovered_facts/mesure_F_hamilton_muet_hub_gonfle_20261019) -- un organe du
CORPS qui gonfle par rapport a SA PROPRE baseline est detecte, meme quand la pression globale est NON_SOI.

Mesure 19/10 (sandbox/hub_blackbox.jsonl) : le hub, stable 0,35-0,6 Go de 20:35 a 21:30, passe a 3,3 Go a 21:35 puis
8,5 Go a 21:40 ; RAM 95,5 %. Hamilton arme n'a rien vu : verdict global NON_SOI (Firefox), et il ne vise que des
DIFFERABLE. fuyards_hors_corps exclut le corps par construction. Contrat de
`forge_resource_manager.gonflement_organe(points, facteur=None, plancher_gb=None)` (points = [(ts, rss_gb)], le
dernier = l'instant present) :
  1. GONFLE si le dernier RSS >= max(plancher, facteur x mediane de la baseline) -- baseline = points de plus de
     10 min, dans l'heure et demie ; rend rss, baseline et rapport ;
  2. une montee de prechauffage normale (0,1 -> 1,1 Go) sous le plancher n'est PAS un gonflement ;
  3. moins de 5 points de baseline -> INCONNU (jamais NORMAL ni GONFLE sur une serie trop courte) ;
  4. defauts d'env NOKIDO_GONFLEMENT_FACTEUR (3) et NOKIDO_GONFLEMENT_PLANCHER_GO (2).
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from nokido_agent.app import forge_resource_manager as rm  # noqa: E402

T0 = 1_000_000.0


def _serie(rss_par_tranche_5min):
    return [(T0 + i * 300.0, v) for i, v in enumerate(rss_par_tranche_5min)]


# courbe REELLE du hub le 19/10, 20:35 -> 21:40, une valeur par 5 min (hub_blackbox.jsonl)
SOIR_19_10 = [0.535, 0.581, 1.367, 0.728, 0.471, 0.46, 0.472, 0.388, 0.402, 0.372, 0.432, 0.352, 3.307, 8.511]


def test_le_gonflement_du_hub_du_19_10_est_detecte():
    v = rm.gonflement_organe(_serie(SOIR_19_10))
    assert v["etat"] == "GONFLE", v
    assert v["rss_gb"] == 8.511 and v["baseline_gb"] < 1.0 and v["rapport"] > 3


def test_le_prechauffage_normal_n_est_pas_un_gonflement():
    v = rm.gonflement_organe(_serie([0.13, 0.31, 0.36, 0.41, 0.48, 0.6, 0.75, 0.9, 1.0, 1.1]))
    assert v["etat"] == "NORMAL", v


def test_une_serie_trop_courte_est_inconnue():
    v = rm.gonflement_organe(_serie([0.4, 0.4, 9.0]))
    assert v["etat"] == "INCONNU", v


def test_les_seuils_viennent_de_l_environnement(monkeypatch):
    monkeypatch.setenv("NOKIDO_GONFLEMENT_PLANCHER_GO", "10")
    assert rm.gonflement_organe(_serie(SOIR_19_10))["etat"] == "NORMAL"
