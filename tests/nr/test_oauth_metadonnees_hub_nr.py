"""NR 2/11 — E2 du plan OAuth MCP (docs/PLAN_OAUTH_MCP_HUB_20261102.md) : metadonnees publiees par le HUB.

Exigences NORMATIVES verifiees (pas seulement le chemin heureux) :
  RFC 9728 §2-3 : `resource` = URI du point MCP ; `authorization_servers` contient l'emetteur ; Bearer en EN-TETE seul.
  RFC 9728 §5.1 : defi `WWW-Authenticate: Bearer ... resource_metadata="<url>"`.
  RFC 8414 §2-3 : `issuer` = la base EXACTE (https/http sans barre finale) ; on n'ANNONCE que les points SERVIS.
  OAuth 2.1 / RFC 7636 : `response_types_supported` = ["code"] seul (pas d'implicite) ; PKCE `S256` SEUL (jamais plain).
  Clients publics : `token_endpoint_auth_methods_supported` = ["none"].
  Interrupteur : eteint par defaut (le hub reste « Bearer only » tant que E3 n'est pas servi et que l'owner n'a pas arme).
"""
import pytest

from app import forge_oauth_route as O

BASE = "http://127.0.0.1:8766"
TOUS = {"authorization_endpoint": "/oauth/authorize", "token_endpoint": "/oauth/token",
        "registration_endpoint": "/oauth/register", "revocation_endpoint": "/oauth/revoke",
        "jwks_uri": "/.well-known/jwks.json"}


def test_interrupteur_eteint_par_defaut(monkeypatch):
    monkeypatch.delenv("NOKIDO_OAUTH_CLIENTS", raising=False)
    assert O.clients_oauth_armes() is False
    monkeypatch.setenv("NOKIDO_OAUTH_CLIENTS", "1")
    assert O.clients_oauth_armes() is True


def test_ressource_protegee_rfc9728():
    m = O.metadonnees_ressource(BASE + "/", "/mcp")
    assert m["resource"] == BASE + "/mcp"
    assert m["authorization_servers"] == [BASE]
    assert m["bearer_methods_supported"] == ["header"]
    assert "mcp:hub" in m["scopes_supported"]


def test_autorite_rfc8414_valeurs_normatives():
    m = O.metadonnees_autorite(BASE + "/", TOUS)
    assert m["issuer"] == BASE
    assert m["response_types_supported"] == ["code"]
    assert m["code_challenge_methods_supported"] == ["S256"]
    assert "plain" not in m["code_challenge_methods_supported"]
    assert m["token_endpoint_auth_methods_supported"] == ["none"]
    assert set(m["grant_types_supported"]) == {"authorization_code", "refresh_token",
                                               "urn:ietf:params:oauth:grant-type:token-exchange"}
    assert m["token_endpoint"] == BASE + "/oauth/token"
    assert m["dpop_signing_alg_values_supported"] == ["ES256"]


def test_on_n_annonce_que_les_points_servis():
    m = O.metadonnees_autorite(BASE, {"token_endpoint": "/oauth/token"})
    assert m["token_endpoint"] == BASE + "/oauth/token"
    for absent in ("authorization_endpoint", "registration_endpoint", "revocation_endpoint", "jwks_uri"):
        assert absent not in m, absent
    # sans point d'autorisation, le flot code n'est PAS annonce
    assert "authorization_code" not in m["grant_types_supported"]


def test_point_inconnu_refuse():
    with pytest.raises(ValueError):
        O.metadonnees_autorite(BASE, {"implicit_endpoint": "/x"})


def test_defi_www_authenticate_rfc9728_et_6750():
    d = O.defi_www_authenticate(BASE, "/mcp")
    assert d.startswith("Bearer ")
    assert 'resource_metadata="%s/.well-known/oauth-protected-resource/mcp"' % BASE in d
    d2 = O.defi_www_authenticate(BASE, "/mcp", erreur="invalid_token")
    assert 'error="invalid_token"' in d2
    with pytest.raises(ValueError):
        O.defi_www_authenticate(BASE, "/mcp", erreur="nimporte")
