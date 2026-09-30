# -*- coding: utf-8 -*-
"""Non-regression — l'agregat du rendement collectif DIT sur quoi il porte.

Module vise : `tools/forge_collective_gain.py`, designe orphelin par le cliquet de
couverture NR (`test_nr_coverage_ratchet_nr`) le 2026-08-26 — il etait le seul module
ajoute apres le socle que AUCUN test ne nommait, et c'est ce qui tenait la CI rouge.

Ce qui est verrouille ici est la doctrine du 2026-08-26, pas de l'arithmetique :

1. **Le denominateur est publie.** Une moyenne sur les seules taches mesurees,
   presentee sans son denominateur, ferait passer 2 succes sur 20 essais pour 100 %.
2. **DEUX baselines, jamais une.** Compare au seul `oracle` (meilleure tentative), le
   collectif perd TOUJOURS -- l'arbitrage choisit PARMI les tentatives, il ne peut pas
   depasser la meilleure. Compare au seul `moyen`, il gagne TOUJOURS. Les deux ensemble
   disent la verite, et `degrade` devient un resultat qui se compte.
3. **CONTESTEE n'est pas NON MESUREE.** Deux tentatives prouvees qui s'opposent = le
   collectif a TROUVE sans TRANCHER : un cout de POLITIQUE, pas une absence de mesure.
   Les confondre avait fausse ma propre mesure sur 2 taches sur 3.
4. **Le plafond de voix se signale.** Quand toutes les tentatives partent au meme modele,
   `voix_independantes` plafonne a 1 et toute politique exigeant 2 voix est inatteignable
   PAR CONSTRUCTION -- mesure : 5 reponses justes sur 6, zero acceptee.

Hermetique : aucune tentative n'appelle un LLM, tout est construit en memoire.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

CG = pytest.importorskip("forge_collective_gain")


def ligne(gain=None, tokens=0, appels=0, voix=0):
    return {"gain": gain or {}, "cout": {"tokens": tokens, "appels": appels},
            "voix_independantes": voix}


def gain(moyen=0.0, oracle=0.0, degrade=False, livre=True, mesurees=2, ktok=None):
    g = {"gain_vs_moyen": moyen, "gain_vs_oracle": oracle, "degrade": degrade,
         "livre": livre, "mesurees": mesurees}
    if ktok is not None:
        g["gain_ajuste_par_ktokens"] = ktok
    return g


# ------------------------------------------------------- le denominateur est publie

def test_agregat_vide_n_affirme_rien():
    """Zero tache : aucune moyenne inventee, et une lecture qui le DIT."""
    out = CG.agreger([])
    assert out["taches"] == 0 and out["mesurees"] == 0
    assert out["gain_vs_moyen_moyen"] is None
    assert out["taux_degradation"] is None
    assert "AUCUNE tache mesuree" in out["lecture"]


def test_les_non_mesurees_sont_comptees_pas_ignorees():
    """LE test du denominateur : 1 mesuree sur 3 ne doit pas se lire comme 3 sur 3."""
    out = CG.agreger([ligne(gain(moyen=0.5, oracle=0.0)), ligne(), ligne()])
    assert out["taches"] == 3
    assert out["mesurees"] == 1
    assert out["non_mesurees"] == 2, "une tache sans gain doit rester visible"


def test_refus_videur_dit_ampute_et_non_nul():
    out = CG.agreger([ligne(gain(moyen=0.5))], refus_videur=2)
    assert out["refus_videur"] == 2
    assert "AMPUTE" in out["lecture"], "un echantillon ampute n'est pas un echantillon nul"


# -------------------------------------------------------------- les deux baselines

def test_les_deux_baselines_sont_rendues():
    out = CG.agreger([ligne(gain(moyen=0.5, oracle=-0.25))])
    assert out["gain_vs_moyen_moyen"] == 0.5
    assert out["gain_vs_oracle_moyen"] == -0.25, (
        "l'oracle NEGATIF est le signal utile : le collectif n'a pas su retenir "
        "la meilleure tentative")


def test_moyennes_sur_les_seules_mesurees():
    out = CG.agreger([ligne(gain(moyen=1.0, oracle=0.0)),
                      ligne(gain(moyen=0.0, oracle=0.0)),
                      ligne()])
    assert out["gain_vs_moyen_moyen"] == 0.5, "diviser par 3 melangerait mesure et absence"


def test_degradation_comptee_et_son_taux():
    """Le cas negatif est un RESULTAT qui se compte, pas une hypothese."""
    out = CG.agreger([ligne(gain(moyen=-0.5, degrade=True)), ligne(gain(moyen=0.5))])
    assert out["degradees"] == 1
    assert out["taux_degradation"] == 0.5


# ------------------------------------------------- contestee n'est pas non mesuree

def test_contestee_distinguee_de_non_mesuree():
    """Deux prouvees qui s'opposent : TROUVE sans TRANCHER."""
    out = CG.agreger([ligne({"livre": False, "mesurees": 2, "gain_vs_moyen": None})])
    assert out["contestees"] == 1
    assert out["mesurees"] == 0, "non tranchee, donc hors des moyennes"
    assert out["non_mesurees"] == 1


def test_rien_a_comparer_n_est_pas_contestee():
    """`livre=False` SANS tentative prouvee = il n'y avait rien a arbitrer."""
    out = CG.agreger([ligne({"livre": False, "mesurees": 0})])
    assert out["contestees"] == 0


# ----------------------------------------------------------- le plafond de voix

def test_plafond_de_voix_signale_quand_une_seule_voix_pour_n_appels():
    """Le defaut de cablage mesure : N appels, UNE voix."""
    out = CG.agreger([ligne(gain(moyen=0.0), appels=3, voix=1)])
    assert "plafond_de_voix" in out
    assert "MEME modele" in out["plafond_de_voix"]


def test_pas_de_plafond_quand_la_diversite_est_reelle():
    out = CG.agreger([ligne(gain(moyen=0.0), appels=3, voix=2)])
    assert "plafond_de_voix" not in out, "2 voix = la diversite de modele est acquise"


def test_pas_de_plafond_quand_un_seul_appel_par_tache():
    """Une voix pour un appel est normal : ce n'est pas un fanout."""
    out = CG.agreger([ligne(gain(moyen=0.0), appels=1, voix=1)])
    assert "plafond_de_voix" not in out


def test_voix_max_est_un_maximum_pas_une_moyenne():
    out = CG.agreger([ligne(gain(moyen=0.0), voix=1), ligne(gain(moyen=0.0), voix=3)])
    assert out["voix_independantes_max"] == 3


# ------------------------------------------------------------------ le cout brut

def test_cout_somme_sur_toutes_les_taches_meme_non_mesurees():
    """Une tache non mesuree a quand meme COUTE : l'oublier flatterait le ratio."""
    out = CG.agreger([ligne(gain(moyen=0.5), tokens=1000, appels=2),
                      ligne(tokens=713, appels=1)])
    assert out["tokens"] == 1713
    assert out["appels_llm"] == 3


def test_cout_absent_ne_leve_pas():
    out = CG.agreger([{"gain": gain(moyen=0.5)}])
    assert out["tokens"] == 0 and out["appels_llm"] == 0
