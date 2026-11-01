"""NR suite 3 : diagnostic 401 TPM, route POST /oauth/token (ASGI), observation ring<=3,
forge_secrets, lanceur. Aucune valeur de jeton affichee (assertions booleennes)."""
import base64
import hashlib
import hmac
import json
import sys
import time
import types
from urllib.parse import urlencode

import pytest

from app import forge_dpop as dp
from app import forge_oauth_route as orr
from app import forge_token_exchange as tx

SECRET = b"k" * 32
URL = "http://testserver/oauth/token"
OBS_URL = "http://testserver/api/task/assign"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(orr, "_secret", lambda: SECRET)
    monkeypatch.delenv("NOKIDO_OAUTH_ENFORCE", raising=False)
    dp._jti_vus.clear()
    orr.OBSERVES.clear()


def _client():
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient
    return TestClient(Starlette(routes=[Route("/oauth/token", orr.oauth_token, methods=["POST"])]))


def _post(sub, job="job_x", scope="task:status", aud="hub", cle=None, avec_preuve=True):
    cle = cle or orr.cle_test()
    h = {"content-type": "application/x-www-form-urlencoded"}
    if avec_preuve:
        h["DPoP"] = dp.creer_preuve("POST", URL, cle=cle)
    corps = urlencode({"grant_type": tx.GRANT_TYPE, "subject_token": sub,
                       "subject_token_type": tx.TYPE_JOB, "job_id": job,
                       "audience": aud, "scope": scope})
    return _client().post("/oauth/token", content=corps, headers=h), cle


def test_enforcement_desarme_par_defaut():
    assert orr.enforcement_arme() is False


def test_route_http_echange_rfc8693_2_2_1():
    sub = orr.emettre_pour_job("job_x", ttl=600)
    r, cle = _post(sub)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    c = r.json()
    assert c["token_type"] == "DPoP" and c["issued_token_type"] == tx.TYPE_ACCESS
    ch = tx.lire_jeton(c["access_token"], SECRET)
    assert ch["cnf"]["jkt"] == dp.thumbprint(dp.jwk_public(cle))


def test_route_http_refus_rfc8693_2_2_2():
    r, _ = _post(orr.emettre_pour_job("job_x", ttl=600), job="job_autre")
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    r, _ = _post(orr.emettre_pour_job("job_x", ttl=600), scope="admin:all")
    assert r.status_code == 400 and r.json()["error"] == "invalid_scope"


def test_route_sans_preuve_dpop_refusee():
    r, _ = _post(orr.emettre_pour_job("job_x", ttl=600), avec_preuve=False)
    assert r.status_code == 400 and r.json()["error"] == "invalid_dpop_proof"


def test_jeton_job_ttl_borne_et_lie():
    ch = tx.lire_jeton(orr.emettre_pour_job("job_x", ttl=10 ** 9), SECRET)
    assert ch["job_id"] == "job_x" and ch["exp"] - ch["iat"] <= orr.TTL_JOB_MAX


def _acces(scope="task:status"):
    r, cle = _post(orr.emettre_pour_job("job_x", ttl=600), scope=scope)
    return r.json()["access_token"], cle


def test_observation_ring3_journalise_sans_bloquer():
    jeton, cle = _acces("task:status")
    preuve = dp.creer_preuve("POST", OBS_URL, jeton_acces=jeton, cle=cle)
    rep = orr.observer_appel(jeton, preuve, "POST", OBS_URL, "task:assign", 3)
    assert rep["status"] == 200 and rep["aurait_refuse"] == "insufficient_scope"
    assert orr.OBSERVES[-1]["aurait_refuse"] == "insufficient_scope"
    assert jeton not in json.dumps(orr.OBSERVES)


def test_observation_ring4_non_concerne():
    assert orr.observer_appel("x", "y", "POST", OBS_URL, "s", 4) is None


def test_enforcement_arme_bloque(monkeypatch):
    monkeypatch.setenv("NOKIDO_OAUTH_ENFORCE", "1")
    jeton, cle = _acces("task:status")
    preuve = dp.creer_preuve("POST", OBS_URL, jeton_acces=jeton, cle=cle)
    assert orr.observer_appel(jeton, preuve, "POST", OBS_URL, "task:assign", 3)["status"] == 403


# --- (1) diagnostic 401 jeton TPM owner -------------------------------------------------
def test_nr_401_tpm_inverifiable_refuse_un_jeton_intact(monkeypatch):
    """Cause : CapabilityToken.decode leve ValueError quand verify_etat rend INVERIFIABLE
    (cle TPM machine non ouvrable depuis le compte) ; le hub traduit en 401."""
    from app.forge_integrity import CapabilityToken
    fake = types.ModuleType("nokido_agent.app.forge_persona_tpm")
    fake.tpm_available = lambda: True
    fake.verify_etat = lambda payload, sig: ("INVERIFIABLE", "cle non ouvrable")
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_persona_tpm", fake)
    p = base64.urlsafe_b64encode(json.dumps(
        {"sub": "OWNER", "ring": 0, "exp": time.time() + 99, "iat": time.time()}).encode()
    ).rstrip(b"=").decode()
    sig = hmac.new(b"z" * 32, p.encode(), hashlib.sha256).hexdigest()
    jeton = "%s.%s.%s" % (p, sig, "QUJD")
    with pytest.raises(ValueError, match="INVERIFIABLE"):
        CapabilityToken.decode(jeton, b"z" * 32)


# --- (5) forge_secrets ------------------------------------------------------------------
def test_secrets_observation_lecture_cloisonnee(monkeypatch):
    from app import forge_secrets as fs
    monkeypatch.setenv("NOKIDO_COMPTES_BAC", "bacuser")
    monkeypatch.setattr(fs, "_compte_du_jeton", lambda: "bacuser")
    assert fs.observer_lecture_cloisonnee("FORGE_TOKEN_SWARM_LANCEUR") == \
        (True, "aurait_refuse:bac_ring_le_3")
    assert fs.observer_lecture_cloisonnee("GROQ_API_KEY") == (True, "ok")


def test_secrets_migration_dry_run_noms_seulement_reel_refuse(capsys):
    from app import forge_secrets as fs
    assert fs.migrer_cli(["--dry-run"], noms=["FORGE_TOKEN_A", "GROQ_API_KEY"]) == 0
    out = capsys.readouterr().out
    assert "FORGE_TOKEN_A" in out and "GROQ_API_KEY" not in out
    assert fs.migrer_cli([], noms=["FORGE_TOKEN_A"]) == 2


# --- (6) lanceur ------------------------------------------------------------------------
def test_lanceur_echange_si_route_repond_sinon_ancien_chemin(monkeypatch):
    from tools import forge_secours_lanceur as la
    monkeypatch.setattr(la, "_jeton_session", lambda s: "ancien")
    monkeypatch.setattr(la, "_echange_job", lambda: None)
    assert la._session_pour("secret") == "ancien"
    monkeypatch.setattr(la, "_echange_job", lambda: "neuf")
    assert la._session_pour("secret") == "neuf"
