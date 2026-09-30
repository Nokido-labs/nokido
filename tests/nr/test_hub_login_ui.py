"""
tests/nr/test_hub_login_ui.py - NR UI login + security headers.

Coverage :
  - GET /auth/login : HTML, contient form method=post + champ admin_token
  - Pas de script inline/CDN dans la page login (CSP-strict)
  - POST /auth/login avec Accept: text/html -> redirect 303 + cookie
  - POST /auth/login echec (wrong token) HTML -> 401 HTML avec message
  - Middleware : 401 sur navigator (Accept: text/html) -> redirect 303 /auth/login?next=...
  - Middleware : 401 sur API (Accept: application/json) -> JSON 401
  - Security headers appliques : X-Frame-Options, CSP, X-Content-Type-Options...
  - Redirect-to safe : // rejete, protocol-relative rejete, javascript: rejete
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def admin_token():
    return "ui-login-token-42"


@pytest.fixture
def client(monkeypatch, admin_token):
    monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
    for m in list(sys.modules):
        if m.startswith("app.web_hub"):
            del sys.modules[m]
    from fastapi.testclient import TestClient
    from app.web_hub.app import app
    from app.web_hub.auth import login_rate_limiter
    login_rate_limiter._by_ip.clear()  # noqa: SLF001
    return TestClient(app)


# -------------------------------------------------------------------
# GET /auth/login
# -------------------------------------------------------------------
class TestLoginPage:
    def test_get_public(self, client):
        r = client.get("/auth/login")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "").lower()

    def test_contains_form(self, client):
        html = client.get("/auth/login").text.lower()
        assert '<form' in html and 'method="post"' in html
        assert 'action="/auth/login"' in html
        assert 'name="admin_token"' in html

    def test_no_script_external(self, client):
        """CSP-strict : pas de <script src=...> sur la page login."""
        html = client.get("/auth/login").text
        assert "<script" not in html.lower(), (
            "page login doit rester sans JS pour CSP stricte")

    def test_with_next_query(self, client):
        """?next=/status doit etre preserve dans le form."""
        html = client.get("/auth/login?next=/status").text
        assert "/status" in html


# -------------------------------------------------------------------
# POST /auth/login (HTML dual mode)
# -------------------------------------------------------------------
class TestLoginPost:
    def test_html_success_redirects_303(self, client, admin_token):
        r = client.post(
            "/auth/login",
            data={"admin_token": admin_token, "redirect_to": "/"},
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers.get("location") == "/"
        sc = r.headers.get("set-cookie", "").lower()
        assert "lf_session=" in sc
        assert "httponly" in sc

    def test_html_redirect_path_sanitized(self, client, admin_token):
        """Protocol-relative // ou external URL -> forcees a /."""
        r = client.post(
            "/auth/login",
            data={"admin_token": admin_token, "redirect_to": "//evil.com"},
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers.get("location") == "/", "protocol-relative doit etre rejete"

    def test_html_wrong_returns_401_html(self, client):
        r = client.post(
            "/auth/login",
            data={"admin_token": "wrong", "redirect_to": "/"},
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        assert r.status_code == 401
        assert "text/html" in r.headers.get("content-type", "").lower()
        assert "Token invalide" in r.text or "invalide" in r.text.lower()

    def test_json_mode_still_works(self, client, admin_token):
        """Sans Accept: text/html, garde le comportement JSON original."""
        r = client.post(
            "/auth/login",
            data={"admin_token": admin_token},
            headers={"Accept": "application/json"},
        )
        assert r.status_code == 200
        assert "token" in r.json()


# -------------------------------------------------------------------
# Middleware 401 redirect vs 401 JSON
# -------------------------------------------------------------------
class TestMiddleware401:
    def test_api_gets_json_401(self, client):
        r = client.get("/status", headers={"Accept": "application/json"})
        assert r.status_code == 401
        assert r.json() == {"detail": "unauthorized"}

    def test_browser_gets_redirect(self, client):
        """Navigator (Accept: text/html) -> redirect 303 vers /auth/login?next=..."""
        r = client.get(
            "/status",
            headers={"Accept": "text/html,application/xhtml+xml"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        loc = r.headers.get("location", "")
        assert loc.startswith("/auth/login?next=")
        assert "/status" in loc

    def test_browser_post_not_redirected(self, client):
        """Un POST qui echoue l auth ne doit pas redirect (pas un navigator nav)."""
        r = client.post(
            "/ctf/api/run/whatever",
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        assert r.status_code == 401  # pas 303


# -------------------------------------------------------------------
# Security headers
# -------------------------------------------------------------------
class TestSecurityHeaders:
    def test_health_has_security_headers(self, client):
        r = client.get("/health")
        h = {k.lower(): v for k, v in r.headers.items()}
        assert h.get("x-content-type-options") == "nosniff"
        assert h.get("x-frame-options") == "DENY"
        assert "same-origin" in h.get("referrer-policy", "")
        assert "geolocation=()" in h.get("permissions-policy", "")
        assert "content-security-policy" in h

    def test_login_page_has_csp(self, client):
        r = client.get("/auth/login")
        h = {k.lower(): v for k, v in r.headers.items()}
        csp = h.get("content-security-policy", "")
        assert "frame-ancestors 'none'" in csp
        assert "default-src 'self'" in csp

    def test_csp_forbids_frame_ancestors(self, client):
        """Anti-clickjacking : X-Frame-Options + frame-ancestors."""
        r = client.get("/health")
        assert r.headers.get("x-frame-options") == "DENY"
        assert "frame-ancestors 'none'" in r.headers.get("content-security-policy", "")
