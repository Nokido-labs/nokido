# -*- coding: utf-8 -*-
"""NR - le hub classe le bearer : format maison (payload.sig[.tpm]) ET JWT standard (h.p.s), sans repli silencieux."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

MAITRE = "maitre-factice-0123456789"


def _b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def _claims(ring=3):
    return {"sub": "AGENT_NR", "ring": ring, "exp": time.time() + 120, "iat": time.time(), "jti": "j-nr"}


@pytest.fixture
def hub(monkeypatch, tmp_path):
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LAFORGE_DATA_DIR", raising=False)
    import nokido_hub as h
    monkeypatch.setattr(h, "HUB_TOKEN", MAITRE, raising=False)
    monkeypatch.setattr(h, "_AGENT_TOKENS", {}, raising=False)
    return h


@pytest.fixture
def secret():
    from nokido_agent.app.forge_integrity import get_manager
    return get_manager()._secret


def _req(tok):
    return SimpleNamespace(headers={"Authorization": "Bearer " + tok, "LaForge-Agent-Name": "AGENT_NR"},
                           client=SimpleNamespace(host="127.0.0.1"))


def _maison(secret, claims):
    p = _b64(claims)
    return p + "." + hmac.new(secret, p.encode("ascii"), hashlib.sha256).hexdigest()


def _jwt(secret, claims, header=None, bad_sig=False):
    h = _b64(header or {"alg": "HS256", "typ": "JWT"})
    p = _b64(claims)
    sig = hmac.new(secret, (h + "." + p).encode("ascii"), hashlib.sha256).digest()
    if bad_sig:
        sig = bytes(b ^ 1 for b in sig)
    return h + "." + p + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")


def test_format_maison_accepte_comme_avant(hub, secret):
    assert hub._resolve_ring(_req(_maison(secret, _claims(3)))) == (3, "AGENT_NR")


def test_jwt_standard_bien_signe_refuse(hub, secret):
    assert hub._resolve_ring(_req(_jwt(secret, _claims(3)))) == (-1, "jwt_standard_non_pris_en_charge")


def test_jwt_ring_du_payload_jamais_rendu(hub, secret):
    for ring in (0, 1, 3):
        r, qui = hub._resolve_ring(_req(_jwt(secret, _claims(ring))))
        assert r == -1 and qui != "AGENT_NR"


def test_maison_trois_parties_tpm_inchange(hub, secret):
    tok = _maison(secret, _claims(3)) + ".tpmx"
    assert hub._resolve_ring(_req(tok)) != (-1, "jwt_standard_non_pris_en_charge")


def test_jwt_signature_invalide_refuse(hub, secret):
    ring, _qui = hub._resolve_ring(_req(_jwt(secret, _claims(3), bad_sig=True)))
    assert ring == -1


def test_jwt_alg_none_ou_inconnu_refuse(hub, secret):
    for alg in ("none", "RS256"):
        tok = _jwt(secret, _claims(3), header={"alg": alg, "typ": "JWT"})
        assert hub._resolve_ring(_req(tok))[0] == -1


def test_trois_points_non_decodable_refuse_pas_bearer_brut(hub):
    ring, qui = hub._resolve_ring(_req("abc.def.ghi"))
    assert ring == -1 and qui == "malformed_bearer"
