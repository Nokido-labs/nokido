"""NR — verdict de completude d'un depot (`forge_veille_completude`).

Chaque test encode une regression REELLEMENT payee le 2026-09-08 :

  * `test_le_palier_froid_est_nomme_avant_l_absence_de_vecteur` — le premier jet
    mettait A_REFAIRE en tete et masquait le defaut STRUCTUREL de 678 depots. Un
    depot froid n'a pas de vecteur PARCE QUE la politique les refuse : le declarer
    SANS_VECTEUR enverrait reparer une decision.
  * `test_un_chunker_a_taille_fixe_ne_produit_pas_un_verdict_de_troncature` — un
    premier jet tirait TRONQUE pour 206 depots, dont scalesim a 97 % : c'etait le
    chunker qui travaillait normalement.
  * `test_un_index_lexical_illisible_ne_declare_personne_sain` — ILLISIBLE n'est
    pas VIDE (constitution : `UNKNOWN` != `NO`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "app"))

comp = pytest.importorskip("forge_veille_completude")


def _fiche(**kw):
    base = {"chunks": 100, "vecteurs": 100, "lexical": 100, "tronques": 0,
            "fichiers": 20, "tiers": ["laforge"]}
    base.update(kw)
    return base


def test_un_depot_complet_est_dit_complet():
    v, raison = comp.verdict(_fiche(), True)
    assert v == "COMPLET", (v, raison)


def test_le_palier_froid_est_nomme_avant_l_absence_de_vecteur():
    """Un depot froid est MAL_CLASSE, jamais SANS_VECTEUR : la cause, pas le
    symptome."""
    v, raison = comp.verdict(
        _fiche(vecteurs=0, tiers=["cold-legacy"], fichiers=8358, chunks=174817,
               lexical=174817), True)
    assert v == "MAL_CLASSE", (v, raison)
    assert "cold-legacy" in raison


def test_un_depot_chaud_sans_vecteur_est_dit_sans_vecteur():
    v, _ = comp.verdict(_fiche(vecteurs=0, tiers=["laforge"]), True)
    assert v == "SANS_VECTEUR"


def test_un_chunker_a_taille_fixe_ne_produit_pas_un_verdict_de_troncature():
    """97 % des chunks a la longueur de coupe = decoupage NORMAL."""
    v, _ = comp.verdict(_fiche(tronques=97, chunks=100), True)
    assert v == "COMPLET", "la troncature ne doit plus produire de verdict"
    assert "TRONQUE" not in v


def test_un_lexical_incomplet_est_signale():
    v, raison = comp.verdict(_fiche(lexical=50, chunks=100), True)
    assert v == "LEXICAL_INCOMPLET", (v, raison)
    assert "50/100" in raison


def test_un_index_lexical_illisible_ne_declare_personne_sain():
    """ILLISIBLE n'est pas VIDE : sans le drapeau, tout depot passerait pour
    lexicalement incomplet, ce qui est une panne inventee."""
    v, _ = comp.verdict(_fiche(lexical=0, chunks=100), False)
    assert v != "LEXICAL_INCOMPLET", "verdict rendu sur un canal non lisible"


def test_un_depot_reduit_a_un_fichier_est_a_refaire():
    v, raison = comp.verdict(_fiche(fichiers=1, chunks=15, vecteurs=0), True)
    assert v == "A_REFAIRE", (v, raison)


def test_un_depot_partiellement_vectorise_est_dit_partiel():
    v, raison = comp.verdict(_fiche(vecteurs=676, chunks=10929, lexical=10929), True)
    assert v == "PARTIEL", (v, raison)
    assert "676/10929" in raison
