# -*- coding: utf-8 -*-
"""NR (2/11) : le veto d'ancrage du tri ne compte que les ancres DISCRIMINANTES (presentes dans au moins un resultat).

Mesure 2/11, veille wj_41bc345756 : ancres du theme ['cp-sat', 'cegar', 'unsatisfiable'] ; 24 resultats, dont
« Unsatisfiable Cores for Constraint Programming » et « A Scalable Algorithm for Minimal Unsatisfiable Core
Extraction », PERTINENTS, plafonnes « hors-sujet » : la regle du 27/10 exige 2 ancres, or « cp-sat » et « cegar »
(sigles du theme) n'apparaissent dans AUCUN resultat -- elles ne discriminent rien. Regle : une ancre absente de tous
les resultats sort du compte. Le cas du 27/10 (PME nigerianes ancrees par le seul « stochastic ») reste plafonne,
ses autres ancres apparaissant ailleurs dans le lot."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_chain_executor as ce  # noqa: E402


def _r(titre, contenu=""):
    return {"title": titre, "content": contenu}


def test_les_sigles_absents_de_tous_les_resultats_sortent_du_compte():
    lot = [_r("Unsatisfiable Cores for Constraint Programming"),
           _r("A Scalable Algorithm for Minimal Unsatisfiable Core Extraction"),
           _r("Changing Data Sources in the Age of Machine Learning")]
    eff = ce.ancres_discriminantes(["cp-sat", "cegar", "unsatisfiable"], lot)
    assert eff == ["unsatisfiable"]
    hay = "unsatisfiable cores for constraint programming"
    assert ce._plafond_ancrage(8.0, hay, eff) == 8.0, "article pertinent : plus plafonne"


def test_le_cas_des_pme_du_27_10_reste_plafonne():
    lot = [_r("Stochastic models of Nigerian SMEs growth"),
           _r("Stochastic scheduling on GPU processors"),
           _r("GPU scheduling heuristics")]
    eff = ce.ancres_discriminantes(["stochastic", "scheduling", "gpu"], lot)
    assert eff == ["stochastic", "scheduling", "gpu"]
    assert ce._plafond_ancrage(8.0, "stochastic models of nigerian smes growth", eff) <= 3.0


def test_aucune_ancre_presente_rien_ne_change():
    lot = [_r("Restore, Assess, Repeat"), _r("Image restoration")]
    assert ce.ancres_discriminantes(["cp-sat", "cegar"], lot) == ["cp-sat", "cegar"]
