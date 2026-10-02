import pytest
import time
import app.forge_swarm_telemetry_guard as tg

def test_telemetry_comportement_principal():
    tg._SECRET_OVERRIDE = b"secret-test-123"
    
    payload = b"mon_vecteur_dense"
    frame = tg.sign_vector(payload, "agent_1")
    
    # Verification
    v = tg.verify_vector(frame)
    assert v["ok"] is True
    assert v["agent"] == "agent_1"
    assert v["payload"] == payload

def test_telemetry_rejet_perime():
    tg._SECRET_OVERRIDE = b"secret-test-123"
    # Forge une frame vieille de 20 secondes
    frame = tg.sign_vector(b"payload", "agent_1", ts=time.time() - 20)
    
    v = tg.verify_vector(frame, max_age_s=10.0)
    assert v["ok"] is False
    assert "perime/replay" in v["reason"]

def test_telemetry_rejet_hmac_invalide():
    tg._SECRET_OVERRIDE = b"secret-test-123"
    frame = bytearray(tg.sign_vector(b"payload", "agent_1"))
    
    # Alteration de la frame
    frame[-1] = frame[-1] ^ 0xFF
    
    v = tg.verify_vector(bytes(frame))
    assert v["ok"] is False
    assert "HMAC invalide" in v["reason"]

def test_telemetry_egress_membrane():
    # Secret en clair bloque
    assert tg.egress_ok(b"api_key=123", is_text=True) is False
    # Vecteur binaire passe
    assert tg.egress_ok(b"api_key=123", is_text=False) is True
