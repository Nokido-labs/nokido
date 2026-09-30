# -*- coding: utf-8 -*-
"""NR — A0-3 : l'audit des entrees de l'arbitre ne doit pas se rassurer lui-meme.

Cet outil sert a repondre a UNE question : les entrees de `arbitrer_pression`
sont-elles reellement mesurees ? Il serait donc pire qu'inutile s'il rendait
`MESUREE` sur une valeur absente, perimee ou refusee — il fabriquerait la confiance
qu'il est cense verifier.

Deux entrees ont deja menti sans se signaler, chacune avec un effet different :
`inutile_s` rendait `None` (ValueError avalee sur un horodatage ISO) et l'arbitre
s'abstenait a chaque tick ; `coder_up` venait d'une sonde PowerShell indisponible
depuis le compte du hub, donc toujours son defaut. Dans les deux cas la decision
restait plausible, motivee et journalisee — et fausse.

Le garde tient donc la propriete la plus simple et la plus facile a perdre :
**une non-mesure ne doit jamais ressortir MESUREE**.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

audit = pytest.importorskip("forge_arbitre_entrees_audit")


def test_backlog_perime_est_inconnu():
    """Le cas reel : snapshot vieux de 36 h, `vector_pending` inexploitable."""
    etat, remarque = audit._classer("backlog", (-1, 131300.0, "INCONNU (perime)"), "")
    assert etat == audit.INCONNUE
    assert "backlog=-1" in remarque


def test_backlog_frais_est_mesure():
    etat, _ = audit._classer("backlog", (124659, 120.0, "snapshot"), "")
    assert etat == audit.MESUREE


def test_backlog_vieux_meme_avec_valeur_reste_inconnu():
    """Une valeur PRESENTE mais perimee ne decrit plus le present."""
    etat, remarque = audit._classer("backlog", (124659, 200000.0, "snapshot"), "")
    assert etat == audit.INCONNUE and "perime" in remarque


def test_conns_negatif_est_une_non_mesure():
    """`coder_conns < 0` signifie mesure ABSENTE, pas zero connexion."""
    etat, _ = audit._classer("coder_conns", -1, "")
    assert etat == audit.INCONNUE


def test_coder_incertain_est_une_non_mesure():
    etat, _ = audit._classer("coder_up", "INCERTAIN", "")
    assert etat == audit.INCONNUE
    assert audit._classer("coder_up", "VIVANT", "")[0] == audit.MESUREE
    assert audit._classer("coder_up", "MORT", "")[0] == audit.MESUREE


def test_none_est_une_non_mesure():
    etat, remarque = audit._classer("demande_active", None, "")
    assert etat == audit.INCONNUE and "abstenir" in remarque


def test_une_source_qui_leve_est_illisible():
    etat, remarque = audit._classer("rhythm", None, "ImportError: x")
    assert etat == audit.ILLISIBLE and "ImportError" in remarque


def test_chaque_entree_porte_sa_semantique_et_sa_consommation():
    """Une valeur juste consommee de travers reste un defaut : le contrat doit dire
    ce que l'entree SIGNIFIE et ce que l'arbitre en FAIT."""
    attendues = {"rhythm", "coder_up", "coder_conns", "chains_active", "embed_wanted",
                 "backlog", "embedder_up", "coder_ram_gb", "free_gb",
                 "demande_active", "inutile_s"}
    assert set(audit.CONTRAT) == attendues, \
        "le contrat ne couvre plus exactement les entrees de arbitrer_pression"
    for nom, (src, sens, conso) in audit.CONTRAT.items():
        assert src and sens and conso, "entree %s sans chaine de preuve complete" % nom
