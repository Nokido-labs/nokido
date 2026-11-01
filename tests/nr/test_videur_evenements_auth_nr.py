# -*- coding: utf-8 -*-
"""NR — resolve_identity emet un evenement d'authentification JSONL par decision.

Aucune base reelle, aucun vrai jeton : NOKIDO_DATA_DIR pointe sur tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_videur as v  # noqa: E402

CLES = {"ts", "agent_declare", "agent_resolu", "via", "ring", "canal", "provenance", "decision", "motif"}
JETON_FACTICE = "jeton-factice-ABCDEF-123456"


@pytest.fixture(autouse=True)
def _bac(monkeypatch, tmp_path):
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LAFORGE_DATA_DIR", raising=False)
    monkeypatch.setattr(v, "_LOG", tmp_path / "videur_identity.log", raising=False)
    return tmp_path


def _events(tmp):
    p = tmp / "sandbox" / "logs" / "auth_events.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_token_valide_accepte(tmp_path):
    v.resolve_identity("VIBE", JETON_FACTICE, True, {"VIBE": JETON_FACTICE}, "")
    (e,) = _events(tmp_path)
    assert CLES <= set(e)
    assert e["via"] == "token" and e["decision"] == "accepte"
    assert e["agent_declare"] == "VIBE" and e["agent_resolu"] == "VIBE"
    assert e["provenance"] == "INCONNUE"


def test_jamais_de_valeur_de_jeton(tmp_path):
    v.resolve_identity("VIBE", JETON_FACTICE, True, {"VIBE": JETON_FACTICE}, "")
    brut = (tmp_path / "sandbox" / "logs" / "auth_events.jsonl").read_text(encoding="utf-8")
    assert JETON_FACTICE not in brut


def test_bad_token_refuse(tmp_path):
    v.resolve_identity("VIBE", JETON_FACTICE + "x", True, {"VIBE": JETON_FACTICE}, "")
    (e,) = _events(tmp_path)
    assert e["via"] == "bad_token" and e["decision"] == "refuse" and e["motif"]


def test_absent(tmp_path):
    v.resolve_identity("", "", True, {}, "")
    (e,) = _events(tmp_path)
    assert e["via"] == "absent"


def test_header_seul(tmp_path):
    v.resolve_identity("CLAUDE", "", True, {"CLAUDE": JETON_FACTICE}, "")
    (e,) = _events(tmp_path)
    assert e["via"] == "header" and e["agent_declare"] == "CLAUDE"


def test_master_token_et_provenance(tmp_path):
    v.resolve_identity("VIBE", "maitre-factice", True, {}, "maitre-factice", provenance="HEADLESS")
    (e,) = _events(tmp_path)
    assert e["via"] == "master_token" and e["provenance"] == "HEADLESS"
    assert "maitre-factice" not in json.dumps(e)


def test_une_ligne_par_decision(tmp_path):
    for _ in range(3):
        v.resolve_identity("VIBE", "", True, {}, "")
    assert len(_events(tmp_path)) == 3


def test_echec_ecriture_ne_casse_pas_et_est_journalise(monkeypatch, caplog):
    def boom(*a, **k):
        raise OSError("disque plein")
    monkeypatch.setattr(v, "_chemin_auth_events", boom)
    with caplog.at_level("WARNING"):
        r = v.resolve_identity("VIBE", JETON_FACTICE, True, {"VIBE": JETON_FACTICE}, "")
    assert r["via"] == "token"
    assert any("auth_events" in m for m in caplog.messages)
