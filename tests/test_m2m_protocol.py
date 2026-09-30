# -*- coding: utf-8 -*-
"""Tests Sprint 3 : protocole M2M (forge_m2m_protocol + canal postal)."""
import json
import os
import sys

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.90)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

import forge_m2m_protocol as m2m  # noqa: E402


@pytest.fixture()
def iso(monkeypatch):
    monkeypatch.delenv("LAFORGE_M2M_MODE", raising=False)
    monkeypatch.setattr(m2m, "_MODE_MARKER", m2m._ROOT / "sandbox" / "_absent_m2m_mode.txt")
    yield monkeypatch


def test_m2m_valide(iso):
    v = m2m.validate("postal", {"intent": "COLLAB_PING", "pointer_ref": "bb:tree_locks/X",
                                "confidence": 0.8, "proposed_action": "review", "thought_process": "anti dup"})
    assert v["code"] == "M2M_OK"


def test_alias_intent_code(iso):
    v = m2m.validate("notify", {"intent_code": "LOCK_RELEASED", "pointer_ref": "bb:tree_locks/X", "key": "X", "owner": "CLAUDE"})
    assert v["code"] == "M2M_OK"


def test_intent_inconnu(iso):
    v = m2m.validate("notify", {"intent": "YOLO_CODE", "pointer_ref": "x"})
    assert v["code"] == "M2M_ERR_UNKNOWN_INTENT"


def test_champ_requis_manquant(iso):
    v = m2m.validate("postal", {"intent": "COLLAB_PING", "pointer_ref": "x"})  # confidence absent
    assert v["code"] == "M2M_ERR_MISSING_FIELD"
    assert any("confidence" in s for s in v["violations"])


def test_prose_courte_toleree(iso):
    v = m2m.validate("notify", "lock libere, voie libre")
    assert v["code"] == "M2M_OK_PROSE"


def test_prose_longue_warn(iso):
    prose = " ".join(["mot"] * 40)
    v = m2m.validate("notify", prose)
    assert v["code"] == "M2M_WARN_PROSE"
    assert v["words"] == 40


def test_payload_json_string(iso):
    s = json.dumps({"intent": "OK_DONE", "pointer_ref": "commit:abc"})
    v = m2m.validate("notify", s)
    assert v["code"] == "M2M_OK"


def test_check_warn_laisse_passer(iso, monkeypatch):
    monkeypatch.setattr(m2m, "publish_stub", None, raising=False)
    ok, v = m2m.check("notify", " ".join(["mot"] * 40))
    assert ok and v["code"] == "M2M_WARN_PROSE"


def test_check_error_bloque(iso, monkeypatch):
    monkeypatch.setenv("LAFORGE_M2M_MODE", "error")
    ok, v = m2m.check("notify", " ".join(["mot"] * 40))
    assert not ok
    ok2, v2 = m2m.check("notify", {"intent": "OK_DONE", "pointer_ref": "x"})
    assert ok2 and v2["code"] == "M2M_OK"


def test_catalogue_couvre_tool_scope(iso):
    intents = m2m._load_catalog()["intents"]
    for code in ("SCOPE_SET", "SCOPE_LOW_CONF_FULL", "SCOPE_CLEARED"):
        assert code in intents


# ── Canal postal : refus en mode error, queued en warn ──────────────────────

def test_postal_post_m2m(iso, monkeypatch, tmp_path):
    import forge_postal as fp

    monkeypatch.setattr(fp, "DB", tmp_path / "postal.db")
    prose = " ".join(["blabla"] * 40)

    r = fp.post("CLAUDE", "ANTIGRAVITY", prose)  # warn : passe
    assert r["status"] == "queued"

    monkeypatch.setenv("LAFORGE_M2M_MODE", "error")
    r2 = fp.post("CLAUDE", "ANTIGRAVITY", prose + " encore")  # error : refuse
    assert r2["status"] == "refused" and "m2m" in r2["reason"]

    ok_body = json.dumps({"intent": "COLLAB_PING", "pointer_ref": "x", "confidence": 0.9})
    r3 = fp.post("CLAUDE", "ANTIGRAVITY", ok_body)  # M2M valide : passe meme en error
    assert r3["status"] == "queued"
