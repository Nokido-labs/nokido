# -*- coding: utf-8 -*-
"""Unit tests for the short-lived CapabilityTokens brick."""
from __future__ import annotations

import time
import hmac
import hashlib
import pytest
from unittest.mock import patch

from forge_integrity import CapabilityToken, TokenExpiredError, get_manager, IntegrityRing
from forge_auth_tokens import login_agent

@pytest.fixture(autouse=True)
def setup_secret(monkeypatch):
    # Enforce a predictable secret for integrity verification
    monkeypatch.setenv("MCP_DEV_SECRET", "super_secret_dev_key_for_testing")
    yield

def test_login_with_secret_id():
    mock_agent_tokens = {
        "CLAUDE": "mock_secret_claude_123",
        "GEMINI": "mock_secret_gemini_456"
    }
    
    # 1. Login with correct secret_id
    token_str = login_agent(
        role_id="CLAUDE",
        secret_id="mock_secret_claude_123",
        agent_tokens=mock_agent_tokens
    )
    assert token_str is not None
    assert token_str.count(".") in (1, 2) # payload.sig or payload.sig.tpm_sig
    
    # 2. Verify the generated token
    mgr = get_manager()
    token = CapabilityToken.decode(token_str, mgr._secret)
    assert token.sub == "CLAUDE"
    assert token.ring == IntegrityRing.DEV
    assert token.exp > time.time()
    assert (token.exp - token.iat) == pytest.approx(1800, abs=10) # 30 minutes lease
    
    # 3. Login with incorrect secret_id must fail
    with pytest.raises(ValueError, match="Invalid credentials"):
        login_agent(
            role_id="CLAUDE",
            secret_id="wrong_secret",
            agent_tokens=mock_agent_tokens
        )

def test_login_with_persona_signature(monkeypatch):
    # Verify using the HMAC signature fallback -- HERMETIQUE depuis 2b-1 (2026-09-28) :
    # la vraie cle n'est lisible que sous SYSTEM (ACL owner) et l'HMAC persona est
    # refuse aux rings <= DEV. Cle et ring sont donc INJECTES ; GEMINI pose en TRUSTED.
    import sys
    from nokido_agent.app import forge_persona_tpm as tpm
    cle = b"cle-persona-test-capability-tokens"
    monkeypatch.setattr(tpm, "_hmac_key", lambda: cle)
    monkeypatch.setattr(tpm, "verify", lambda payload, sig: False)
    monkeypatch.setattr(sys.modules[login_agent.__module__], "_load_store",
                        lambda: {"GEMINI": 2})
    _hmac_key = tpm._hmac_key
    
    role_id = "GEMINI"
    timestamp = time.time()
    payload_bytes = f"{role_id}:{timestamp}".encode("utf-8")
    
    # Create valid HMAC signature
    sig = hmac.new(_hmac_key(), payload_bytes, hashlib.sha256).digest()
    sig_hex = sig.hex()
    
    # 1. Login with correct signature
    token_str = login_agent(
        role_id=role_id,
        timestamp=timestamp,
        signature=sig_hex
    )
    assert token_str is not None
    
    # Verify token claims
    mgr = get_manager()
    token = CapabilityToken.decode(token_str, mgr._secret)
    assert token.sub == "GEMINI"
    assert token.ring == IntegrityRing.TRUSTED
    
    # 2. Login with incorrect signature must fail
    with pytest.raises(ValueError, match="Signature verification failed|Invalid credentials"):
        login_agent(
            role_id=role_id,
            timestamp=timestamp,
            signature="bad_signature_hex_123"
        )
        
    # 3. Replay attack: login with expired timestamp must fail
    old_timestamp = time.time() - 400 # > 300s window
    old_payload = f"{role_id}:{old_timestamp}".encode("utf-8")
    old_sig = hmac.new(_hmac_key(), old_payload, hashlib.sha256).hexdigest()
    
    with pytest.raises(ValueError, match="Timestamp skew too large"):
        login_agent(
            role_id=role_id,
            timestamp=old_timestamp,
            signature=old_sig
        )

def test_token_expiration():
    mgr = get_manager()
    # Create a token that expires instantly (expired 10s ago)
    token = CapabilityToken(
        sub="TEST_AGENT",
        ring=IntegrityRing.TRUSTED,
        scopes={"fs": ["read"]},
        exp=time.time() - 10,
        iat=time.time() - 100,
        jti="test_jti",
        seq=1
    )
    token_str = token.encode(mgr._secret)
    
    # Decoding must raise TokenExpiredError
    with pytest.raises(TokenExpiredError):
        CapabilityToken.decode(token_str, mgr._secret)

def test_tampered_token_rejection():
    mgr = get_manager()
    token = CapabilityToken(
        sub="TEST_AGENT",
        ring=IntegrityRing.TRUSTED,
        scopes={"fs": ["read"]},
        exp=time.time() + 1000,
        iat=time.time(),
        jti="test_jti",
        seq=1
    )
    token_str = token.encode(mgr._secret)
    
    # Corrupt the signature part
    parts = token_str.split(".")
    parts[1] = "badsignature123"
    tampered_str = ".".join(parts)
    
    with pytest.raises(ValueError, match="Signature HMAC invalide"):
        CapabilityToken.decode(tampered_str, mgr._secret)


@pytest.mark.asyncio
async def test_auth_login_endpoint_handler():
    import sys
    from pathlib import Path
    tools_dir = str(Path(__file__).resolve().parent.parent / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from nokido_hub import auth_login
    
    # Mock Starlette Request
    class MockRequest:
        def __init__(self, json_data):
            self._json = json_data
        async def json(self):
            return self._json
            
    req = MockRequest({
        "role_id": "CLAUDE",
        "secret_id": "mock_secret_claude_123"
    })
    
    mock_agent_tokens = {
        "CLAUDE": "mock_secret_claude_123"
    }
    
    with patch("nokido_hub._AGENT_TOKENS", mock_agent_tokens), \
         patch("nokido_hub.HUB_TOKEN", "mock_master_token"):
        resp = await auth_login(req)
        assert resp.status_code == 200
        
        import json
        body = json.loads(resp.body.decode())
        assert "token" in body
        assert body["expires_in"] == 1800

