"""NR -- etape 2b-3 du correctif du coffre : JWT du hub en Ed25519 (plan valide le 2026-09-28).

Avant : JWT HS256, cle symetrique LAFORGE_JWT_SECRET. Tout lecteur de la cle -- le
portail sous le compte de l'owner, les comptes bac a sable au coffre machine -- pouvait
FABRIQUER un JWT du hub. Apres : EdDSA (RFC 8037), cle PRIVEE reservee
(LAFORGE_JWT_ED25519_PRIVE, coffre reserve, SYSTEM) ; le hub derive la cle publique en
memoire -- aucun fichier public qu'un compte bac a sable pourrait remplacer.

Ce que ce NR verrouille :
  - le nom est reserve et l'outil de provisionnement le GENERE (nouvelle cle, pas une
    rotation : aucune signature existante n'est invalidee), jamais regenere ;
  - avec la cle : emission EdDSA + `kid` ; verification par la cle publique ; portee ;
  - une signature d'une AUTRE cle Ed25519, un `kid` etranger, `alg=none`, et la confusion
    d'algorithme (HS256 signe avec la cle PUBLIQUE comme secret) sont rejetes ;
  - chaque cle ne sert qu'UN algorithme (RFC 8725 §3.1) ;
  - TRANSITION jusqu'a 2b-6 (go owner) : HS256 reste accepte avec SA cle, et c'est dit ;
    `LAFORGE_JWT_HS256_ACCEPTE=0` le ferme ; sans cle Ed25519, l'emission reste HS256.
Cles fabriquees ici ; aucune assertion n'affiche une valeur.
"""
import base64
import hashlib
import hmac
import importlib
import json
import logging

import pytest

ed = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
from cryptography.hazmat.primitives import serialization  # noqa: E402

CLE_HS = "cle-hs256-nr-2b3-" + "h" * 32
NOM_ED = "LAFORGE_JWT_ED25519_PRIVE"


def _b64(o: bytes) -> str:
    return base64.urlsafe_b64encode(o).rstrip(b"=").decode("ascii")


def _cle_ed_brute() -> str:
    k = ed.Ed25519PrivateKey.generate()
    return _b64(k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                serialization.NoEncryption()))


def _signer_hs(entete: dict, charge: dict, secret: bytes) -> str:
    h = _b64(json.dumps(entete, separators=(",", ":"), sort_keys=True).encode())
    p = _b64(json.dumps(charge, separators=(",", ":"), sort_keys=True).encode())
    s = hmac.new(secret, f"{h}.{p}".encode("ascii"), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64(s)}"


@pytest.fixture
def jwt(monkeypatch):
    mod = importlib.import_module("nokido_agent.app.forge_auth_jwt")
    store = {"LAFORGE_JWT_SECRET": CLE_HS, NOM_ED: _cle_ed_brute()}
    monkeypatch.setattr(mod, "get_secret", lambda k, required=False: store.get(k))
    monkeypatch.delenv("LAFORGE_JWT_HS256_ACCEPTE", raising=False)
    monkeypatch.setitem(mod._TRANSITION_DITE, "hs256", False)  # dite une fois par process
    mod._store_nr = store
    return mod


def _entete(tok: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(tok.split(".")[0] + "=="))


def test_le_nom_est_reserve():
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    assert NOM_ED in fs.NOMS_RESERVES


def test_emission_eddsa_avec_kid_et_verification(jwt):
    tok = jwt.issue_token("NR", ["services:start"], 60)
    h = _entete(tok)
    assert h.get("alg") == "EdDSA" and h.get("kid")
    assert jwt.verify_token(tok, required_scope="services:start") is not None
    assert jwt.verify_token(tok, required_scope="admin:shutdown_all") is None


def test_une_autre_cle_ed25519_est_rejetee(jwt):
    tok = jwt.issue_token("NR", [], 60)
    jwt._store_nr[NOM_ED] = _cle_ed_brute()  # le hub a une AUTRE cle
    assert jwt.verify_token(tok) is None


def test_un_kid_etranger_est_rejete(jwt):
    tok = jwt.issue_token("NR", [], 60)
    h, p, s = tok.split(".")
    ent = _entete(tok)
    ent["kid"] = "0" * 16
    h2 = _b64(json.dumps(ent, separators=(",", ":"), sort_keys=True).encode())
    assert jwt.verify_token(f"{h2}.{p}.{s}") is None


def test_alg_none_est_rejete(jwt):
    tok = jwt.issue_token("NR", [], 60)
    _h, p, _s = tok.split(".")
    h2 = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    assert jwt.verify_token(f"{h2}.{p}.") is None


def test_confusion_d_algorithme_cle_publique_comme_secret_hmac(jwt):
    priv = ed.Ed25519PrivateKey.from_private_bytes(
        base64.urlsafe_b64decode(jwt._store_nr[NOM_ED] + "=="))
    publique = priv.public_key().public_bytes(serialization.Encoding.Raw,
                                             serialization.PublicFormat.Raw)
    import time
    charge = {"iat": int(time.time()), "exp": int(time.time()) + 60, "sub": "NR", "scope": ["*"]}
    faux = _signer_hs({"alg": "HS256", "typ": "JWT"}, charge, publique)
    assert jwt.verify_token(faux) is None


def test_transition_hs256_acceptee_et_dite_puis_fermable(jwt, monkeypatch, caplog):
    import time
    charge = {"iat": int(time.time()), "exp": int(time.time()) + 60, "sub": "NR", "scope": []}
    ancien = _signer_hs({"alg": "HS256", "typ": "JWT"}, charge, CLE_HS.encode())
    with caplog.at_level(logging.WARNING):
        assert jwt.verify_token(ancien) is not None
    assert "TRANSITION" in caplog.text
    monkeypatch.setenv("LAFORGE_JWT_HS256_ACCEPTE", "0")
    assert jwt.verify_token(ancien) is None


def test_sans_cle_ed25519_l_emission_reste_hs256(jwt):
    jwt._store_nr.pop(NOM_ED)
    tok = jwt.issue_token("NR", [], 60)
    assert _entete(tok).get("alg") == "HS256"
    assert jwt.verify_token(tok) is not None


def test_l_outil_genere_la_cle_ed25519_sans_rotation_et_ne_la_regenere_jamais():
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "forge_coffre_provision_nr_2b3", root / "tools" / "forge_coffre_reserve_provision.py")
    o = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(o)
    mv = importlib.import_module("nokido_agent.app.forge_machine_vault")
    assert NOM_ED in o.NOUVELLES
    absente = lambda _n: (None, mv.RESERVE_CLE_ABSENTE)  # noqa: E731
    presente = lambda _n: ("x", mv.RESERVE_TROUVE)  # noqa: E731
    assert o.planifier_nouvelles(absente, rotation=False)[NOM_ED] == o.A_ECRIRE
    assert o.planifier_nouvelles(presente, rotation=True)[NOM_ED] == o.DEJA_EN_PLACE
    brute = o._GENERATEURS[NOM_ED]()
    ok = len(base64.urlsafe_b64decode(brute + "==")) == 32
    assert ok, "la cle generee n'est pas une cle privee Ed25519 brute de 32 octets"
