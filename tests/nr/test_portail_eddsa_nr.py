"""NR -- sessions du portail en EdDSA, cle publique ENREGISTREE de WEBHUB (decision owner 2026-09-28).

Avant : le portail signait ses sessions en HS256 avec LAFORGE_JWT_SECRET, la cle des JWT du
hub -- tout lecteur de la cle pouvait fabriquer une session. Apres :
  - cle PRIVEE Ed25519 au coffre PERSONNEL du compte du portail ;
  - cle PUBLIQUE enregistree par l'owner (sous SYSTEM) au registre des cles d'agents,
    agent WEBHUB ; c'est la SEULE source de verification -- jamais une cle derivee d'une
    cle privee trouvee ailleurs ;
  - le portail n'emet en EdDSA que si SA cle est deja enregistree (sinon HS256 de
    TRANSITION : aucune session que le hub ne saurait verifier) ;
  - HS256 fermable (LAFORGE_PORTAIL_HS256_ACCEPTE=0) ; tout autre `alg` rejete.
Outil `tools/forge_portail_cle.py` : `--generer` (compte du portail, rien d'affiche de la
cle privee), `--enregistrer` (SYSTEM seulement).
Cles fabriquees ici ; aucune assertion n'affiche une valeur.
"""
import base64
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

ed = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
from cryptography.hazmat.primitives import serialization  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NOM_PRIVE = "LAFORGE_PORTAIL_ED25519_PRIVE"
CLE_HS = ("cle-hs-portail-nr-" + "h" * 32).encode()


def _b64(o: bytes) -> str:
    return base64.urlsafe_b64encode(o).rstrip(b"=").decode("ascii")


def _paire():
    k = ed.Ed25519PrivateKey.generate()
    brut = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                           serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64(brut), {"kty": "OKP", "crv": "Ed25519", "x": _b64(pub)}


@pytest.fixture
def env(monkeypatch, tmp_path):
    auth = importlib.import_module("nokido_agent.app.web_hub.auth")
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    ak = importlib.import_module("nokido_agent.app.forge_agent_keys")
    monkeypatch.setattr(ak, "_CHEMIN", tmp_path / "agent_keys.json")
    monkeypatch.setattr(ak, "_CACHE", None)
    store = {}
    monkeypatch.setattr(fs, "get_secret", lambda k, required=False: store.get(k))
    monkeypatch.delenv("LAFORGE_PORTAIL_HS256_ACCEPTE", raising=False)
    cfg = auth.AuthConfig(enabled=True, admin_token="admin-nr-" + "x" * 32, jwt_secret=CLE_HS,
                          jwt_ttl_s=60, fail_closed=False, legacy_secrets=())
    return {"auth": auth, "ak": ak, "store": store, "cfg": cfg}


def _alg(tok):
    return json.loads(base64.urlsafe_b64decode(tok.split(".")[0] + "==")).get("alg")


def test_cle_enregistree_emission_eddsa_et_verification(env):
    prive, jwk = _paire()
    env["store"][NOM_PRIVE] = prive
    env["ak"].enregistrer("WEBHUB", jwk)
    tok = env["auth"].issue_token(env["cfg"], "admin")
    assert _alg(tok) == "EdDSA"
    assert env["auth"].verify_token(env["cfg"], tok) is not None


def test_le_hub_verifie_par_le_registre_sans_cle_privee(env):
    prive, jwk = _paire()
    env["store"][NOM_PRIVE] = prive
    env["ak"].enregistrer("WEBHUB", jwk)
    tok = env["auth"].issue_token(env["cfg"], "admin")
    assert _alg(tok) == "EdDSA"
    env["store"].clear()  # le hub (SYSTEM) ne detient pas la cle privee du portail
    assert env["auth"].verify_token(env["cfg"], tok) is not None


def test_cle_non_enregistree_transition_hs256(env):
    prive, _jwk = _paire()
    env["store"][NOM_PRIVE] = prive
    tok = env["auth"].issue_token(env["cfg"], "admin")
    assert _alg(tok) == "HS256"
    assert env["auth"].verify_token(env["cfg"], tok) is not None


def test_une_cle_privee_non_enregistree_ne_forge_pas_de_session(env):
    _prive_ok, jwk_ok = _paire()
    env["ak"].enregistrer("WEBHUB", jwk_ok)
    prive_intrus, _ = _paire()
    env["store"][NOM_PRIVE] = prive_intrus  # cle privee posee ailleurs (env, fichier...)
    auth = env["auth"]
    priv = ed.Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(prive_intrus + "=="))
    import jwt as _jwt
    import time
    forge = _jwt.encode({"sub": "admin", "iat": int(time.time()), "nbf": int(time.time()),
                         "exp": int(time.time()) + 60, "aud": "nokido:webhub"},
                        priv, algorithm="EdDSA", headers={"kid": "0" * 43})
    assert auth.verify_token(env["cfg"], forge) is None
    assert _alg(auth.issue_token(env["cfg"], "admin")) == "HS256"


def test_hs256_fermable_eddsa_reste(env, monkeypatch):
    prive, jwk = _paire()
    ancien = env["auth"].issue_token(env["cfg"], "admin")  # HS256 : aucune cle encore
    env["store"][NOM_PRIVE] = prive
    env["ak"].enregistrer("WEBHUB", jwk)
    neuf = env["auth"].issue_token(env["cfg"], "admin")
    monkeypatch.setenv("LAFORGE_PORTAIL_HS256_ACCEPTE", "0")
    assert env["auth"].verify_token(env["cfg"], ancien) is None
    assert env["auth"].verify_token(env["cfg"], neuf) is not None


def test_alg_none_rejete(env):
    tete = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    corps = _b64(json.dumps({"sub": "admin", "exp": 9999999999, "iat": 1, "nbf": 1}).encode())
    assert env["auth"].verify_token(env["cfg"], f"{tete}.{corps}.") is None


# --- outil ---------------------------------------------------------------------------

def _outil():
    spec = importlib.util.spec_from_file_location("forge_portail_cle_nr", ROOT / "tools" / "forge_portail_cle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generer_sous_le_compte_du_portail(monkeypatch, tmp_path, capsys):
    o = _outil()
    ecrits = {}
    monkeypatch.setattr(o, "_sous_system", lambda: False)
    pub = tmp_path / "portail.pub.json"
    jkt = o.generer(pub, ecrire=lambda k, v: ecrits.__setitem__(k, v) or True, lire=lambda k: None)
    assert list(ecrits) == [NOM_PRIVE]
    ok = len(base64.urlsafe_b64decode(ecrits[NOM_PRIVE] + "==")) == 32
    assert ok
    jwk = json.loads(pub.read_text(encoding="utf-8"))
    assert jwk.get("kty") == "OKP" and jwk.get("crv") == "Ed25519" and "d" not in jwk
    sortie = capsys.readouterr().out
    assert ecrits[NOM_PRIVE] not in sortie and jkt


def test_generer_refuse_sous_system_et_sans_remplacer(monkeypatch, tmp_path):
    o = _outil()
    monkeypatch.setattr(o, "_sous_system", lambda: True)
    with pytest.raises(SystemExit):
        o.generer(tmp_path / "p.json", ecrire=lambda k, v: True, lire=lambda k: None)
    monkeypatch.setattr(o, "_sous_system", lambda: False)
    with pytest.raises(SystemExit):
        o.generer(tmp_path / "p.json", ecrire=lambda k, v: True, lire=lambda k: "deja-la")


def test_enregistrer_sous_system_seulement(monkeypatch, tmp_path):
    o = _outil()
    ak = importlib.import_module("nokido_agent.app.forge_agent_keys")
    monkeypatch.setattr(ak, "_CHEMIN", tmp_path / "agent_keys.json")
    monkeypatch.setattr(ak, "_CACHE", None)
    _prive, jwk = _paire()
    pub = tmp_path / "portail.pub.json"
    pub.write_text(json.dumps(jwk), encoding="utf-8")
    monkeypatch.setattr(o, "_sous_system", lambda: False)
    with pytest.raises(SystemExit):
        o.enregistrer(pub)
    monkeypatch.setattr(o, "_sous_system", lambda: True)
    entree = o.enregistrer(pub)
    assert entree["status"] == "ACTIVE"
    assert [c["jkt"] for c in ak.cles_acceptees("WEBHUB")] == [entree["jkt"]]
