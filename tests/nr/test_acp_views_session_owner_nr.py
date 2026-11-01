"""NR -- recette owner 28/10 : « 401 quand j'essaye d'autoriser » sur /acp.

_est_admin n'acceptait que le jeton admin BRUT ; le navigateur de l'owner presente une session JWT, delivree
seulement apres login au jeton admin (/auth/login) et verifiee par l'AuthMiddleware. La route doit accepter
cette session, la REVERIFIER elle-meme (jamais l'en-tete X-LaForge-User), et refuser si l'auth est desactivee.
Toujours aucune derogation loopback.
"""
from __future__ import annotations

import types

import app.web_hub as pkg
from app.web_hub import acp_views


class _Req:
    def __init__(self, cookie=None):
        self.headers = {}
        self.cookies = {"s": cookie} if cookie else {}


def _faux_hub(monkeypatch, enabled=True, jwt_valides=(), admin=()):
    fake = types.SimpleNamespace(
        AUTH_CFG=types.SimpleNamespace(enabled=enabled),
        extract_token=lambda headers, cookies: cookies.get("s"),
        admin_token_ok=lambda cfg, tok: tok in admin,
        verify_token=lambda cfg, tok: {"sub": "owner"} if tok in jwt_valides else None,
    )
    monkeypatch.setattr(pkg, "app", fake, raising=False)


def test_session_jwt_valide_de_l_owner_autorise(monkeypatch):
    _faux_hub(monkeypatch, jwt_valides=("jwt-ok",))
    assert acp_views._est_admin(_Req("jwt-ok")) is True


def test_jwt_invalide_refuse(monkeypatch):
    _faux_hub(monkeypatch, jwt_valides=("jwt-ok",))
    assert acp_views._est_admin(_Req("jwt-faux")) is False


def test_sans_jeton_refuse(monkeypatch):
    _faux_hub(monkeypatch, jwt_valides=("jwt-ok",))
    assert acp_views._est_admin(_Req()) is False


def test_auth_desactivee_un_jwt_ne_suffit_pas(monkeypatch):
    _faux_hub(monkeypatch, enabled=False, jwt_valides=("jwt-ok",))
    assert acp_views._est_admin(_Req("jwt-ok")) is False


def test_jeton_admin_brut_toujours_accepte(monkeypatch):
    _faux_hub(monkeypatch, admin=("brut",))
    assert acp_views._est_admin(_Req("brut")) is True
