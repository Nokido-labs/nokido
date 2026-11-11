"""NR 3/11 — E3 du plan OAuth MCP : couche HTTP (Starlette) de l'autorite des clients du hub.

Exigences : interrupteur eteint = comportement inchange (404 « Bearer only », jeton RFC 8693 delegue) ;
RFC 9728/8414 publies quand arme ; RFC 7591 §3.2.1 inscription 201 ; RFC 6749 §4.1.2.1 pas de redirection vers une
URI non verifiee ; §5.1 `Cache-Control: no-store` sur le point de jeton ; RFC 7009 revocation 200 ; consentement
OBLIGATOIRE avant tout code (page d'attente, decision par `decider`, branchee au tray en E4).
"""
import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app import forge_oauth_clients as C
from app import forge_oauth_http as H
from app import forge_signature_hub as S

RES = "http://127.0.0.1:8766/mcp"
ISS = "http://127.0.0.1:8766"
VERIF = "z" * 60
DEFI = base64.urlsafe_b64encode(hashlib.sha256(VERIF.encode()).digest()).rstrip(b"=").decode()
REDIR = "http://127.0.0.1:41111/cb"


async def _delegue(request):
    return JSONResponse({"delegue": "rfc8693"})


@pytest.fixture
def client(tmp_path, monkeypatch):
    coffre = {}
    sig = S.obtenir_signataire(nom_cle="t-http", tpm=False, lire=coffre.get, ecrire=coffre.__setitem__)
    autorite = C.AutoriteClientsHub(tmp_path, sig, RES, ISS)
    monkeypatch.setenv("NOKIDO_OAUTH_CLIENTS", "1")
    app = Starlette(routes=H.routes(lambda: autorite, ISS, delegue_jeton=_delegue))
    return TestClient(app, follow_redirects=False), autorite, monkeypatch


def test_eteint_comportement_inchange(client):
    tc, _, mp = client
    mp.delenv("NOKIDO_OAUTH_CLIENTS")
    r = tc.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 404 and "Bearer token auth only" in r.text
    assert tc.post("/oauth/register", json={"redirect_uris": [REDIR]}).status_code == 404
    assert tc.post("/oauth/token", data={"grant_type": "authorization_code"}).json() == {"delegue": "rfc8693"}


def test_metadonnees_publiees(client):
    tc, _, _ = client
    m = tc.get("/.well-known/oauth-authorization-server").json()
    assert m["issuer"] == ISS and m["authorization_endpoint"] == ISS + "/oauth/authorize"
    assert m["registration_endpoint"] == ISS + "/oauth/register" and m["jwks_uri"] == ISS + "/.well-known/jwks.json"
    assert m["authorization_response_iss_parameter_supported"] is True        # RFC 9207 §3
    r = tc.get("/.well-known/oauth-protected-resource/mcp").json()
    assert r["resource"] == RES and r["authorization_servers"] == [ISS]
    assert tc.get("/.well-known/jwks.json").json()["keys"][0]["alg"] == "ES256"


def _inscrire(tc):
    r = tc.post("/oauth/register", json={"redirect_uris": ["http://127.0.0.1:1/cb"], "client_name": "VS Code"})
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store"
    return r.json()["client_id"]


def _autoriser(tc, cid, **sur):
    p = {"response_type": "code", "client_id": cid, "redirect_uri": REDIR, "code_challenge": DEFI,
         "code_challenge_method": "S256", "resource": RES, "state": "etat1"}
    p.update(sur)
    return tc.get("/oauth/authorize", params=p)


def test_inscription_refusee_400(client):
    tc, _, _ = client
    r = tc.post("/oauth/register", json={"redirect_uris": ["https://evil.example/cb"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri"


def test_redirection_non_verifiee_jamais_suivie(client):
    tc, _, _ = client
    cid = _inscrire(tc)
    r = _autoriser(tc, cid, redirect_uri="https://evil.example/cb")
    assert r.status_code == 400 and "location" not in r.headers


def test_erreur_redirigee_si_uri_verifiee(client):
    tc, _, _ = client
    cid = _inscrire(tc)
    r = _autoriser(tc, cid, code_challenge_method="plain")
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert r.status_code == 302 and q["error"] == ["invalid_request"] and q["iss"] == [ISS]


def test_flot_complet_avec_consentement(client):
    tc, autorite, _ = client
    cid = _inscrire(tc)
    r = _autoriser(tc, cid)
    assert r.status_code == 200 and "consentement" in r.text.lower()
    ident = H.demandes_en_attente()[-1]
    # avant decision : pas de code
    assert tc.get("/oauth/authorize/etat", params={"demande": ident}).status_code == 202
    H.decider(ident, accord=True, identite="OAUTH_VSCODE", ring=3)
    r = tc.get("/oauth/authorize/etat", params={"demande": ident})
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert r.status_code == 302 and q["iss"] == [ISS] and q["state"] == ["etat1"]
    t = tc.post("/oauth/token", data={"grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": REDIR,
                                      "client_id": cid, "code_verifier": VERIF, "resource": RES})
    assert t.status_code == 200 and t.headers["cache-control"] == "no-store" and t.headers["pragma"] == "no-cache"
    corps = t.json()
    assert autorite.verifier_acces(corps["access_token"])[1] is None
    rv = tc.post("/oauth/revoke", data={"token": corps["access_token"], "client_id": cid})
    assert rv.status_code == 200 and autorite.verifier_acces(corps["access_token"])[0] is None


def test_refus_du_consentement(client):
    tc, _, _ = client
    cid = _inscrire(tc)
    _autoriser(tc, cid)
    ident = H.demandes_en_attente()[-1]
    H.decider(ident, accord=False)
    q = parse_qs(urlsplit(tc.get("/oauth/authorize/etat", params={"demande": ident}).headers["location"]).query)
    assert q["error"] == ["access_denied"]


def test_jeton_rfc8693_toujours_delegue(client):
    tc, _, _ = client
    r = tc.post("/oauth/token", data={"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange"})
    assert r.json() == {"delegue": "rfc8693"}
