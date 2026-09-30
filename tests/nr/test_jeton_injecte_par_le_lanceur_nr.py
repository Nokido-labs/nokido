"""NR -- jeton court injecte par le superviseur (decision owner 2026-09-28), etape C : le
service l'UTILISE et le RENOUVELLE.

Le superviseur (LocalSystem) passait a chaque enfant tout son environnement, jeton maitre
compris. Il injectera a la place un jeton COURT pour l'identite du service
(`NOKIDO_JETON_COURT` + `NOKIDO_IDENTITE`). Cote service, `forge_agent_credential.jeton_pour` :
  1. rend le jeton injecte pour l'identite NOMMEE par le lanceur, et pour elle seule ;
  2. le RETIRE de l'environnement a la premiere lecture : les processus que le service lance
     n'en heritent pas ;
  3. le renouvelle, pres de l'expiration, par un ECHANGE DE JETON RFC 8693 (corps
     form-urlencoded, `grant_type` token-exchange, `subject_token_type` access_token) ;
  4. n'envoie jamais son jeton hors de la boucle locale ;
  5. expire et non renouvelable : il n'invente rien -- ni jeton statique pris ailleurs, ni
     maitre (`jeton_pour` n'en a jamais eu) -- et l'etat le dit.
Aucune vraie valeur : les jetons sont fabriques ici, le hub est substitue.
"""
from __future__ import annotations

import base64
import importlib
import json
import time
from urllib.parse import parse_qs

import pytest

CRED = "nokido_agent.app.forge_agent_credential"
IDENT = "SERVICE_NR_LANCE"


def _faux_jeton(reste_s: float, marque: str = "a") -> str:
    charge = json.dumps({"sub": IDENT, "exp": time.time() + reste_s, "m": marque}).encode()
    return base64.urlsafe_b64encode(charge).rstrip(b"=").decode() + ".signature-de-test"


@pytest.fixture
def cred(monkeypatch):
    c = importlib.import_module(CRED)

    def _vider():
        c.invalider()
        for etat in (c._INJECTES, c._ECHEC_RENOUVELLEMENT, c._ETAT):
            etat.clear()

    _vider()
    monkeypatch.setattr(c, "_statique", lambda agent: "")
    monkeypatch.delenv("LAFORGE_HUB_URL", raising=False)
    yield c
    _vider()


def test_le_jeton_injecte_sert_son_identite_et_quitte_l_environnement(cred, monkeypatch):
    import os
    jeton = _faux_jeton(1500)
    monkeypatch.setenv("NOKIDO_IDENTITE", IDENT)
    monkeypatch.setenv("NOKIDO_JETON_COURT", jeton)
    ok = (cred.jeton_pour(IDENT) == jeton, "NOKIDO_JETON_COURT" in os.environ,
          cred.etat()["detail"][IDENT]["mode"], cred.etat()["injectes"])
    assert ok == (True, False, "INJECTE", 1)
    assert cred.jeton_pour(IDENT) == jeton            # toujours servi, depuis la memoire


def test_le_jeton_injecte_n_est_jamais_prete_a_une_autre_identite(cred, monkeypatch):
    monkeypatch.setenv("NOKIDO_IDENTITE", "UNE_AUTRE_IDENTITE")
    monkeypatch.setenv("NOKIDO_JETON_COURT", _faux_jeton(1500))
    assert cred.jeton_pour(IDENT) == ""


def test_pres_de_l_expiration_il_se_renouvelle_par_un_echange_rfc8693(cred, monkeypatch):
    import urllib.request
    ancien, neuf = _faux_jeton(120, "ancien"), _faux_jeton(1800, "neuf")
    vus: list = []

    class _Rep:
        def __init__(self, corps):
            self._c = corps

        def read(self):
            return self._c

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout=0):
        vus.append((req.full_url, req.get_header("Content-type"), parse_qs(req.data.decode())))
        return _Rep(json.dumps({"access_token": neuf, "token_type": "Bearer",
                                "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
                                "expires_in": 1800}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    monkeypatch.setenv("NOKIDO_IDENTITE", IDENT)
    monkeypatch.setenv("NOKIDO_JETON_COURT", ancien)
    ok = cred.jeton_pour(IDENT) == neuf
    assert ok
    url, type_contenu, champs = vus[0]
    forme = (url.endswith("/api/login/renouveler"), type_contenu,
             champs.get("grant_type"), champs.get("subject_token_type"), champs.get("subject_token") == [ancien])
    assert forme == (True, "application/x-www-form-urlencoded",
                     ["urn:ietf:params:oauth:grant-type:token-exchange"],
                     ["urn:ietf:params:oauth:token-type:access_token"], True)
    assert cred.etat()["detail"][IDENT]["mode"] == "INJECTE_RENOUVELE"


def test_jamais_de_renouvellement_hors_boucle_locale(cred, monkeypatch):
    monkeypatch.setenv("LAFORGE_HUB_URL", "http://hub.exemple.test:8766")
    ok = (cred._url_renouvellement_du_hub() == "", cred._renouveler_par_le_hub(_faux_jeton(60)) == "")
    assert ok == (True, True)


def test_expire_et_non_renouvelable_il_n_invente_rien(cred, monkeypatch):
    monkeypatch.setattr(cred, "_renouveler_par_le_hub", lambda jeton: "")
    monkeypatch.setenv("NOKIDO_IDENTITE", IDENT)
    monkeypatch.setenv("NOKIDO_JETON_COURT", _faux_jeton(-10))
    assert cred.jeton_pour(IDENT) == ""
    assert cred.etat()["injectes_expires"] == 1
