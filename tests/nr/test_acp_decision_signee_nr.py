"""NR : une decision ACP n'est valide que signee (JWS EdDSA) par la cle du hub ; tout le reste = cancelled."""
import sys
import threading
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization as S
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import forge_acp_hub as H  # noqa: E402
import forge_acp_router as R  # noqa: E402

OPTS = [{"optionId": "ok", "kind": "allow_once", "name": "ok"}]
REQ = {"sessionId": "s", "options": OPTS}


def _cle(kid="k1"):
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(S.Encoding.Raw, S.PublicFormat.Raw)
    return (priv, kid), {kid: pub}


def _lancer(tmp_path, epingle, agir, delai=3):
    pol = R.politique_owner(dossier=tmp_path, delai_s=delai, epingle_fn=lambda: epingle)
    res = {}
    t = threading.Thread(target=lambda: res.update(pol(REQ, session="s", agent="claude")))
    t.start()
    fs = []
    for _ in range(100):
        fs = list(tmp_path.glob("*.json"))
        if fs:
            break
        time.sleep(0.05)
    agir(fs[0].stem)
    t.join(10)
    return res


def _signer(cle):
    return lambda payload: H.sceller("acp_decision", payload, cle)


def test_non_signee_cancelled(tmp_path):
    cle, ep = _cle()
    res = _lancer(tmp_path, ep, lambda pid: R.decider(pid, option="ok", dossier=tmp_path))
    assert res == {"outcome": "cancelled"}


def test_autre_cle_cancelled(tmp_path):
    cle, ep = _cle()
    autre, _ = _cle()
    res = _lancer(tmp_path, ep, lambda pid: R.decider(pid, option="ok", dossier=tmp_path, signer=_signer(autre)))
    assert res == {"outcome": "cancelled"}


def test_pid_echange_cancelled(tmp_path):
    cle, ep = _cle()
    res = _lancer(tmp_path, ep, lambda pid: R.decider(
        pid, option="ok", dossier=tmp_path,
        signer=lambda p: H.sceller("acp_decision", dict(p, pid="a" * 32), cle)))
    assert res == {"outcome": "cancelled"}


def test_rejouee_cancelled():
    cle, ep = _cle()
    vus = set()
    pid = "b" * 32
    jws = H.sceller("acp_decision", {"pid": pid, "option": "ok", "refuser": False, "sub": "o"}, cle)
    assert R.verifier_decision(jws, pid, ep, time.time() - 1, time.time(), 60, vus)[0]
    assert not R.verifier_decision(jws, pid, ep, time.time() - 1, time.time(), 60, vus)[0]


def test_perimee_cancelled():
    cle, ep = _cle()
    pid = "c" * 32
    jws = H.sceller("acp_decision", {"pid": pid, "option": "ok", "refuser": False, "sub": "o"}, cle,
                    now=time.time() - 1000)
    assert not R.verifier_decision(jws, pid, ep, time.time() - 5, time.time(), 60, set())[0]


def test_signee_valide_appliquee(tmp_path):
    cle, ep = _cle()
    res = _lancer(tmp_path, ep, lambda pid: R.decider(pid, option="ok", dossier=tmp_path, signer=_signer(cle)))
    assert res == {"outcome": "selected", "optionId": "ok"}
