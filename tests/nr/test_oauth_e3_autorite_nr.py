"""NR 3/11 — E3 du plan OAuth MCP : autorite des clients du hub, flot COMPLET (etat persiste, horloge injectee).

Exigences normatives :
  RFC 6749 §4.1.2 : code a usage UNIQUE, duree courte (300 s) ; un code REJOUE est refuse ET revoque les jetons
    qu'il a emis. §4.1.3 : redirect_uri identique a la demande, client_id identique. §5.2 : codes d'erreur.
  RFC 7636 §4.6 : verifier PKCE. RFC 8707 : resource identique, sinon invalid_target.
  RFC 9207 : `iss` dans la reponse d'autorisation (succes ET erreur).
  OAuth 2.1 §4.3.1 : renouvellement TOURNANT ; un ancien renouvellement qui resurgit revoque toute la famille.
  RFC 7009 §2.2 : revocation -> 200 meme pour un jeton inconnu ; effet a l'appel suivant.
  RFC 9068 : jeton d'acces JWS ES256 (aud = ressource, client_id, sub = identite Nokido, scope, exp, jti).
"""
import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from app import forge_oauth_clients as C
from app import forge_signature_hub as S

RES = "http://127.0.0.1:8766/mcp"
ISS = "http://127.0.0.1:8766"
VERIF = "v" * 50
DEFI = base64.urlsafe_b64encode(hashlib.sha256(VERIF.encode()).digest()).rstrip(b"=").decode()
REDIR = "http://127.0.0.1:40123/callback"


class Horloge:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path):
    coffre = {}
    sig = S.obtenir_signataire(nom_cle="test-autorite", tpm=False, lire=coffre.get, ecrire=coffre.__setitem__)
    h = Horloge()
    a = C.AutoriteClientsHub(tmp_path, sig, RES, ISS, horloge=h)
    return a, h, tmp_path, sig


def _client(a):
    c, err = a.inscrire({"redirect_uris": ["http://127.0.0.1:1/callback"], "client_name": "VS Code"})
    assert err is None
    return c


def _accorde(a, c, state="st"):
    did, err, _, _ = a.demander_autorisation({
        "response_type": "code", "client_id": c["client_id"], "redirect_uri": REDIR, "code_challenge": DEFI,
        "code_challenge_method": "S256", "resource": RES, "scope": "mcp:hub", "state": state})
    assert err is None and a.demande(did)["etat"] == "en_attente_consentement"
    url = a.accorder(did, identite="OAUTH_VSCODE", ring=3)
    q = parse_qs(urlsplit(url).query)
    return q


def _form(c, code_recu, **sur):
    # `code_recu` et non `code` : un cas surcharge `code` (absent) -- deux valeurs pour un meme parametre leveraient
    f = {"grant_type": "authorization_code", "code": code_recu, "redirect_uri": REDIR, "client_id": c["client_id"],
         "code_verifier": VERIF, "resource": RES}
    f.update(sur)
    return {k: v for k, v in f.items() if v is not None}


def test_inscription_persistee(env):
    a, h, d, sig = env
    c = _client(a)
    b = C.AutoriteClientsHub(d, sig, RES, ISS, horloge=h)
    assert b.client(c["client_id"])["client_name"] == "VS Code"


def test_flot_complet_et_iss_rfc9207(env):
    a, h, d, sig = env
    c = _client(a)
    q = _accorde(a, c)
    assert q["state"] == ["st"] and q["iss"] == [ISS] and len(q["code"][0]) >= 32
    st, corps = a.jeton(_form(c, q["code"][0]))
    assert st == 200 and corps["token_type"] == "Bearer" and corps["expires_in"] == 3600 and corps["refresh_token"]
    charge, motif = a.verifier_acces(corps["access_token"])
    assert motif is None
    assert charge["aud"] == RES and charge["client_id"] == c["client_id"] and charge["sub"] == "OAUTH_VSCODE"
    assert charge["scope"] == "mcp:hub" and charge["iss"] == ISS and charge["ring"] == 3


def test_refus_du_consentement(env):
    a, h, d, sig = env
    c = _client(a)
    did, _, _, _ = a.demander_autorisation({
        "response_type": "code", "client_id": c["client_id"], "redirect_uri": REDIR, "code_challenge": DEFI,
        "code_challenge_method": "S256", "resource": RES, "state": "x"})
    q = parse_qs(urlsplit(a.refuser(did)).query)
    assert q["error"] == ["access_denied"] and q["state"] == ["x"] and q["iss"] == [ISS]


def test_code_rejoue_refuse_et_revoque(env):
    a, h, d, sig = env
    c = _client(a)
    code = _accorde(a, c)["code"][0]
    st, corps = a.jeton(_form(c, code))
    assert st == 200
    st2, err = a.jeton(_form(c, code))
    assert st2 == 400 and err["error"] == "invalid_grant"
    assert a.verifier_acces(corps["access_token"])[0] is None


@pytest.mark.parametrize("sur,code_err", [
    ({"code_verifier": "w" * 50}, "invalid_grant"),
    ({"redirect_uri": "http://127.0.0.1:40123/autre"}, "invalid_grant"),
    ({"client_id": "nkc_autre"}, "invalid_grant"),
    ({"resource": "http://127.0.0.1:9200/mcp"}, "invalid_target"),
    ({"grant_type": "password"}, "unsupported_grant_type"),
    ({"code": None}, "invalid_request"),
])
def test_echange_refuse(env, sur, code_err):
    a, h, d, sig = env
    c = _client(a)
    code = _accorde(a, c)["code"][0]
    st, err = a.jeton(_form(c, code, **sur))
    assert st == 400 and err["error"] == code_err


def test_code_expire(env):
    a, h, d, sig = env
    c = _client(a)
    code = _accorde(a, c)["code"][0]
    h.t += 301
    assert a.jeton(_form(c, code))[1]["error"] == "invalid_grant"


def test_renouvellement_tournant_et_famille_revoquee(env):
    a, h, d, sig = env
    c = _client(a)
    _, c1 = a.jeton(_form(c, _accorde(a, c)["code"][0]))
    st, c2 = a.jeton({"grant_type": "refresh_token", "refresh_token": c1["refresh_token"],
                      "client_id": c["client_id"]})
    assert st == 200 and c2["refresh_token"] != c1["refresh_token"]
    # l'ancien resurgit : refuse ET la famille entiere tombe (le nouveau aussi)
    st3, e3 = a.jeton({"grant_type": "refresh_token", "refresh_token": c1["refresh_token"],
                       "client_id": c["client_id"]})
    assert st3 == 400 and e3["error"] == "invalid_grant"
    st4, e4 = a.jeton({"grant_type": "refresh_token", "refresh_token": c2["refresh_token"],
                       "client_id": c["client_id"]})
    assert st4 == 400 and e4["error"] == "invalid_grant"


# 7/11 (decision owner) : aucune tolerance au rejeu, la fenetre de 30 s du 6/11 etait une faille.
def _tourne(a, c):
    _, c1 = a.jeton(_form(c, _accorde(a, c)["code"][0]))
    st, c2 = a.jeton({"grant_type": "refresh_token", "refresh_token": c1["refresh_token"], "client_id": c["client_id"]})
    assert st == 200
    return c1, c2


def _renouvelle(a, jeton, client_id, **sur):
    return a.jeton({"grant_type": "refresh_token", "refresh_token": jeton, "client_id": client_id, **sur})


def test_rejeu_immediat_revoque_la_famille(env):
    a, _h, _d, _sig = env
    c = _client(a)
    c1, c2 = _tourne(a, c)
    st3, e3 = _renouvelle(a, c1["refresh_token"], c["client_id"])
    assert st3 == 400 and e3["error"] == "invalid_grant" and "access_token" not in e3
    assert _renouvelle(a, c2["refresh_token"], c["client_id"])[0] == 400    # le jeton neuf tombe aussi


def test_plus_aucune_fenetre_de_tolerance_dans_le_code():
    assert not hasattr(C, "GRACE_REJEU_S")
    assert not hasattr(C.AutoriteClientsHub, "_rejeu_tolere")


def test_rejeu_par_un_autre_client_revoque(env):
    a, _h, _d, _sig = env
    c = _client(a)
    c1, c2 = _tourne(a, c)
    st, e = _renouvelle(a, c1["refresh_token"], "nkc_autre")
    assert st == 400 and e["error"] == "invalid_grant"
    assert _renouvelle(a, c2["refresh_token"], c["client_id"])[0] == 400


def test_rejeu_d_une_famille_revoquee_reste_refuse(env):
    a, _h, _d, _sig = env
    c = _client(a)
    c1, c2 = _tourne(a, c)
    assert _renouvelle(a, c1["refresh_token"], "nkc_autre")[0] == 400       # famille tombee
    st, e = _renouvelle(a, c1["refresh_token"], c["client_id"])
    assert st == 400 and e["error"] == "invalid_grant"
    assert _renouvelle(a, c2["refresh_token"], c["client_id"])[0] == 400


def test_rejeu_avec_portee_elargie_revoque_aussi(env):
    a, _h, _d, _sig = env
    c = _client(a)
    c1, c2 = _tourne(a, c)
    st, e = _renouvelle(a, c1["refresh_token"], c["client_id"], scope="mcp:hub admin")
    assert st == 400 and "access_token" not in e
    assert _renouvelle(a, c2["refresh_token"], c["client_id"])[0] == 400


def test_rejeu_refuse_apres_redemarrage(env):
    a, h, d, sig = env
    c = _client(a)
    c1, c2 = _tourne(a, c)
    b = C.AutoriteClientsHub(d, sig, RES, ISS, horloge=h)
    assert _renouvelle(b, c1["refresh_token"], c["client_id"])[0] == 400
    assert _renouvelle(b, c2["refresh_token"], c["client_id"])[0] == 400


def test_le_rejeu_n_ecrit_aucun_jeton_sur_disque(env):
    a, _h, d, _sig = env
    c = _client(a)
    c1, _c2 = _tourne(a, c)
    assert _renouvelle(a, c1["refresh_token"], c["client_id"])[0] == 400
    for f in d.glob("*.json"):
        assert c1["refresh_token"] not in f.read_text(encoding="utf-8"), f.name


def test_revocation_rfc7009(env):
    a, h, d, sig = env
    c = _client(a)
    _, corps = a.jeton(_form(c, _accorde(a, c)["code"][0]))
    assert a.revoquer({"token": "inconnu", "client_id": c["client_id"]})[0] == 200
    assert a.revoquer({"token": corps["access_token"], "client_id": c["client_id"]})[0] == 200
    assert a.verifier_acces(corps["access_token"])[0] is None
    assert a.revoquer({"token": corps["refresh_token"], "token_type_hint": "refresh_token",
                       "client_id": c["client_id"]})[0] == 200
    st, e = a.jeton({"grant_type": "refresh_token", "refresh_token": corps["refresh_token"],
                     "client_id": c["client_id"]})
    assert st == 400 and e["error"] == "invalid_grant"


def test_acces_expire_et_audience(env):
    a, h, d, sig = env
    c = _client(a)
    _, corps = a.jeton(_form(c, _accorde(a, c)["code"][0]))
    h.t += 3601
    assert "expir" in a.verifier_acces(corps["access_token"])[1]


def test_jwks_publie_sans_partie_privee(env):
    a, h, d, sig = env
    k = a.jwks()["keys"][0]
    assert k["kid"] == sig.kid and k["alg"] == "ES256" and k["use"] == "sig" and "d" not in k
