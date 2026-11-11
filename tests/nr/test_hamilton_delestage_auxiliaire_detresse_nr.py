# -*- coding: utf-8 -*-
"""NR (debat 2 tour 2, 3/11, accord Claude x AGY) : sous DETRESSE critique, une pression NON_SOI (le corps ne la porte
pas : carcasse WSL, navigateur...) -> le delestage AUXILIAIRE (les seuls services DIFFERABLE) est OBSERVE, jamais
execute : le rejeu de la fenetre reelle du 28/10 (test_regulation_replay_nr) montre qu'actif il endormait des
executeurs EN TACHE. Hors detresse : rien d'observe. UTILE et VITAL jamais. INCERTAIN ou illisible : rien (UNKNOWN
n'est pas une permission). Promotion en action = decision owner, sur mesure.

Livraisons refusees avant ce NR : 74f27169f (GPT-OSS, branche morte + RAM utilisee au lieu de libre), a71c4d7e2 (GLM,
convention `auxiliary*` inventee)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_resource_manager as RM  # noqa: E402

CANDIDATS = [{"service": "A_diff_petit", "classe": "DIFFERABLE", "rss_mb": 300},
             {"service": "B_diff_gros", "classe": "DIFFERABLE", "rss_mb": 900},
             {"service": "C_utile", "classe": "UTILE", "rss_mb": 2000},
             {"service": "D_vital", "classe": "VITAL", "rss_mb": 5000}]


def _noms(plan):
    return [c["service"] for c in plan["delester"]]


def test_non_soi_hors_detresse_reste_signale_jamais_deleste():
    plan = RM.ordre_delestage(CANDIDATS, "NON_SOI", detresse=False)
    assert plan["delester"] == [] and not plan.get("auxiliaire_observe")


def test_non_soi_en_detresse_observe_les_auxiliaires_sans_agir():
    plan = RM.ordre_delestage(CANDIDATS, "NON_SOI", detresse=True)
    assert plan["delester"] == []                                   # aucune action
    assert [c["service"] for c in plan["auxiliaire_observe"]] == ["B_diff_gros", "A_diff_petit"]  # gros d'abord


def test_soi_en_detresse_inchange():
    plan = RM.ordre_delestage(CANDIDATS, "SOI", detresse=True)
    assert _noms(plan) == ["B_diff_gros", "A_diff_petit", "C_utile"]


def test_incertain_ou_illisible_en_detresse_aucune_action():
    for verdict in ("INCERTAIN", "NOYAU", None, "ILLISIBLE"):
        plan = RM.ordre_delestage(CANDIDATS, verdict, detresse=True)
        assert plan["delester"] == [] and not plan.get("auxiliaire_observe"), verdict
