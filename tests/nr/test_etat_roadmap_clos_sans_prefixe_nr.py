# -*- coding: utf-8 -*-
"""NR -- etat_roadmap lit [CLOS ...] en tete de valeur, avec OU sans prefixe de priorite.

Trou mesure : `^\\s*(?:P[012]|BLOCKER|...)\\s*[:\\-]\\s*\\[` exigeait le prefixe ; une valeur
`[CLOS 2026-10-17 : ...]` nue restait OUVERT (roadmap_p1_arbre_evolution_ui_web_20261017,
roadmap_p2_crawl4ai_restart_always_20261015, roadmap_p2_purgeurs_web_hub_tests_20261015).

Valeurs FICTIVES. Contrat : marqueur en tete (avec ou sans prefixe) ; liste blanche ;
le mot CLOS au milieu d'un texte ne clot rien.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_ssot_maintainer as M  # noqa: E402


def test_clos_en_tete_sans_prefixe_clot():
    assert M.etat_roadmap("[CLOS 2026-10-17 : valeur fictive]") == "CLOS"
    assert M.etat_roadmap("  [CLOS] valeur fictive sans date") == "CLOS"


def test_clos_avec_prefixe_clot():
    assert M.etat_roadmap("P2: [CLOS 2026-10-15 : valeur fictive]") == "CLOS"
    assert M.etat_roadmap("P1: [CLOS 2026-10-17 : valeur fictive]") == "CLOS"


def test_autres_marqueurs_de_cloture_sans_prefixe_clotent():
    assert M.etat_roadmap("[FAIT le 2026-10-01] valeur fictive") == "FAIT"
    assert M.etat_roadmap("[RESOLU] valeur fictive") == "RESOLU"


def test_partiel_et_ouvert_restent_ouverts_avec_ou_sans_prefixe():
    assert M.etat_roadmap("[PARTIEL 2026-10-01 : valeur fictive]") == "OUVERT"
    assert M.etat_roadmap("[OUVERT : valeur fictive]") == "OUVERT"
    assert M.etat_roadmap("P1: [PARTIEL : valeur fictive]") == "OUVERT"
    assert M.etat_roadmap("P2: [OUVERT : valeur fictive]") == "OUVERT"


def test_clos_au_milieu_du_texte_ne_clot_rien():
    assert M.etat_roadmap("P1: le chantier reste a clore, non CLOS") == "OUVERT"
    assert M.etat_roadmap("valeur fictive reste a clore [CLOS] plus tard") == "OUVERT"
    assert M.etat_roadmap("non CLOS : valeur fictive") == "OUVERT"


def test_vide_ou_none_restent_ouverts():
    assert M.etat_roadmap("") == "OUVERT"
    assert M.etat_roadmap(None) == "OUVERT"
