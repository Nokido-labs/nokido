"""NR — cliquet de la liste blanche des lanceurs llama-server.

La liste est celle définie par forge_resource_manager. Seuls ces marqueurs de
preuve autorisent la régulation ; un processus étranger n'est jamais arrêté.
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)


@pytest.fixture
def rm():
    return importlib.import_module("nokido_agent.app.forge_resource_manager")


def _llama():
    return {"nom": "llama-server.exe", "ppid": 1, "rss_mo": 900.0, "cree": 1.0}


def test_liste_blanche_reste_exactement_celle_du_code(rm):
    # Égalité exacte : tout ajout implicite ou explicite à la whitelist fait échouer le NR.
    assert rm._LANCEURS_NOKIDO == frozenset(
        {"superviseur", "job", "battement", "parente"}
    )


def test_regulation_narrete_jamais_letranger_et_regule_nokido(rm):
    vivants = {10: _llama(), 20: _llama()}
    identites = {
        10: {"identite": "LM Studio (application de l'owner)", "preuve": "parent"},
        20: {"identite": "job_x (bench.py)", "preuve": "job"},
    }
    arretes = []

    resultat = rm.reguler_llama_non_justifies(
        vivants=vivants,
        identites=identites,
        non_identifies=[],
        toml={},
        intents={},
        conns={},
        vus={10: 0.0, 20: 0.0},
        now=10_000.0,
        grace_s=300.0,
        kill=lambda pid: arretes.append(pid) or True,
    )

    assert arretes == [20]
    assert [item["pid"] for item in resultat["tues"]] == [20]
    assert [item["pid"] for item in resultat["signales"]] == [10]
    assert "etranger : jamais arrete" in resultat["signales"][0]["raison"]
