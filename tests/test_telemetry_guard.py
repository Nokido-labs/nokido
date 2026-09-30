"""forge_swarm_telemetry_guard — signature/vérif des vecteurs multicast (anti-injection)."""
import importlib

import pytest

vg = importlib.import_module("forge_swarm_telemetry_guard")


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(vg, "_SECRET_OVERRIDE", b"secret-k1", raising=False)


def test_sign_verify_roundtrip(key):
    f = vg.sign_vector(b"\x01\x02vector", "NODE_A", ts=1000.0)
    r = vg.verify_vector(f, now=1001.0)
    assert r["ok"] and r["agent"] == "NODE_A" and r["payload"] == b"\x01\x02vector"


def test_tamper_payload_rejected(key):
    f = bytearray(vg.sign_vector(b"vecteur", "NODE_A", ts=1000.0))
    f[-1] ^= 0xFF  # un nœud rogue altère le vecteur
    r = vg.verify_vector(bytes(f), now=1000.0)
    assert not r["ok"] and "HMAC" in r["reason"]


def test_wrong_key_rejected(monkeypatch):
    monkeypatch.setattr(vg, "_SECRET_OVERRIDE", b"k1", raising=False)
    f = vg.sign_vector(b"vec", "N", ts=1000.0)
    monkeypatch.setattr(vg, "_SECRET_OVERRIDE", b"k2", raising=False)  # injecteur, autre clé
    assert not vg.verify_vector(f, now=1000.0)["ok"]


def test_replay_rejected(key):
    f = vg.sign_vector(b"vec", "N", ts=1000.0)
    r = vg.verify_vector(f, now=1020.0, max_age_s=10.0)
    assert not r["ok"] and "replay" in r["reason"]


def test_bad_magic(key):
    assert vg.verify_vector(b"XXXX" + b"\x00" * 50, now=0.0)["ok"] is False


def test_egress_membrane(key):
    assert vg.egress_ok(b"\x01\x02\x03binvec") is True            # vecteur binaire OK
    assert vg.egress_ok(b"token bearer abc", is_text=True) is False  # secret texte bloqué
    assert vg.egress_ok(b"hello cluster", is_text=True) is True


def test_meta_roundtrip():
    b = vg.pack_meta({"worker": "w1", "goap": ["x"]})
    meta, rest = vg.unpack_meta(b + b"VECTORBYTES")
    assert meta["worker"] == "w1" and rest == b"VECTORBYTES"


def test_broadcast_egress_block():
    sent = []
    r = vg.broadcast_vector(lambda f: sent.append(f), b"api_key=secret", "N", is_text=True)
    assert r["sent"] is False and not sent


def test_broadcast_ingest_with_meta(key):
    sent = []
    r = vg.broadcast_vector(lambda f: sent.append(f), b"\x01\x02vec", "NODE", meta={"w": "1"})
    assert r["sent"] is True and len(sent) == 1
    got = {}
    res = vg.ingest_vector(sent[0], update_fn=lambda vec, ag, m: got.update(vec=vec, ag=ag, m=m),
                           has_meta=True)
    assert res["ok"] and got["vec"] == b"\x01\x02vec" and got["m"]["w"] == "1" and got["ag"] == "NODE"


def test_ingest_rejects_tampered(key):
    sent = []
    vg.broadcast_vector(lambda f: sent.append(f), b"vec", "N")
    bad = bytearray(sent[0]); bad[-1] ^= 0xFF
    assert not vg.ingest_vector(bytes(bad))["ok"]
