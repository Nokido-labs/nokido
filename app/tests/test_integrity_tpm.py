# -*- coding: utf-8 -*-
"""
AXE 8 PR-6 (suite) — CapabilityToken HMAC→TPM (racine matérielle additive).
HMAC toujours vérifié (interop) ; segment TPM optionnel ; require_tpm strict.
"""
import sys
import time
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from nokido_agent.app import forge_integrity as fi  # noqa: E402

SECRET = b"secret-test-integrity"


def _tok():
    now = time.time()
    return fi.CapabilityToken(
        sub="agentX", ring=fi.IntegrityRing(2), scopes={"fs": ["*"]},
        exp=now + 3600, iat=now, jti="jti1", seq=1,
    )


def test_hmac_backward_compat():
    t = _tok().encode(SECRET)
    assert t.count(".") == 1
    assert fi.CapabilityToken.decode(t, SECRET).sub == "agentX"


def test_tpm_sign_fallback_when_unavailable(monkeypatch):
    from nokido_agent.app import forge_persona_tpm as tpm

    monkeypatch.setattr(tpm, "sign", lambda p: None)
    t = _tok().encode(SECRET, tpm_sign=True)
    assert t.count(".") == 1  # retombe sur HMAC seul
    assert fi.CapabilityToken.decode(t, SECRET).sub == "agentX"


def test_tpm_sign_adds_segment_and_verifies(monkeypatch):
    from nokido_agent.app import forge_persona_tpm as tpm

    monkeypatch.setattr(tpm, "sign", lambda p: b"FAKESIG")
    monkeypatch.setattr(tpm, "tpm_available", lambda: True)
    monkeypatch.setattr(tpm, "verify", lambda payload, sig: sig == b"FAKESIG")
    t = _tok().encode(SECRET, tpm_sign=True)
    assert t.count(".") == 2
    d = fi.CapabilityToken.decode(t, SECRET, require_tpm=True)
    assert d.sub == "agentX"


def test_require_tpm_rejects_hmac_only():
    t = _tok().encode(SECRET)
    with pytest.raises(ValueError):
        fi.CapabilityToken.decode(t, SECRET, require_tpm=True)


def test_tampered_tpm_rejected(monkeypatch):
    from nokido_agent.app import forge_persona_tpm as tpm

    monkeypatch.setattr(tpm, "sign", lambda p: b"FAKESIG")
    monkeypatch.setattr(tpm, "tpm_available", lambda: True)
    monkeypatch.setattr(tpm, "verify", lambda payload, sig: False)
    t = _tok().encode(SECRET, tpm_sign=True)
    with pytest.raises(ValueError):
        fi.CapabilityToken.decode(t, SECRET)
