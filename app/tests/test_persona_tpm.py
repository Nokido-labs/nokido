# -*- coding: utf-8 -*-
"""
PR-6 AXE 8 — racine de confiance matérielle (TPM) de la persona.
TPM-backed si dispo, fallback HMAC sinon. Tests résilients (skip round-trip si pas de TPM).
"""
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from nokido_agent.app import forge_persona_tpm as tpm  # noqa: E402


def test_tpm_available_is_bool():
    assert isinstance(tpm.tpm_available(), bool)


def test_ensure_key_never_crashes():
    assert isinstance(tpm.ensure_persona_key(), bool)


def _cle_injectee(monkeypatch):
    # Cle persona INJECTEE (2b-1, 2026-09-28) : la vraie n'est lisible que sous SYSTEM,
    # et sans cle `sign_identity` rend `aucune:` au lieu d'un tag signe d'une cle devinee.
    monkeypatch.setattr(tpm, "get_secret", lambda k, required=False:
                        "clef-test-fixe" if k == "FORGE_PERSONA_HMAC_KEY" else None)


def test_sign_identity_tagged(monkeypatch):
    _cle_injectee(monkeypatch)
    tag = tpm.sign_identity("identité Nokido test")
    assert isinstance(tag, str)
    assert tag.startswith("tpm:") or tag.startswith("hmac:")
    assert len(tag.split(":")[1]) == 16


def test_hmac_fallback_deterministic(monkeypatch):
    _cle_injectee(monkeypatch)
    # Force le chemin HMAC en simulant TPM absent
    monkeypatch.setattr(tpm, "sign", lambda payload: None)
    a = tpm.sign_identity("meme texte")
    b = tpm.sign_identity("meme texte")
    c = tpm.sign_identity("autre texte")
    assert a == b and a.startswith("hmac:")
    assert a != c


def test_tpm_round_trip_if_available():
    if not tpm.tpm_available() or not tpm.ensure_persona_key():
        pytest.skip("TPM indisponible dans cet env")
    payload = b"nokido persona payload"
    sig = tpm.sign(payload)
    if sig is None:
        pytest.skip("sign TPM indispo")
    assert tpm.verify(payload, sig) is True
    assert tpm.verify(b"payload altere", sig) is False


def test_persona_anchor_sig_optin(monkeypatch):
    from nokido_agent.app import forge_persona_engine as pe

    eng = pe.PersonaEngine()
    # off par défaut
    monkeypatch.delenv("FORGE_PERSONA_SIGN", raising=False)
    assert "[ANCHOR_SIG:" not in eng.build_system_prompt("laforge", turn=5)
    # opt-in
    monkeypatch.setenv("FORGE_PERSONA_SIGN", "1")
    assert "[ANCHOR_SIG:" in eng.build_system_prompt("laforge", turn=5)
