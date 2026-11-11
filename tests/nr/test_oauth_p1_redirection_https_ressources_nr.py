"""NR 3/11 — lot P1 du plan OAuth MCP (docs/PLAN_OAUTH_MCP_HUB_20261102.md) : claude.ai sur l'autorite du hub.

Mesure du 3/11 : `valider_inscription` refusait `https://claude.ai/api/mcp/auth_callback` (bouclage seul) ; une seule
ressource et une seule portee (`mcp:hub`) alors que le pont des pairs annonce `pair:collaborer`.

Exigences :
  - claude.ai (doc connecteurs/authentication, `claude_docs:claude.com/docs/connectors/building/authentication.md`) :
    redirect `https://claude.ai/api/mcp/auth_callback` EXACT ; Claude Code garde son bouclage a port libre.
  - RFC 6749 §3.1.2.2 / OAuth 2.1 : comparaison de chaine EXACTE pour une redirection non-bouclage (pas de motif,
    pas de prefixe, pas de requete ajoutee).
  - RFC 8707 : `resource` parmi celles DECLAREES, sinon invalid_target ; portee propre a chaque ressource.
  - Separation : un jeton emis pour le pont (aud = pont) n'ouvre JAMAIS le /mcp du hub.
"""
import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from app import forge_oauth_clients as C
from app import forge_oauth_route as R
from app import forge_signature_hub as S

RES_HUB = "http://127.0.0.1:8766/mcp"
RES_PONT = "https://pont.exemple.ts.net/mcp"
ISS = "http://127.0.0.1:8766"
CLAUDE_AI = "https://claude.ai/api/mcp/auth_callback"
VERIF = "w" * 50
DEFI = base64.urlsafe_b64encode(hashlib.sha256(VERIF.encode()).digest()).rstrip(b"=").decode()


def _meta(uri):
    return {"client_name": "Claude", "redirect_uris": [uri], "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]}


# -- inscription -----------------------------------------------------------------------------------

def test_claude_ai_exact_est_admis():
    c, err = R.valider_inscription(_meta(CLAUDE_AI))
    assert err is None and c["redirect_uris"] == [CLAUDE_AI]


@pytest.mark.parametrize("uri", [
    CLAUDE_AI + "/",
    CLAUDE_AI + "?x=1",
    "http://claude.ai/api/mcp/auth_callback",
    "https://claude.ai.evil.example/api/mcp/auth_callback",
    "https://CLAUDE.ai/api/mcp/auth_callback",
    "https://claude.ai:8443/api/mcp/auth_callback",
    "https://claude.ai/api/mcp/auth_callback#f",
    "https://evil.example/cb",
])
def test_toute_autre_https_est_refusee(uri):
    c, err = R.valider_inscription(_meta(uri))
    assert c is None and err == "invalid_redirect_uri"


AGY = "https://antigravity.google/oauth-callback"


def test_agy_exact_est_admis():
    """Mesure 3/11 06:31-06:32 : 11 inscriptions « Google Antigravity » refusees (invalid_redirect_uri) avec
    redirect_uris=['https://antigravity.google/oauth-callback'] (doc antigravity.google/docs/cli/mcp)."""
    c, err = R.valider_inscription(_meta(AGY))
    assert err is None and c["redirect_uris"] == [AGY]


@pytest.mark.parametrize("uri", [AGY + "/", AGY + "?x=1", "http://antigravity.google/oauth-callback",
                                 "https://antigravity.google.evil.example/oauth-callback",
                                 "https://antigravity.google/oauth-callback2"])
def test_variantes_agy_refusees(uri):
    assert R.valider_inscription(_meta(uri)) == (None, "invalid_redirect_uri")


VSCODE = ["https://insiders.vscode.dev/redirect", "https://vscode.dev/redirect", "http://127.0.0.1/",
          "http://127.0.0.1:33418/"]


def test_inscription_vscode_mesuree_est_admise():
    """Mesure 3/11 12:2x : 3 inscriptions « Visual Studio Code » refusees (invalid_redirect_uri) avec exactement ces 4
    redirections ; VS Code se rabattait sur la saisie manuelle d'un identifiant client."""
    m = _meta(VSCODE[0])
    m["redirect_uris"] = list(VSCODE)
    c, err = R.valider_inscription(m)
    assert err is None and c["redirect_uris"] == VSCODE


@pytest.mark.parametrize("uri", ["https://vscode.dev/redirect/", "https://vscode.dev/redirect?x=1",
                                 "http://vscode.dev/redirect", "https://evil.vscode.dev.example/redirect",
                                 "https://vscode.dev/redirect2"])
def test_variantes_vscode_refusees(uri):
    assert R.valider_inscription(_meta(uri)) == (None, "invalid_redirect_uri")


def test_le_bouclage_de_claude_code_reste_admis():
    for uri in ("http://localhost:3118/callback", "http://127.0.0.1:40123/callback"):
        c, err = R.valider_inscription(_meta(uri))
        assert err is None, uri


def test_un_melange_avec_une_https_inconnue_est_refuse():
    m = _meta(CLAUDE_AI)
    m["redirect_uris"].append("https://evil.example/cb")
    assert R.valider_inscription(m) == (None, "invalid_redirect_uri")


# -- autorisation ----------------------------------------------------------------------------------

def _clients():
    return {"nkc_x": {"client_id": "nkc_x", "redirect_uris": [CLAUDE_AI, "http://localhost/callback"]}}


def _params(**sur):
    p = {"client_id": "nkc_x", "redirect_uri": CLAUDE_AI, "response_type": "code", "code_challenge": DEFI,
         "code_challenge_method": "S256", "resource": RES_PONT, "scope": "pair:collaborer", "state": "s"}
    p.update(sur)
    return {k: v for k, v in p.items() if v is not None}


RESSOURCES = {RES_HUB: {"mcp:hub"}, RES_PONT: {"pair:collaborer"}}


def test_ressource_du_pont_avec_sa_portee():
    d, err, _ = R.valider_autorisation(_params(), _clients(), RESSOURCES)
    assert err is None and d["resource"] == RES_PONT and d["scope"] == "pair:collaborer"


def test_portee_par_defaut_est_celle_de_la_ressource():
    d, err, _ = R.valider_autorisation(_params(scope=None), _clients(), RESSOURCES)
    assert err is None and d["scope"] == "pair:collaborer"


def test_portee_du_hub_refusee_sur_la_ressource_du_pont():
    assert R.valider_autorisation(_params(scope="mcp:hub"), _clients(), RESSOURCES)[1] == "invalid_scope"


def test_ressource_non_declaree():
    assert R.valider_autorisation(_params(resource="https://autre/mcp"), _clients(), RESSOURCES)[1] == "invalid_target"


def test_redirection_exacte_exigee_a_l_autorisation():
    d, err, peut = R.valider_autorisation(_params(redirect_uri=CLAUDE_AI + "?x=1"), _clients(), RESSOURCES)
    assert d is None and err == "invalid_request" and peut is False


def test_forme_historique_une_seule_ressource():
    d, err, _ = R.valider_autorisation(_params(resource=RES_HUB, scope="mcp:hub"), _clients(), RES_HUB)
    assert err is None and d["resource"] == RES_HUB


# -- autorite : un jeton du pont n'ouvre pas le hub -------------------------------------------------

class _Horloge:
    t = 1_800_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def autorite(tmp_path):
    coffre = {}
    sig = S.obtenir_signataire(nom_cle="test-p1", tpm=False, lire=coffre.get, ecrire=coffre.__setitem__)
    return C.AutoriteClientsHub(tmp_path, sig, RES_HUB, ISS, horloge=_Horloge(),
                                ressources_annexes={RES_PONT: {"pair:collaborer"}})


def _jeton_pour(a, ressource, portee):
    c, err = a.inscrire(_meta(CLAUDE_AI))
    assert err is None
    did, err, _, _ = a.demander_autorisation(_params(client_id=c["client_id"], resource=ressource, scope=portee))
    assert err is None
    code = parse_qs(urlsplit(a.accorder(did, identite="OAUTH_CLAUDE_AI", ring=1)).query)["code"][0]
    statut, corps = a.jeton({"grant_type": "authorization_code", "code": code, "redirect_uri": CLAUDE_AI,
                             "client_id": c["client_id"], "code_verifier": VERIF, "resource": ressource})
    assert statut == 200, corps
    return corps["access_token"]


def test_jeton_du_pont_refuse_par_le_hub(autorite):
    jeton = _jeton_pour(autorite, RES_PONT, "pair:collaborer")
    charge, motif = autorite.verifier_acces(jeton)
    assert charge is None and "audience" in motif


def test_jeton_du_pont_porte_l_aud_du_pont(autorite):
    jeton = _jeton_pour(autorite, RES_PONT, "pair:collaborer")
    charge, motif = autorite.verifier_acces(jeton, ressource=RES_PONT)
    assert motif is None and charge["aud"] == RES_PONT and charge["ring"] == 1


def test_jeton_du_hub_reste_valide_au_hub(autorite):
    c, _ = autorite.inscrire(_meta("http://127.0.0.1:1/callback"))
    assert autorite.client(c["client_id"]) is not None
    jeton = _jeton_pour(autorite, RES_HUB, "mcp:hub")
    assert autorite.verifier_acces(jeton)[1] is None


def test_ressource_non_declaree_refusee_par_la_verification(autorite):
    jeton = _jeton_pour(autorite, RES_PONT, "pair:collaborer")
    assert autorite.verifier_acces(jeton, ressource="https://autre/mcp")[0] is None
