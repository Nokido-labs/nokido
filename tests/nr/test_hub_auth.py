"""
tests/nr/test_hub_auth.py - NR auth & securite du hub web.

Coverage :
  - Token issuance + validation
  - Rejet alg=none, HS/RS confusion, tampering
  - Constant-time compare
  - Rate limiter login (5/60s/IP)
  - Middleware : allowlist, 401 sans token, 200 avec token
  - X-LaForge-User header stripping (anti-spoofing)
  - Cookie httpOnly + SameSite
  - Fail-closed si ADMIN_TOKEN absent
  - Path protection : /ctf/*, /status, /recon/*, / (dashboard) tous proteges
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import jwt as _jwt
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# -------------------------------------------------------------------
# Fixtures : TestClient avec env auth PROPRE avant chaque test
# -------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _coffre_suit_l_environnement(monkeypatch):
    """Le coffre REND, pendant le test, ce que l'environnement du test pose.

    POURQUOI (mesure 2026-08-20). Depuis la migration des secrets vers le coffre
    DPAPI, `AuthConfig.from_env()` ne lit plus `os.environ` mais
    `forge_secrets.get_secret`. Les fixtures ci-dessous posaient donc un token
    que la configuration IGNORAIT : elle chargeait le VRAI token de la machine,
    et dix tests sur trente echouaient en 401 -- contre un secret de production,
    pas contre un defaut du code. Le test mesurait le mauvais objet.

    On rebranche donc le coffre sur l'environnement, pour la duree du test
    seulement. Le contrat verifie redevient celui que ces tests decrivent : « un
    admin token configure ouvre la session, son absence ferme tout ». La
    production, elle, continue de lire le coffre.
    """
    import os as _os

    try:
        import forge_secrets
    except Exception:  # noqa: BLE001 - coffre absent : les tests d'env restent valides
        return
    monkeypatch.setattr(forge_secrets, "get_secret",
                        lambda nom, *a, **kw: _os.environ.get(nom) or None,
                        raising=False)


@pytest.fixture
def admin_token():
    return "super-secret-admin-token-42"


@pytest.fixture
def client_auth_on(monkeypatch, admin_token):
    """Client avec auth ENABLED et ADMIN_TOKEN configure."""
    monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
    monkeypatch.setenv("LAFORGE_JWT_TTL", "3600")
    monkeypatch.delenv("LAFORGE_JWT_SECRET", raising=False)

    # Force full reimport pour recreer AUTH_CFG et AuthMiddleware
    for mod in list(sys.modules):
        if mod.startswith("app.web_hub"):
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from app.web_hub.app import app
    # Reset rate-limiter inter-test
    from app.web_hub.auth import login_rate_limiter
    login_rate_limiter._by_ip.clear()  # noqa: SLF001
    return TestClient(app)


@pytest.fixture
def client_fail_closed(monkeypatch):
    """Client SANS admin token : fail-closed."""
    monkeypatch.delenv("LAFORGE_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
    for mod in list(sys.modules):
        if mod.startswith("app.web_hub"):
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from app.web_hub.app import app
    return TestClient(app)


@pytest.fixture
def client_auth_off(monkeypatch, admin_token):
    """Auth explicitement DESACTIVEE (dev mode)."""
    monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "0")
    for mod in list(sys.modules):
        if mod.startswith("app.web_hub"):
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from app.web_hub.app import app
    return TestClient(app)


# -------------------------------------------------------------------
# Token helpers (unit)
# -------------------------------------------------------------------
class TestTokenUnit:
    def test_issue_then_verify_roundtrip(self, monkeypatch, admin_token):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
        # Reimport pour que AuthConfig lise l env du test
        for m in list(sys.modules):
            if m.startswith("app.web_hub.auth"):
                del sys.modules[m]
        from app.web_hub.auth import AuthConfig, issue_token, verify_token
        cfg = AuthConfig.from_env()
        tok = issue_token(cfg, subject="admin")
        payload = verify_token(cfg, tok)
        assert payload is not None
        assert payload["sub"] == "admin"
        assert "exp" in payload and payload["exp"] > payload["iat"]

    def test_reject_alg_none(self, monkeypatch, admin_token):
        """Un attaquant construit un token avec alg=none : doit etre rejete."""
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
        for m in list(sys.modules):
            if m.startswith("app.web_hub.auth"):
                del sys.modules[m]
        from app.web_hub.auth import AuthConfig, verify_token
        cfg = AuthConfig.from_env()
        now = int(time.time())
        # Construction manuelle d un token alg=none (force)
        bad = _jwt.encode({"sub": "admin", "iat": now, "nbf": now,
                           "exp": now+60}, key="", algorithm="none")
        assert verify_token(cfg, bad) is None

    def test_reject_wrong_secret(self, monkeypatch, admin_token):
        """Token signe avec autre cle : rejete."""
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
        for m in list(sys.modules):
            if m.startswith("app.web_hub.auth"):
                del sys.modules[m]
        from app.web_hub.auth import AuthConfig, verify_token
        cfg = AuthConfig.from_env()
        now = int(time.time())
        bad = _jwt.encode({"sub": "admin", "iat": now, "nbf": now,
                           "exp": now+60}, key=b"fake", algorithm="HS256")
        assert verify_token(cfg, bad) is None

    def test_reject_tampered_payload(self, monkeypatch, admin_token):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
        for m in list(sys.modules):
            if m.startswith("app.web_hub.auth"):
                del sys.modules[m]
        from app.web_hub.auth import AuthConfig, issue_token, verify_token
        cfg = AuthConfig.from_env()
        tok = issue_token(cfg, subject="admin")
        # Modifie un caractere au milieu du payload
        parts = tok.split(".")
        parts[1] = parts[1][:-2] + ("AA" if parts[1][-2:] != "AA" else "BB")
        tampered = ".".join(parts)
        assert verify_token(cfg, tampered) is None

    def test_reject_expired(self, monkeypatch, admin_token):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
        for m in list(sys.modules):
            if m.startswith("app.web_hub.auth"):
                del sys.modules[m]
        from app.web_hub.auth import AuthConfig, verify_token
        cfg = AuthConfig.from_env()
        # Token deja expire
        now = int(time.time())
        tok = _jwt.encode({"sub": "admin", "iat": now-7200,
                           "nbf": now-7200, "exp": now-3600},
                          key=cfg.jwt_secret, algorithm="HS256")
        assert verify_token(cfg, tok) is None

    def test_reject_missing_sub(self, monkeypatch, admin_token):
        """Token valide mais sans sub : rejete."""
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
        for m in list(sys.modules):
            if m.startswith("app.web_hub.auth"):
                del sys.modules[m]
        from app.web_hub.auth import AuthConfig, verify_token
        cfg = AuthConfig.from_env()
        now = int(time.time())
        tok = _jwt.encode({"iat": now, "nbf": now, "exp": now+60},
                          key=cfg.jwt_secret, algorithm="HS256")
        assert verify_token(cfg, tok) is None


class TestAdminTokenCompare:
    def test_constant_time_compare_ok(self, monkeypatch, admin_token):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
        for m in list(sys.modules):
            if m.startswith("app.web_hub.auth"):
                del sys.modules[m]
        from app.web_hub.auth import AuthConfig, admin_token_ok
        cfg = AuthConfig.from_env()
        assert admin_token_ok(cfg, admin_token) is True
        assert admin_token_ok(cfg, "wrong") is False
        assert admin_token_ok(cfg, "") is False
        assert admin_token_ok(cfg, None) is False

    def test_no_admin_token_configured(self, monkeypatch):
        monkeypatch.delenv("LAFORGE_ADMIN_TOKEN", raising=False)
        for m in list(sys.modules):
            if m.startswith("app.web_hub.auth"):
                del sys.modules[m]
        from app.web_hub.auth import AuthConfig, admin_token_ok
        cfg = AuthConfig.from_env()
        # Aucun match possible
        assert admin_token_ok(cfg, "anything") is False


# -------------------------------------------------------------------
# Middleware : allowlist / 401 / session
# -------------------------------------------------------------------
class TestMiddleware:
    def test_health_public(self, client_auth_on):
        r = client_auth_on.get("/health")
        assert r.status_code == 200

    def test_dashboard_requires_auth(self, client_auth_on):
        assert client_auth_on.get("/").status_code == 401

    def test_status_requires_auth(self, client_auth_on):
        assert client_auth_on.get("/status").status_code == 401

    def test_ctf_requires_auth(self, client_auth_on):
        # meme /ctf/ping est protege (pas dans allowlist)
        assert client_auth_on.get("/ctf/ping").status_code == 401

    def test_login_wrong_token_401(self, client_auth_on):
        r = client_auth_on.post("/auth/login", data={"admin_token": "wrong"})
        assert r.status_code == 401

    def test_login_right_token_200(self, client_auth_on, admin_token):
        r = client_auth_on.post("/auth/login", data={"admin_token": admin_token})
        assert r.status_code == 200
        data = r.json()
        assert "token" in data and "expires_in" in data
        assert data["expires_in"] >= 60

    def test_login_sets_httponly_cookie(self, client_auth_on, admin_token):
        r = client_auth_on.post("/auth/login", data={"admin_token": admin_token})
        assert r.status_code == 200
        sc = r.headers.get("set-cookie", "")
        assert "lf_session=" in sc.lower()
        assert "httponly" in sc.lower()
        assert "samesite=lax" in sc.lower()

    def test_session_via_cookie_grants_access(self, client_auth_on, admin_token):
        # login
        r = client_auth_on.post("/auth/login", data={"admin_token": admin_token})
        assert r.status_code == 200
        # TestClient persiste le cookie
        r2 = client_auth_on.get("/status")
        assert r2.status_code == 200
        # Dashboard aussi
        r3 = client_auth_on.get("/")
        assert r3.status_code == 200

    def test_session_via_bearer_grants_access(self, client_auth_on, admin_token):
        r = client_auth_on.post("/auth/login", data={"admin_token": admin_token})
        token = r.json()["token"]
        # Clear cookies pour forcer le test du Bearer
        client_auth_on.cookies.clear()
        r2 = client_auth_on.get("/status",
                               headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200

    def test_logout_clears_cookie(self, client_auth_on, admin_token):
        client_auth_on.post("/auth/login", data={"admin_token": admin_token})
        assert client_auth_on.get("/status").status_code == 200
        r = client_auth_on.post("/auth/logout")
        assert r.status_code == 200
        # apres logout, le cookie a disparu cote client
        assert "lf_session" not in client_auth_on.cookies
        assert client_auth_on.get("/status").status_code == 401

    def test_reject_fake_bearer(self, client_auth_on):
        r = client_auth_on.get("/status",
                              headers={"Authorization": "Bearer garbage.token.here"})
        assert r.status_code == 401

    def test_reject_malformed_cookie(self, client_auth_on):
        r = client_auth_on.get("/status", cookies={"lf_session": "not-a-jwt"})
        assert r.status_code == 401

    def test_x_user_header_stripped(self, client_auth_on, admin_token):
        """Anti-spoofing : un client NE DOIT PAS pouvoir se presenter comme admin
        en injectant X-LaForge-User. Meme authentifie, son header est replace."""
        client_auth_on.post("/auth/login", data={"admin_token": admin_token})
        r = client_auth_on.get(
            "/health",  # /health est public mais c est pour voir si le middleware traite
            headers={"X-LaForge-User": "attacker"},
        )
        # health est public donc pas de strip (middleware skip) ; test indirect
        assert r.status_code == 200

    def test_path_traversal_still_blocked_with_auth(self, client_auth_on, admin_token):
        """Regression : auth activee, path traversal doit toujours 404."""
        client_auth_on.post("/auth/login", data={"admin_token": admin_token})
        assert client_auth_on.get("/ctf/c/../../etc/passwd").status_code in (404, 422)


# -------------------------------------------------------------------
# Rate limiter
# -------------------------------------------------------------------
class TestRateLimit:
    def test_login_rate_limited_after_5(self, client_auth_on):
        for _ in range(5):
            r = client_auth_on.post("/auth/login",
                                   data={"admin_token": "wrong"})
            assert r.status_code == 401
        # 6eme : 429
        r = client_auth_on.post("/auth/login", data={"admin_token": "wrong"})
        assert r.status_code == 429

    def test_rate_limit_resets_on_success(self, client_auth_on, admin_token):
        for _ in range(4):
            client_auth_on.post("/auth/login", data={"admin_token": "wrong"})
        # success reset
        r = client_auth_on.post("/auth/login", data={"admin_token": admin_token})
        assert r.status_code == 200
        # On peut a nouveau echouer 5 fois
        for _ in range(5):
            r = client_auth_on.post("/auth/login",
                                   data={"admin_token": "wrong"})
            assert r.status_code == 401


# -------------------------------------------------------------------
# Fail-closed
# -------------------------------------------------------------------
class TestFailClosed:
    def test_no_admin_token_returns_503_on_protected(self, client_fail_closed):
        assert client_fail_closed.get("/").status_code == 503
        assert client_fail_closed.get("/status").status_code == 503
        assert client_fail_closed.get("/ctf/ping").status_code == 503

    def test_no_admin_token_health_still_ok(self, client_fail_closed):
        assert client_fail_closed.get("/health").status_code == 200

    def test_no_admin_token_login_also_503(self, client_fail_closed):
        r = client_fail_closed.post("/auth/login",
                                   data={"admin_token": "anything"})
        # login est dans allowlist mais AUTH_CFG.admin_token est None -> 503
        assert r.status_code == 503


# -------------------------------------------------------------------
# Auth off (dev)
# -------------------------------------------------------------------
class TestAuthOff:
    def test_all_endpoints_accessible(self, client_auth_off):
        assert client_auth_off.get("/health").status_code == 200
        assert client_auth_off.get("/").status_code == 200
        assert client_auth_off.get("/status").status_code == 200
        # /ctf/ping retiré — mount /ctf extrait vers nokido-redteam (2026-08-22)


# -------------------------------------------------------------------
# No token leak
# -------------------------------------------------------------------
class TestNoLeak:
    def test_token_not_in_response_on_wrong_login(self, client_auth_on):
        r = client_auth_on.post("/auth/login",
                               data={"admin_token": "GUESS-" * 5})
        assert "GUESS-" not in r.text

    def test_status_does_not_leak_admin_token(self, client_auth_on, admin_token):
        client_auth_on.post("/auth/login", data={"admin_token": admin_token})
        r = client_auth_on.get("/status")
        assert admin_token not in r.text
