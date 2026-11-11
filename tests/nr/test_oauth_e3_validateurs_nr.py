"""NR 3/11 — E3 du plan OAuth MCP : validateurs PURS de l'inscription et de l'autorisation (hub = autorite unique).

Exigences normatives :
  RFC 7591 §2 : `redirect_uris` obligatoires ; client public `token_endpoint_auth_method=none` ; grant_types limites.
  RFC 8252 §7.3/§8.3 : redirection de bouclage local (127.0.0.1 / [::1]) en http ; le PORT est libre a la demande,
    le chemin doit etre identique ; schemas arbitraires et hotes distants refuses.
  RFC 6749 §4.1.1 / §4.1.2.1 : response_type=code seul ; erreurs normatives (invalid_request, unauthorized_client,
    unsupported_response_type, invalid_scope) ; redirect_uri invalide = JAMAIS de redirection (erreur affichee).
  RFC 7636 §4 : code_challenge obligatoire, methode S256 seule ; verifier 43-128 car. [A-Za-z0-9-._~].
  RFC 8707 §2 : `resource` doit designer la ressource du hub, sinon invalid_target.
"""
import base64
import hashlib

import pytest

from app import forge_oauth_route as O

RES = "http://127.0.0.1:8766/mcp"


def _client():
    c, err = O.valider_inscription({"redirect_uris": ["http://127.0.0.1:33418/callback"], "client_name": "VS Code"})
    assert err is None
    return c


@pytest.mark.parametrize("uri", ["http://127.0.0.1:33418/callback", "http://[::1]:5000/cb", "http://127.0.0.1/cb",
                                 # 3/11, premier VRAI client (Claude Code) : DCR refusee en invalid_redirect_uri --
                                 # il utilise http://localhost:<port>/callback. RFC 8252 §8.3 le DECONSEILLE aux
                                 # clients sans l'interdire ; la spec MCP l'admet. Nom EXACT seulement.
                                 "http://localhost:54321/callback", "http://LOCALHOST:1/cb"])
def test_inscription_bouclage_acceptee(uri):
    c, err = O.valider_inscription({"redirect_uris": [uri]})
    assert err is None and c["token_endpoint_auth_method"] == "none"
    assert set(c["grant_types"]) <= {"authorization_code", "refresh_token"} and c["response_types"] == ["code"]


@pytest.mark.parametrize("meta,code", [
    ({}, "invalid_redirect_uri"),
    ({"redirect_uris": []}, "invalid_redirect_uri"),
    ({"redirect_uris": ["https://evil.example/cb"]}, "invalid_redirect_uri"),
    ({"redirect_uris": ["http://localhost.evil.example:80/cb"]}, "invalid_redirect_uri"),
    ({"redirect_uris": ["http://evil-localhost:80/cb"]}, "invalid_redirect_uri"),
    ({"redirect_uris": ["https://localhost:1/cb"]}, "invalid_redirect_uri"),
    ({"redirect_uris": ["myapp://cb"]}, "invalid_redirect_uri"),
    ({"redirect_uris": ["http://127.0.0.1:1/cb#frag"]}, "invalid_redirect_uri"),
    ({"redirect_uris": ["http://127.0.0.1:1/cb"], "token_endpoint_auth_method": "client_secret_basic"},
     "invalid_client_metadata"),
    ({"redirect_uris": ["http://127.0.0.1:1/cb"], "grant_types": ["implicit"]}, "invalid_client_metadata"),
    ({"redirect_uris": ["http://127.0.0.1:1/cb"], "response_types": ["token"]}, "invalid_client_metadata"),
])
def test_inscription_refusee_codes_rfc7591(meta, code):
    c, err = O.valider_inscription(meta)
    assert c is None and err == code


def _verifier_et_defi():
    v = "a" * 43
    return v, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def _params(**sur):
    v, defi = _verifier_et_defi()
    c = _client()
    p = {"response_type": "code", "client_id": c["client_id"], "redirect_uri": "http://127.0.0.1:51000/callback",
         "code_challenge": defi, "code_challenge_method": "S256", "resource": RES, "scope": "mcp:hub",
         "state": "s1"}
    p.update(sur)
    return p, {c["client_id"]: c}


def test_autorisation_localhost_port_libre():
    c, err = O.valider_inscription({"redirect_uris": ["http://localhost:1/callback"]})
    v, defi = _verifier_et_defi()
    p = {"response_type": "code", "client_id": c["client_id"], "redirect_uri": "http://localhost:60123/callback",
         "code_challenge": defi, "code_challenge_method": "S256", "resource": RES}
    d, err, _ = O.valider_autorisation(p, {c["client_id"]: c}, RES)
    assert err is None and d["redirect_uri"] == "http://localhost:60123/callback"
    # localhost inscrit ne vaut PAS 127.0.0.1 (hote different = redirection differente)
    p["redirect_uri"] = "http://127.0.0.1:60123/callback"
    assert O.valider_autorisation(p, {c["client_id"]: c}, RES)[1] == "invalid_request"


def test_autorisation_valide_port_libre_en_bouclage():
    p, clients = _params()
    d, err, redirige = O.valider_autorisation(p, clients, RES)
    assert err is None and d["redirect_uri"] == "http://127.0.0.1:51000/callback" and d["resource"] == RES


@pytest.mark.parametrize("sur,code,redirige", [
    ({"response_type": "token"}, "unsupported_response_type", True),
    ({"code_challenge": None}, "invalid_request", True),
    ({"code_challenge_method": "plain"}, "invalid_request", True),
    ({"resource": "http://127.0.0.1:9200/mcp"}, "invalid_target", True),
    ({"resource": None}, "invalid_target", True),
    ({"scope": "mcp:hub admin"}, "invalid_scope", True),
    ({"client_id": "inconnu"}, "invalid_request", False),
    ({"redirect_uri": "http://127.0.0.1:51000/autre"}, "invalid_request", False),
    ({"redirect_uri": "https://evil.example/callback"}, "invalid_request", False),
])
def test_autorisation_refusee_codes_rfc6749(sur, code, redirige):
    p, clients = _params()
    p.update({k: v for k, v in sur.items()})
    p = {k: v for k, v in p.items() if v is not None}
    d, err, peut_rediriger = O.valider_autorisation(p, clients, RES)
    assert d is None and err == code and peut_rediriger is redirige


def test_pkce_s256():
    v, defi = _verifier_et_defi()
    assert O.verifier_pkce(v, defi) is True
    assert O.verifier_pkce("b" * 43, defi) is False
    assert O.verifier_pkce("a" * 42, defi) is False          # trop court (RFC 7636 §4.1)
    assert O.verifier_pkce("a" * 43 + "+", defi) is False    # caractere hors alphabet
