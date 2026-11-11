"""NR 3/11 — revoquer un CLIENT OAuth (owner : « fais revoquer_client » ; « est-on conforme RFC ? renforce-t-on la
securite ? »).

Conformite : revocation des jetons = politique du serveur d'autorisation, effet a l'appel suivant (RFC 7009 §2.2) ;
retrait d'une inscription par l'administrateur = politique AS (RFC 7591/7592 l'admettent sans la normer).
Securite : DEUX verrous independants -- familles revoquees (tout jeton existant refuse) ET entree du registre retiree
(un jeton restant retomberait au ring 3, verification max(registre, jeton)).
"""
import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app import forge_oauth_clients as C
from app import forge_signature_hub as S
from nokido_agent.app import forge_ring_admin as A

RES, ISS = "http://127.0.0.1:8766/mcp", "http://127.0.0.1:8766"
VERIF = "r" * 50
DEFI = base64.urlsafe_b64encode(hashlib.sha256(VERIF.encode()).digest()).rstrip(b"=").decode()
REDIR = "http://localhost:40999/callback"


@pytest.fixture
def autorite(tmp_path):
    coffre = {}
    sig = S.obtenir_signataire(nom_cle="t-rev", tpm=False, lire=coffre.get, ecrire=coffre.__setitem__)
    return C.AutoriteClientsHub(tmp_path, sig, RES, ISS)


def _client_avec_jetons(a):
    c, _ = a.inscrire({"redirect_uris": ["http://localhost:1/callback"], "client_name": "CC"})
    did, _, _, _ = a.demander_autorisation({"response_type": "code", "client_id": c["client_id"], "redirect_uri": REDIR,
                                            "code_challenge": DEFI, "code_challenge_method": "S256", "resource": RES})
    code = parse_qs(urlsplit(a.accorder(did, identite="OAUTH_" + c["client_id"], ring=1)).query)["code"][0]
    _, j = a.jeton({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIR,
                    "client_id": c["client_id"], "code_verifier": VERIF, "resource": RES})
    return c, j


def test_revoquer_client_coupe_tout(autorite):
    c, j = _client_avec_jetons(autorite)
    assert autorite.verifier_acces(j["access_token"])[1] is None
    r = autorite.revoquer_client(c["client_id"])
    assert r["ok"] is True and r["familles_revoquees"] == 1 and r["inscription_retiree"] is True
    assert autorite.verifier_acces(j["access_token"])[0] is None                       # acces refuse aussitot
    st, e = autorite.jeton({"grant_type": "refresh_token", "refresh_token": j["refresh_token"],
                            "client_id": c["client_id"]})
    assert st == 400 and e["error"] == "invalid_grant"                                  # renouvellement mort
    assert autorite.client(c["client_id"]) is None


def test_revocation_persiste_au_redemarrage(autorite, tmp_path):
    c, j = _client_avec_jetons(autorite)
    autorite.revoquer_client(c["client_id"])
    b = C.AutoriteClientsHub(tmp_path, autorite._sig, RES, ISS)
    assert b.verifier_acces(j["access_token"])[0] is None and b.client(c["client_id"]) is None


def test_client_inconnu_dit(autorite):
    r = autorite.revoquer_client("nkc_inexistant")
    assert r["ok"] is False and "inconnu" in r["raison"]


def test_retirer_l_entree_du_registre(tmp_path, monkeypatch):
    p = tmp_path / "ids.json"
    p.write_text(json.dumps({"agents": {"CLAUDE": {"ring": 1}, "OAUTH_NKC_X": {"ring": 1}}}), encoding="utf-8")
    monkeypatch.setattr(A, "_STORE", p)
    audits = []
    monkeypatch.setattr(A, "_audit", lambda m: audits.append(m))
    assert A.retirer_client_oauth("OAUTH_nkc_x")["ok"] is True
    agents = json.loads(p.read_text(encoding="utf-8"))["agents"]
    assert "OAUTH_NKC_X" not in agents and agents["CLAUDE"]["ring"] == 1 and audits
    assert A.retirer_client_oauth("CLAUDE")["ok"] is False                             # jamais hors OAUTH_
    assert json.loads(p.read_text(encoding="utf-8"))["agents"]["CLAUDE"]["ring"] == 1
