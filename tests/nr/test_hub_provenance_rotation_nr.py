# -*- coding: utf-8 -*-
"""NR - le hub transmet LaForge-Provenance (validee) au videur ; rotation de auth_events.jsonl."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_videur as v  # noqa: E402

JETON = "jeton-factice-ABCDEF-123456"
TOKS = dict(VIBE=JETON)
MAITRE = "maitre-factice-0123456789"


@pytest.fixture(autouse=True)
def _bac(monkeypatch, tmp_path):
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LAFORGE_DATA_DIR", raising=False)
    monkeypatch.setattr(v, "_LOG", tmp_path / "videur_identity.log", raising=False)


def _events(tmp):
    p = tmp / "sandbox" / "logs" / "auth_events.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _req(prov=None):
    h = dict(Authorization="Bearer " + JETON)
    h["LaForge-Agent-Name"] = "VIBE"
    if prov is not None:
        h["LaForge-Provenance"] = prov
    return SimpleNamespace(headers=h, client=SimpleNamespace(host="127.0.0.1"))


def _hub(monkeypatch):
    import nokido_hub as hub
    monkeypatch.setattr(hub, "HUB_TOKEN", MAITRE, raising=False)
    monkeypatch.setattr(hub, "_AGENT_TOKENS", TOKS, raising=False)
    return hub


def test_provenance_http_valide_et_invalide(monkeypatch):
    hub = _hub(monkeypatch)
    assert hub._provenance_http(_req("TASK_EXECUTOR")) == "TASK_EXECUTOR"
    assert hub._provenance_http(_req("X & calc")) == "INVALIDE"
    assert hub._provenance_http(_req()) == ""


@pytest.mark.parametrize("entete,attendu", [("TASK_EXECUTOR", "TASK_EXECUTOR"), ("X & calc", "INVALIDE")])
def test_resolve_ring_ecrit_la_provenance(monkeypatch, tmp_path, entete, attendu):
    hub = _hub(monkeypatch)
    hub._resolve_ring(_req(entete))
    evs = _events(tmp_path)
    assert evs and evs[-1]["provenance"] == attendu
    assert "calc" not in json.dumps(evs)


def test_identite_inbox_ecrit_la_provenance(monkeypatch, tmp_path):
    hub = _hub(monkeypatch)
    hub._identite_inbox(_req("TASK_EXECUTOR"))
    assert _events(tmp_path)[-1]["provenance"] == "TASK_EXECUTOR"


def test_rotation_au_dela_du_seuil(monkeypatch, tmp_path):
    monkeypatch.setattr(v, "AUTH_EVENTS_MAX_BYTES", 200)
    chemin = tmp_path / "sandbox" / "logs" / "auth_events.jsonl"
    chemin.parent.mkdir(parents=True)
    chemin.write_text("x" * 500, encoding="utf-8")
    chemin.with_name(chemin.name + ".1").write_text("ancienne", encoding="utf-8")
    v.resolve_identity("VIBE", JETON, True, TOKS, "", provenance="T")
    assert chemin.with_name(chemin.name + ".1").read_text(encoding="utf-8") == "x" * 500
    assert len(_events(tmp_path)) == 1


def test_echec_de_rotation_nempeche_rien(monkeypatch, tmp_path):
    monkeypatch.setattr(v, "AUTH_EVENTS_MAX_BYTES", 10)
    chemin = tmp_path / "sandbox" / "logs" / "auth_events.jsonl"
    chemin.parent.mkdir(parents=True)
    chemin.write_text("ligne-existante-assez-longue\n", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("verrou")
    monkeypatch.setattr(v._os, "replace", boom)
    sortie = v.resolve_identity("VIBE", JETON, True, TOKS, "")
    assert sortie["agent"] == "VIBE"
    assert len(chemin.read_text(encoding="utf-8").splitlines()) == 2
