#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tests/nr/test_capability_lineage_nr.py — l'automate de lignees dit-il vrai ?

Deux facons de se tromper, toutes deux mesurees le 2026-08-16 :

1. Le DEPLACEMENT. En `-U0`, bouger une fonction dans son fichier produit `-def x`
   PUIS `+def x` dans le MEME commit. Sans agregation par commit, chaque refactor
   devient une mort suivie d'une resurrection -- du bruit en volume.
2. Le nom COMMUN. `source`, `save`, `description` sont des cles de dict, pas des
   capacites. Sans mesure de dispersion, le rapport en etait noye.

Hermetiques : aucun git, aucun working tree.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.57)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_ajout_et_retrait_sont_detectes_symetriquement():
    """Le meme detecteur sert aux deux prefixes : ils ne peuvent pas diverger."""
    import forge_capability_lineage as L

    assert L._detecter_ajout("+def axe_workflows():") == ("fonction", "axe_workflows")
    assert L._detecter_ajout("+class ProviderSlot:") == ("classe", "ProviderSlot")
    assert L._detecter_ajout("-def axe_workflows():") is None  # retrait, pas ajout
    assert L._detecter_ajout("+    resultat = axe_workflows()") is None  # usage


def test_un_deplacement_dans_un_commit_ne_tue_rien():
    """`-def x` + `+def x` au meme commit = net nul. Sinon tout refactor crie."""
    import forge_capability_lineage as L

    ajoutes = {("fonction", "x")}
    retires = {("fonction", "x")}
    assert not (retires - ajoutes), "le net doit etre vide : deplacement, pas suppression"
    assert not (ajoutes - retires)


def test_etat_distingue_un_retour_dune_naissance_unique():
    import forge_capability_lineage as L

    assert L._etat({"present": True, "apparitions": 1}) == "VIVANT"
    assert L._etat({"present": True, "apparitions": 3}) == "RESSUSCITE"
    assert L._etat({"present": False, "apparitions": 1}) == "PERDU"
    assert L._etat({"present": False, "apparitions": 2}) == "PERDU_APRES_RETOURS"


def test_aucun_depot_lisible_rend_indetermine(tmp_path):
    """Un dossier sans depot n'est pas une histoire vide : c'est une non-mesure."""
    import forge_capability_lineage as L

    res = L.analyser({"faux": str(tmp_path)}, max_lignes=10)
    assert res.get("observable") is False
    assert "faux" in res.get("raison", "")


def test_la_phase7_reutilise_le_detecteur_de_la_phase6():
    """Deux detecteurs finiraient par diverger ; on verifie qu'il n'y en a qu'un."""
    import forge_capability_lineage as L
    import forge_constituent_archaeology as A

    assert L.A is A
