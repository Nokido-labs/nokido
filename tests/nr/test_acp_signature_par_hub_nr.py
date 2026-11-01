"""NR : la signature d'une decision ACP par le hub (SYSTEM) reverifie le JWT owner ; le web hub (compte owner)
ne lit jamais la cle privee, il POSTe sur le hub loopback. Cles et JWT de TEST, aucun reseau reel."""
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization as S
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import forge_acp_hub as H  # noqa: E402
import forge_acp_router as R  # noqa: E402

PAYLOAD = {"pid": "a" * 32, "option": "ok", "refuser": False, "sub": "owner"}
OPTS = [{"optionId": "ok", "kind": "allow_once", "name": "ok"}]


def _cle_jwt():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    brut = pub.public_bytes(S.Encoding.Raw, S.PublicFormat.Raw)
    return priv, pub, hashlib.sha256(brut).hexdigest()[:16]


@pytest.fixture
def jwt_mod(monkeypatch):
    J = H._importer_jwt()
    cle = _cle_jwt()
    monkeypatch.setattr(J, "_cle_ed25519", lambda: cle)
    return J


def _cle_decision(kid="k1"):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(S.Encoding.Raw, S.PublicFormat.Raw)
    return (priv, kid), {kid: pub}


def _jeton_admin(J):
    return J.issue_token("owner", scopes=[H.PORTEE_ADMIN], ttl_s=60)


def test_sans_jeton_refuse(jwt_mod):
    cle, _ = _cle_decision()
    for j in (None, "", "   "):
        with pytest.raises(PermissionError):
            H.signer_decision(j, PAYLOAD, _cle=cle)


def test_jeton_sans_portee_admin_refuse(jwt_mod):
    cle, _ = _cle_decision()
    jeton = jwt_mod.issue_token("owner", scopes=["services:start"], ttl_s=60)
    with pytest.raises(PermissionError):
        H.signer_decision(jeton, PAYLOAD, _cle=cle)


def test_jeton_d_une_autre_cle_refuse(jwt_mod, monkeypatch):
    cle, _ = _cle_decision()
    vraie = jwt_mod._cle_ed25519()
    monkeypatch.setattr(jwt_mod, "_cle_ed25519", lambda: _cle_jwt())
    forge = jwt_mod.issue_token("owner", scopes=[H.PORTEE_ADMIN], ttl_s=60)
    monkeypatch.setattr(jwt_mod, "_cle_ed25519", lambda: vraie)
    with pytest.raises(PermissionError):
        H.signer_decision(forge, PAYLOAD, _cle=cle)


def test_payload_cle_en_trop_ou_manquante_refuse(jwt_mod):
    cle, _ = _cle_decision()
    jeton = _jeton_admin(jwt_mod)
    with pytest.raises(PermissionError):
        H.signer_decision(jeton, dict(PAYLOAD, extra=1), _cle=cle)
    with pytest.raises(PermissionError):
        H.signer_decision(jeton, {"pid": "a" * 32}, _cle=cle)
    with pytest.raises(PermissionError):
        H.signer_decision(jeton, "pas un dict", _cle=cle)


def test_jeton_admin_valide_jws_verifiable(jwt_mod):
    cle, ep = _cle_decision()
    jws = H.signer_decision(_jeton_admin(jwt_mod), PAYLOAD, _cle=cle)
    ok, raison, corps = H.verifier(jws, ep, time.time())
    assert ok, raison
    assert corps["op"] == "acp_decision" and corps["params"] == PAYLOAD


def test_verifier_jeton_injecte():
    cle, _ = _cle_decision()
    vu = []
    jws = H.signer_decision("t", PAYLOAD, verifier_jeton=lambda t: vu.append(t) or {"sub": "o"}, _cle=cle)
    assert vu == ["t"] and jws.count(".") == 2
    with pytest.raises(PermissionError):
        H.signer_decision("t", PAYLOAD, verifier_jeton=lambda t: None, _cle=cle)


def test_signer_par_hub_poste_sur_loopback_seul():
    vus = {}

    def faux_post(url, jeton, payload):
        vus.update(url=url, jeton=jeton, payload=payload)
        return {"jws": "x.y.z"}

    s = R.signer_par_hub("JWT", _post=faux_post)
    assert s(PAYLOAD) == "x.y.z"
    assert vus["url"] == "http://127.0.0.1:8766/acp/sign" and vus["jeton"] == "JWT"
    with pytest.raises(ValueError):
        R.signer_par_hub("JWT", url="http://example.com:8766/acp/sign", _post=faux_post)


def test_decision_signee_par_le_hub_acceptee_par_politique_owner(tmp_path, jwt_mod):
    cle, ep = _cle_decision()
    jeton = _jeton_admin(jwt_mod)
    pol = R.politique_owner(dossier=tmp_path, delai_s=5, epingle_fn=lambda: ep)
    res = {}
    t = threading.Thread(target=lambda: res.update(
        pol({"sessionId": "s", "options": OPTS}, session="s", agent="claude")))
    t.start()
    fs = []
    for _ in range(100):
        fs = list(tmp_path.glob("*.json"))
        if fs:
            break
        time.sleep(0.05)
    pid = fs[0].stem
    signer = R.signer_par_hub(jeton, _post=lambda u, j, p: {"jws": H.signer_decision(j, p, _cle=cle)})
    R.decider(pid, option="ok", dossier=tmp_path, signer=signer)
    t.join(10)
    assert res == {"outcome": "selected", "optionId": "ok"}


def test_api_decider_passe_le_jeton_de_la_requete(monkeypatch):
    """api_decider construit signer=R.signer_par_hub(<jeton de la requete>)."""
    from app.web_hub import acp_views as V
    src = Path(V.__file__).read_text(encoding="utf-8")
    assert "R.signer_par_hub(jeton)" in src


def test_traiter_signature_http():
    cle, _ = _cle_decision()
    ok_corps = json.dumps(PAYLOAD).encode()
    assert H.traiter_signature(None, ok_corps, _cle=cle)[0] == 401
    assert H.traiter_signature("Bearer ", ok_corps, _cle=cle)[0] == 401
    assert H.traiter_signature("Bearer x", b"pas json", _cle=cle, verifier_jeton=lambda t: {"sub": "o"})[0] == 400
    assert H.traiter_signature("Bearer x", ok_corps, _cle=cle, verifier_jeton=lambda t: None)[0] == 403
    st, corps = H.traiter_signature("Bearer x", ok_corps, _cle=cle, verifier_jeton=lambda t: {"sub": "o"})
    assert st == 200 and corps["jws"].count(".") == 2
    assert set(corps) == {"jws"}
