"""Phase 23C JWT HS256 tests."""
import os
import time
import pytest
import forge_auth_jwt as jwt


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setenv("LAFORGE_JWT_SECRET", "test_secret_xyz_123")
    monkeypatch.delenv("FORGE_MCP_TOKEN", raising=False)
    yield


@pytest.fixture(autouse=True)
def _secrets_de_l_environnement_seul(monkeypatch):
    """`get_secret` lit le coffre machine AVANT l'environnement. Sous un compte qui le
    lit, le « secret manquant » de ces tests etait le VRAI secret JWT, et les
    round-trips signaient avec lui, pas avec leur secret de test (mesure 2026-09-28,
    LaForgeSbxOffline). Ces tests parlent de l'environnement : on les y enferme."""
    monkeypatch.setattr(jwt, "get_secret", lambda k: os.environ.get(k) or None)
    yield


def test_issue_then_verify_round_trip():
    tok = jwt.issue_token("agt_test", scopes=["services:start"], ttl_s=60)
    assert tok.count(".") == 2
    claims = jwt.verify_token(tok)
    assert claims is not None
    assert claims["sub"] == "agt_test"
    assert "services:start" in claims["scope"]


def test_verify_with_scope_match():
    tok = jwt.issue_token("agt", scopes=["services:start", "services:stop"], ttl_s=60)
    assert jwt.verify_token(tok, required_scope="services:start") is not None
    assert jwt.verify_token(tok, required_scope="services:stop") is not None
    assert jwt.verify_token(tok, required_scope="admin:shutdown_all") is None


def test_verify_wildcard_scope():
    tok = jwt.issue_token("agt_admin", scopes=["admin:*"], ttl_s=60)
    assert jwt.verify_token(tok, required_scope="admin:shutdown_all") is not None
    assert jwt.verify_token(tok, required_scope="admin:anything") is not None
    assert jwt.verify_token(tok, required_scope="services:start") is None


def test_verify_star_scope_matches_all():
    tok = jwt.issue_token("root", scopes=["*"], ttl_s=60)
    assert jwt.verify_token(tok, required_scope="services:start") is not None
    assert jwt.verify_token(tok, required_scope="admin:shutdown_all") is not None


def test_tampered_signature_rejected():
    tok = jwt.issue_token("agt", scopes=["x"], ttl_s=60)
    bad = tok[:-4] + "AAAA"  # corrupt signature
    assert jwt.verify_token(bad) is None


def test_tampered_payload_rejected():
    tok = jwt.issue_token("agt", scopes=["x"], ttl_s=60)
    parts = tok.split(".")
    # modify 1 char in payload
    parts[1] = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
    bad = ".".join(parts)
    assert jwt.verify_token(bad) is None


def test_expired_token_rejected():
    tok = jwt.issue_token("agt", scopes=["x"], ttl_s=-100)  # already expired
    assert jwt.verify_token(tok, leeway_s=0) is None


def test_missing_secret_returns_none_on_verify(monkeypatch):
    monkeypatch.delenv("LAFORGE_JWT_SECRET", raising=False)
    monkeypatch.delenv("FORGE_MCP_TOKEN", raising=False)
    # token genere avant : si plus de secret, verify fail
    monkeypatch.setenv("LAFORGE_JWT_SECRET", "tmp")
    tok = jwt.issue_token("agt", ttl_s=60)
    monkeypatch.delenv("LAFORGE_JWT_SECRET", raising=False)
    assert jwt.verify_token(tok) is None


def test_missing_secret_raises_on_issue(monkeypatch):
    monkeypatch.delenv("LAFORGE_JWT_SECRET", raising=False)
    monkeypatch.delenv("FORGE_MCP_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="manquant"):
        jwt.issue_token("agt", ttl_s=60)


def test_malformed_token_rejected():
    assert jwt.verify_token("") is None
    assert jwt.verify_token("not.a.jwt.extra") is None
    assert jwt.verify_token("only.two") is None
    assert jwt.verify_token("invalid_base64_!!!.invalid_base64_!!!.invalid_base64_!!!") is None


def test_parse_bearer_header():
    assert jwt.parse_bearer_header("Bearer abc123") == "abc123"
    assert jwt.parse_bearer_header("bearer xyz") == "xyz"  # case insensitive
    assert jwt.parse_bearer_header("  Bearer   tok  ") == "tok"
    assert jwt.parse_bearer_header("raw_tok") == "raw_tok"  # no prefix = raw
    assert jwt.parse_bearer_header("") == ""
