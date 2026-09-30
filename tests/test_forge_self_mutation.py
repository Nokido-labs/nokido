#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tests/test_forge_self_mutation.py — garde-fous de la boucle de mutation.

La boucle d'auto-amelioration (LOCAL_SAFE_MUTATION_V1) a ete perdue le
2026-03-26 par `chore: clean hackathon branch — remove 651 non-essential files`.
Elle est remise en service branchee sur les gardes actuels. Ces tests portent
sur ce qui rend la remise en service acceptable : le garde doit REFUSER une
mutation degradee, et ne jamais taire une regle qu'il n'a pas pu executer.

Hermetiques : aucun LLM, aucun NPU, aucune lecture du working tree.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from forge_self_mutation import MutationGuard, fichier_protege  # noqa: E402

ORIGINAL = '''"""Module de demonstration."""


class Moteur:
    """Fait tourner quelque chose."""

    def demarrer(self, vitesse: int) -> bool:
        """Demarre le moteur."""
        self.vitesse = vitesse
        return True

    def arreter(self) -> bool:
        """Arrete le moteur."""
        self.vitesse = 0
        return True


def aide(nom: str) -> str:
    """Rend un message d aide."""
    return "aide pour " + nom
'''


def _guard():
    return MutationGuard()


def test_refuse_syntaxe_cassee():
    ok, motif = _guard().valider(ORIGINAL, "class Moteur(:\n    pass")
    assert ok is False
    assert "syntaxe" in motif.lower()


def test_refuse_troncation():
    """Perdre plus de 20 % des lignes est une troncation, pas un refactor."""
    tronque = '''"""Module de demonstration."""


class Moteur:
    """Fait tourner quelque chose."""

    def demarrer(self, vitesse: int) -> bool:
        """Demarre le moteur."""
        return True
'''
    ok, motif = _guard().valider(ORIGINAL, tronque)
    assert ok is False
    assert "troncation" in motif.lower()


def test_refuse_classe_disparue():
    ampute = ORIGINAL.replace("class Moteur:", "class Autre:")
    ok, motif = _guard().valider(ORIGINAL, ampute)
    assert ok is False
    assert "moteur" in motif.lower()


def test_refuse_fonction_inventee():
    invente = ORIGINAL + '''

def bonus_invente(x: int) -> int:
    """Fonction que personne n a demandee."""
    return x
'''
    ok, motif = _guard().valider(ORIGINAL, invente)
    assert ok is False
    assert "inventee" in motif.lower() or "invente" in motif.lower()


def test_refuse_docstring_perdue():
    sans_doc = ORIGINAL.replace('        """Demarre le moteur."""\n', "")
    ok, motif = _guard().valider(ORIGINAL, sans_doc)
    assert ok is False
    assert "docstring" in motif.lower()


def test_refuse_type_hint_perdu():
    sans_hint = ORIGINAL.replace("def demarrer(self, vitesse: int) -> bool:",
                                 "def demarrer(self, vitesse) -> bool:")
    ok, motif = _guard().valider(ORIGINAL, sans_hint)
    assert ok is False
    assert "type" in motif.lower()


def test_accepte_mutation_legitime():
    """Un vrai refactor conserve structure, docstrings et annotations."""
    mute = ORIGINAL.replace(
        '        self.vitesse = vitesse\n        return True',
        '        self.vitesse = max(0, vitesse)\n        return True')
    ok, motif = _guard().valider(ORIGINAL, mute)
    assert ok is True, motif


def test_regle_non_executee_est_declaree():
    """Une regle qu'on n'a pas pu executer doit apparaitre, jamais disparaitre.

    C'est le coeur du probleme : un garde vert sans mesure vaut un garde absent.
    """
    g = MutationGuard(embedder=None)
    ok, _motif = g.valider(ORIGINAL, ORIGINAL.replace("aide pour ", "aide de "))
    assert ok is True
    assert any(r["regle"] == "derive_semantique" and r["etat"] == "NON_EXECUTEE"
               for r in g.rapport), g.rapport


def test_derive_semantique_refuse_quand_embedder_present():
    class EmbedderFactice:
        """Rend des vecteurs orthogonaux : similarite nulle."""

        available = True

        def encode(self, textes):
            return [[1.0, 0.0] if i == 0 else [0.0, 1.0]
                    for i, _ in enumerate(textes)]

    ok, motif = MutationGuard(embedder=EmbedderFactice()).valider(
        ORIGINAL, ORIGINAL.replace("aide pour ", "aide de "))
    assert ok is False
    assert "derive" in motif.lower()


@pytest.mark.parametrize("chemin", [
    "tools/bash_guard.py",
    "tools/hook_posttool_validate.py",
    "app/forge_semantic_firewall.py",
    "tools/laforge_hub.py",
    "app/forge_self_mutation.py",
])
def test_refuse_de_muter_ses_propres_gardes(chemin):
    """Le systeme ne doit jamais reecrire ce qui le surveille, ni lui-meme."""
    assert fichier_protege(chemin) is True


def test_autorise_un_module_ordinaire():
    assert fichier_protege("app/forge_novelty_search.py") is False
