"""tests/test_forge_swarm_telemetry_guard.py - NR pour forge_swarm_telemetry_guard.

Tests hermétiques (pas de réseau UDP réel, pas de coffre : la clé HMAC est une doublure),
vérifie la signature, le rejet de rejeu (replay), et la membrane egress (qui doit échouer
si on tente de broadcaster un secret en texte).
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import forge_swarm_telemetry_guard as _tg
from forge_swarm_telemetry_guard import (
    broadcast_vector,
    ingest_vector,
    sign_vector,
    verify_vector,
    _SECRET_PATTERNS
)


@pytest.fixture(autouse=True)
def _cle_doublee(monkeypatch):
    """Hermétique : sans doublure, _secret() lit le secret du gestionnaire d'intégrité puis
    LAFORGE_TELEMETRY_KEY dans le VRAI coffre. On passe par la couture du module lui-même."""
    monkeypatch.setattr(_tg, "_SECRET_OVERRIDE", b"cle-nr-telemetrie")


def test_telemetry_nominal():
    # Simulation d'un réseau
    network = []
    def mock_send(frame):
        network.append(frame)

    # 1. L'agent A broadcast un vecteur
    payload = b"dummy_vector_data"
    res_bcast = broadcast_vector(mock_send, payload, agent="A", meta={"task": "T1"})
    assert res_bcast["sent"] is True
    assert len(network) == 1

    frame = network[0]

    # 2. L'agent B ingest la frame
    db = []
    def mock_update(vector, agent, meta):
        db.append((vector, agent, meta))

    res_ingest = ingest_vector(frame, update_fn=mock_update, has_meta=True)
    assert res_ingest["ok"] is True
    assert res_ingest["indexed"] is True
    assert len(db) == 1
    assert db[0][0] == payload
    assert db[0][1] == "A"
    assert db[0][2] == {"task": "T1"}


def test_telemetry_guard_egress_blocks_secret():
    # DOIT échouer par garde : on tente d'envoyer un secret en texte
    network = []
    payload = b"Voici mon api_key : 12345"

    res = broadcast_vector(lambda f: network.append(f), payload, agent="A", is_text=True)
    assert res["sent"] is False
    assert "egress refuse" in res["reason"]
    assert len(network) == 0


def test_telemetry_guard_verify_blocks_replay():
    # DOIT échouer par garde : on tente de rejouer une frame périmée
    payload = b"data"
    old_ts = time.time() - 20.0  # 20 secondes dans le passé
    frame = sign_vector(payload, agent="A", ts=old_ts)

    res = ingest_vector(frame, max_age_s=10.0)
    assert res["ok"] is False
    assert "perime/replay" in res["reason"]


def test_telemetry_guard_verify_blocks_tampering():
    # DOIT échouer par garde : on altère la frame (injection)
    payload = b"data"
    frame = bytearray(sign_vector(payload, agent="A"))

    # On modifie un octet du payload à la fin
    frame[-1] ^= 0xFF

    res = ingest_vector(bytes(frame))
    assert res["ok"] is False
    assert "HMAC invalide" in res["reason"]
