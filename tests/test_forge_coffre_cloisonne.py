"""Coffre cloisonne + client d'echange minimal (RFC 8693 / RFC 9449). Aucune valeur de jeton."""
import json

from app import forge_coffre_cloisonne as cc
from app import forge_token_exchange as te

BAC = {"LaForgeSbxOnline", "LaForgeSbxOffline"}
SECRET = b"s" * 32


def test_bac_refuse_identite_ring_3():
    assert cc.decision_lecture("LaForgeSbxOnline", "identite", 2, BAC, "bloquant") == (False, "bac_ring_le_3")


def test_bac_autorise_hors_identite_ou_ring_eleve():
    assert cc.decision_lecture("LaForgeSbxOnline", "identite", 4, BAC, "bloquant")[0] is True
    assert cc.decision_lecture("LaForgeSbxOnline", "api", 1, BAC, "bloquant")[0] is True


def test_owner_garde_acces():
    assert cc.decision_lecture("user", "identite", 0, BAC, "bloquant")[0] is True


def test_observation_laisse_passer_et_signale():
    ok, raison = cc.decision_lecture("LaForgeSbxOnline", "identite", 2, BAC, "observation")
    assert ok is True and raison == "aurait_refuse:bac_ring_le_3"


def test_migration_dry_run_ne_touche_rien():
    entrees = [{"nom": "id_a", "genre": "identite", "ring": 1},
               {"nom": "api_x", "genre": "api", "ring": 5}]
    plan = cc.planifier_migration(entrees, dry_run=True)
    assert plan["execute"] is False
    assert [m["nom"] for m in plan["deplacements"]] == ["id_a"]
    assert "valeur" not in json.dumps(plan)


def test_migration_reelle_refusee_sans_ordre_owner():
    try:
        cc.planifier_migration([], dry_run=False)
    except PermissionError:
        return
    raise AssertionError("migration reelle doit etre refusee")


def test_client_echange_puis_appel_dpop_verifie():
    job = te.emettre_jeton_job("j1", "id_a", 120, SECRET)
    cle = cc.cle_ephemere()
    req = cc.demande_echange(job, "j1", "hub", "read", cle)
    assert req["grant_type"] == te.GRANT_TYPE and "dpop_jwk" in req
    rep = te.echanger(req["grant_type"], req["subject_token"], req["subject_token_type"],
                      "j1", "hub", "read", req["dpop_jwk"],
                      {"id_a": {"audiences": ["hub"], "scopes": ["read"], "ring": 3}}, SECRET,
                      mode="bloquant")
    jeton = rep["corps"]["access_token"]
    preuve = cc.preuve_appel(cle, "GET", "https://hub/x", jeton)
    r = te.verifier_appel(jeton, preuve, "GET", "https://hub/x", "read", SECRET, mode="bloquant")
    assert r["status"] == 200
