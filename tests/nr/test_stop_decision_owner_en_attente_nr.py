"""Owner 10/11, 4e recidive (« fait moi un choix multiple pour les choix user, deja dit 1000 fois ! ancre le »).

Compte rendu fini par « Toujours en attente de ta décision : supprimer les branches archivées, GO push, et passer
Docker en VMM » : le garde Stop connaissait « attend ta décision » et « en attente de toi », pas « en attente de ta
décision » ni « décisions en attente ». Les trois choix sont partis en prose au lieu d'AskUserQuestion.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import hook_stop_attente_passive as h  # noqa: E402


@pytest.mark.parametrize("texte", [
    "Toujours en attente de ta décision : supprimer les branches archivées, GO push, et passer Docker en VMM.",
    "En attente de votre décision : GO push.",
    "Décisions en attente : suppression des branches, push.",
    "Décision en attente owner : bascule Docker VMM.",
    "Reste en attente de ton accord pour le push.",
    "Le push attend ton go.",
    "Ceci attend votre accord.",
])
def test_attente_de_decision_sans_question_bloque(texte):
    assert h.decider_decision_prose(texte, []) is not None, texte


def test_question_posee_laisse_passer():
    assert h.decider_decision_prose("Toujours en attente de ta décision : GO push.", ["AskUserQuestion"]) is None


@pytest.mark.parametrize("texte", [
    "Ta décision du 9/11 est appliquée, push fait.",
    "Le job est en attente de RAM, relance en job ensuite.",
    "Choix notés : push après le pré-vol vert.",
])
def test_compte_rendu_ordinaire_ne_bloque_pas(texte):
    assert h.decider_decision_prose(texte, []) is None, texte
