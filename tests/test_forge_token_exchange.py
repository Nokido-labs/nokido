"""NR echange de jetons RFC 8693 + liaison DPoP RFC 9449 (horloge figee, aucune valeur de jeton affichee)."""
import time

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app import forge_dpop as dp
from app import forge_token_exchange as tx

T0 = 1_800_000_000.0
SECRET = b"s" * 32
TE = tx.GRANT_TYPE
POL = {"SWARM_LANCEUR": {"ring": 3, "scopes": ["task:status", "task:assign"],
                         "audiences": ["hub"]}}
URI = "https://hub.local/api/task/assign"


@pytest.fixture(autouse=True)
def horloge(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: T0)
    dp._jti_vus.clear()


def _cle():
    return ec.generate_private_key(ec.SECP256R1())


def _sub(job="j1", ttl=600, ident="SWARM_LANCEUR"):
    return tx.emettre_jeton_job(job, ident, ttl, SECRET, now=T0)


def _ech(sub, job="j1", cle=None, scope="task:status", aud="hub", mode="bloquant",
         now=T0, jwk=True, grant=TE):
    cle = cle or _cle()
    rep = tx.echanger(grant, sub, tx.TYPE_JOB, job, aud, scope,
                      dp.jwk_public(cle) if jwk else None, POL, SECRET, mode, now=now)
    return rep, cle


def _appel(cle, jeton, scope="task:assign", preuve=None, mode="bloquant"):
    preuve = preuve if preuve is not None else dp.creer_preuve("POST", URI, jeton, cle=cle)
    return tx.verifier_appel(jeton, preuve, "POST", URI, scope, SECRET, mode, now=T0)


def test_echange_valide_rfc8693_2_2_1():
    rep, cle = _ech(_sub())
    assert rep["ok"] is True
    c = rep["corps"]
    assert c["token_type"] == "DPoP"
    assert c["issued_token_type"] == "urn:ietf:params:oauth:token-type:access_token"
    assert 0 < c["expires_in"] <= 300 and c["scope"] == "task:status"
    ch = tx.lire_jeton(c["access_token"], SECRET, now=T0)
    assert ch["cnf"]["jkt"] == dp.thumbprint(dp.jwk_public(cle))
    assert ch["act"]["sub"] == "job:j1" and ch["ring"] == 3


def test_ttl_borne_par_le_job():
    rep, _ = _ech(_sub(ttl=30))
    assert rep["corps"]["expires_in"] <= 30


def test_subject_expire_refuse():
    rep, _ = _ech(_sub(ttl=10), now=T0 + 11)
    assert rep["ok"] is False and rep["corps"]["error"] == "invalid_grant"


def test_autre_job_refuse():
    rep, _ = _ech(_sub("j1"), job="j2")
    assert rep["ok"] is False and rep["corps"]["error"] == "invalid_grant"


def test_audience_et_portee_invalides():
    assert _ech(_sub(), aud="autre")[0]["corps"]["error"] == "invalid_target"
    assert _ech(_sub(), scope="admin:all")[0]["corps"]["error"] == "invalid_scope"


def test_dpop_obligatoire_et_grant_type():
    assert _ech(_sub(), jwk=False)[0]["corps"]["error"] == "invalid_request"
    assert _ech(_sub(), grant="x")[0]["corps"]["error"] == "unsupported_grant_type"


def test_appel_valide_puis_rejeu_refuse():
    rep, cle = _ech(_sub(), scope="task:status task:assign")
    jeton = rep["corps"]["access_token"]
    preuve = dp.creer_preuve("POST", URI, jeton, cle=cle)
    assert _appel(cle, jeton, preuve=preuve)["status"] == 200
    r = _appel(cle, jeton, preuve=preuve)
    assert r["status"] == 401 and "rejeu" in r["raison"]


def test_ath_faux_refuse():
    rep, cle = _ech(_sub(), scope="task:assign")
    jeton = rep["corps"]["access_token"]
    mauvaise = dp.creer_preuve("POST", URI, "autre-jeton", cle=cle)
    assert _appel(cle, jeton, preuve=mauvaise)["status"] == 401


def test_autre_cle_refusee():
    rep, cle = _ech(_sub(), scope="task:assign")
    assert _appel(_cle(), rep["corps"]["access_token"])["status"] == 401


def test_portee_absente_403_insufficient_scope():
    rep, cle = _ech(_sub(), scope="task:status")
    r = _appel(cle, rep["corps"]["access_token"], scope="task:assign")
    assert r["status"] == 403 and r["error"] == "insufficient_scope"
    assert "insufficient_scope" in r["www_authenticate"]


def test_observation_ne_bloque_pas_mais_journalise():
    rep, cle = _ech(_sub(), scope="task:status")
    r = _appel(cle, rep["corps"]["access_token"], mode="observation")
    assert r["status"] == 200 and r["aurait_refuse"] == "insufficient_scope"
    rep, _ = _ech(_sub(), job="j2", mode="observation")
    assert rep["ok"] is True and rep["aurait_refuse"] == "invalid_grant"


def test_jeton_owner_tpm_avec_dpop_accepte():
    faux_tpm = _cle()  # faux TPM : meme chemin de verification
    jeton = tx.emettre_jeton_lie("owner", 1, ["task:assign"],
                                 dp.thumbprint(dp.jwk_public(faux_tpm)), 120, SECRET, now=T0)
    assert _appel(faux_tpm, jeton)["status"] == 200
    r = _appel(faux_tpm, jeton, preuve="")  # sans DPoP : refuse
    assert r["status"] == 401
