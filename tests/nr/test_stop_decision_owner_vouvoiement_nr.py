"""Owner 6/11, 3e recidive : le garde des decisions en prose ne connaissait que le tutoiement.

« Dites go », « decision a vous » passaient sans AskUserQuestion."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import hook_stop_attente_passive as h  # noqa: E402


@pytest.mark.parametrize("texte", [
    "Dites « go » pour que je continue.",
    "Dites go et je lance la suite.",
    "Non fusionnée : décision à vous.",
    "Ce point attend votre décision.",
    "La suite vous revient.",
    "À vous de choisir entre les deux.",
    "J'attends votre accord pour le push.",
    "J'attends votre go.",
    "Voulez-vous que je fusionne ?",
])
def test_vouvoiement_sans_question_bloque(texte):
    assert h.decider_decision_prose(texte, []) is not None, texte


@pytest.mark.parametrize("texte", [
    "Dites « go » pour que je continue.",
    "Non fusionnée : décision à vous.",
])
def test_question_posee_laisse_passer(texte):
    assert h.decider_decision_prose(texte, ["AskUserQuestion"]) is None


@pytest.mark.parametrize("texte", [
    "Les tests passent, le commit est fait.",
    "Votre choix de la semaine dernière est appliqué.",
    "Le go de l'exécuteur est tombé, 12 tests verts.",
])
def test_compte_rendu_ordinaire_ne_bloque_pas(texte):
    assert h.decider_decision_prose(texte, []) is None, texte


def test_le_tutoiement_reste_couvert():
    assert h.decider_decision_prose("Ceci attend ta décision.", []) is not None


def test_attente_avec_geste_owner_vouvoye_reste_legitime():
    assert h.decider("J'attends le job ; la suite vous revient.", False) is None
