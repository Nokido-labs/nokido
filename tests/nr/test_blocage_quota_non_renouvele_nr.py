"""NR -- un refus de l'executeur ne renouvelle pas un blocage de quota (mesure du 6/11).

MISTRAL etait refuse a 17:08 alors que son echeance de 16:06:18 etait passee : le motif du refus cite « quota exceeded », donc
`_noter_indisponibilite` y lisait un nouvel epuisement et posait six heures de plus. Chaque refus prolongeait la suspension.
Un vrai quota rendu par le CLI reste note.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)
RACINE = Path(__file__).resolve().parents[2]
ANCIEN = "quota epuise jusqu'a 2026-11-06T16:06:18 (quota exceeded (journal OpenCode) : level=ERROR message=stream error)"


@pytest.fixture(scope="module")
def executeur():
    spec = importlib.util.spec_from_file_location("blocage_quota_executeur_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["blocage_quota_executeur_nr"] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def marques(executeur, monkeypatch):
    vues = []
    monkeypatch.setattr(executeur, "marquer_surface_indisponible", lambda a, m="", jusqu_a=None, **k: vues.append((a, jusqu_a)))
    return vues


@pytest.mark.parametrize("motif", [
    "MODELE HORS QUOTA : mistral:codestral-latest " + ANCIEN,
    "MISTRAL INDISPONIBLE (MODELE HORS QUOTA : mistral:codestral-latest " + ANCIEN + ")",
])
def test_un_refus_de_l_executeur_ne_prolonge_rien(executeur, marques, motif):
    assert executeur._noter_indisponibilite("MISTRAL", motif) is False
    assert marques == []


def test_un_vrai_quota_rendu_par_le_cli_reste_note(executeur, marques):
    assert executeur._noter_indisponibilite("MISTRAL", "erreur ACP OpenCode", "quota exceeded (journal OpenCode) : stream error") is True
    assert marques and marques[0][0] == "MISTRAL"


def test_un_refus_avec_rendu_reel_reste_note(executeur, marques):
    """Le texte de l'agent prime : un rendu reel de quota n'est pas un refus interne."""
    assert executeur._noter_indisponibilite("MISTRAL", "MODELE HORS QUOTA : x", "quota exceeded (journal OpenCode)") is True
