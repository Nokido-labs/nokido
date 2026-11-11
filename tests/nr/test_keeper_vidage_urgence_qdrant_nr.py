"""Owner 7/11 : au-dela de 85 % et Qdrant > 2 Go, vidage sans attendre le refractaire, avant les 88 % du superviseur."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_docker_keeper as k  # noqa: E402

MAINTENANT = 10_000.0
JUSTE_AVANT = MAINTENANT - 30


def test_urgence_ignore_le_refractaire():
    vider, motif = k.decider_vidage_qdrant(85.1, 6.0, 0.2, JUSTE_AVANT, MAINTENANT)
    assert vider is True and "URGENCE" in motif


@pytest.mark.parametrize("ram", [85.0, 82.0])
def test_sous_le_seuil_le_refractaire_tient(ram):
    assert k.decider_vidage_qdrant(ram, 6.0, 0.2, JUSTE_AVANT, MAINTENANT)[0] is False


def test_qdrant_sous_le_plancher_pas_de_vidage():
    assert k.decider_vidage_qdrant(95.0, 1.5, 0.2, JUSTE_AVANT, MAINTENANT)[0] is False


def test_memoire_privee_majoritaire_pas_de_vidage():
    assert k.decider_vidage_qdrant(95.0, 6.0, 5.0, JUSTE_AVANT, MAINTENANT)[0] is False


def test_voie_sterile_garde_son_refractaire():
    assert k.decider_vidage_qdrant(95.0, 6.0, 0.2, JUSTE_AVANT, MAINTENANT, sterile=1)[0] is False


def test_mesure_illisible_jamais_de_vidage():
    assert k.decider_vidage_qdrant(None, 6.0, 0.2, JUSTE_AVANT, MAINTENANT)[0] is False
