# -*- coding: utf-8 -*-
"""NR -- un acte RSI rend son service NON EVINCABLE jusqu'au verdict (veto de sommeil, 15/10).

MESURE QUI L'A DECLENCHE. RESOURCE_MANAGER a endormi NokidoAutonomousLoops 14 fois le 15/10
(`sandbox/supervisor_ordres.jsonl`). Un sommeil entre un acte L1 et sa mesure laisse un acte ORPHELIN
reel : repris et defait au cycle suivant, le reglage n'est jamais juge.

Contrat, sur les chemins REELS :
  1. `forge_mutation_controller.appliquer_et_mesurer` pose le veto du service qui porte l'acte
     (`LAFORGE_SERVICE_SELF`) AVANT l'acte, et le leve apres le verdict -- meme si la mesure leve ;
  2. hors service (variable absente : CLI, test), rien n'est pose ;
  3. `_non_essential_sains()` (sommeil RAM) saute un service sous veto, et seulement lui ;
  4. un veto expire, hors borne ou illisible est ignore : il ne bloque jamais la regulation.
"""
from __future__ import annotations

import json
import sys
import time
import types

import pytest

from nokido_agent.app import forge_autonomous_loops as al
from nokido_agent.app import forge_mutation_controller as mc
from nokido_agent.app import forge_resource_manager as rm


@pytest.fixture
def vetos(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "_VETO_SOMMEIL_DIR", tmp_path / "veto_sommeil")
    monkeypatch.setattr(rm, "_audit_lifecycle", lambda *a, **k: None)
    return tmp_path / "veto_sommeil"


@pytest.fixture
def banc(tmp_path, monkeypatch, vetos):
    monkeypatch.setattr(al, "_EVOLUTION_LEDGER", tmp_path / "evolution_experiences.jsonl")
    monkeypatch.setattr(al, "_ensure_ledger_migrated", lambda: None)
    monkeypatch.setattr(mc, "_generation_avant", lambda: None)
    monkeypatch.setattr(mc, "_porte", lambda: {"autorisee": True, "etat": "ARMEE", "motif": ""})
    etat = {"v": 0}
    vus = []

    def appliquer():
        vus.append(dict(rm.vetos_sommeil_actifs()))   # ce que la regulation VOIT pendant l'acte
        etat.update(v=1)
        return {"ok": True}

    def appeler():
        return mc.appliquer_et_mesurer(
            "L1", "param:x", "exp-veto", appliquer=appliquer,
            reverter=lambda: etat.update(v=0) or {"ok": True},
            mesurer=lambda: {"score": 1.0}, empreinte=lambda: str(etat["v"]), bruit={"score": 0.1})
    return appeler, vus


def test_l_acte_pose_le_veto_puis_le_leve(banc, monkeypatch):
    monkeypatch.setenv("LAFORGE_SERVICE_SELF", "NokidoAutonomousLoops")
    appeler, vus = banc
    r = appeler()
    assert r["verdict"] == "CONSERVE", r
    assert "NokidoAutonomousLoops" in vus[0] and "param:x" in vus[0]["NokidoAutonomousLoops"], vus
    assert rm.vetos_sommeil_actifs() == {}                     # leve apres le verdict


def test_le_veto_est_leve_meme_si_la_mesure_leve(banc, monkeypatch):
    monkeypatch.setenv("LAFORGE_SERVICE_SELF", "NokidoAutonomousLoops")

    def _panne(*_a, **_k):
        raise RuntimeError("mesure en panne")

    monkeypatch.setattr(mc, "mesurer_apres", _panne)
    appeler, _vus = banc
    with pytest.raises(RuntimeError):
        appeler()
    assert rm.vetos_sommeil_actifs() == {}


def test_hors_service_aucun_veto(banc, monkeypatch):
    monkeypatch.delenv("LAFORGE_SERVICE_SELF", raising=False)
    appeler, vus = banc
    assert appeler()["verdict"] == "CONSERVE"
    assert vus == [{}]


def test_le_sommeil_ram_saute_le_service_sous_veto_et_lui_seul(vetos, monkeypatch):
    monkeypatch.setattr(rm, "_services_du_toml", lambda: {})
    caps = types.ModuleType("nokido_agent.app.forge_service_capabilities")
    caps.is_critical = lambda svc: False
    caps.why_critical = lambda svc: ""
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_service_capabilities", caps)
    avant = rm._non_essential_sains()
    assert "NokidoAutonomousLoops" in avant
    assert rm.poser_veto_sommeil("NokidoAutonomousLoops", "acte a1")["ok"]
    apres = rm._non_essential_sains()
    assert "NokidoAutonomousLoops" not in apres
    assert set(avant) - set(apres) == {"NokidoAutonomousLoops"}


def test_duree_bornee_et_vetos_perimes_ignores(vetos):
    r = rm.poser_veto_sommeil("A", "x", duree_s=10 ** 6)
    assert r["jusqu_a"] - r["pose_a"] <= rm._VETO_SOMMEIL_MAX_S
    maintenant = time.time()
    vetos.mkdir(parents=True, exist_ok=True)
    (vetos / "B.json").write_text(json.dumps({"service": "B", "jusqu_a": maintenant - 1}), encoding="utf-8")
    (vetos / "C.json").write_text(json.dumps({"service": "C", "jusqu_a": maintenant + 10 ** 6}), encoding="utf-8")
    (vetos / "D.json").write_text("{pas du json", encoding="utf-8")
    assert set(rm.vetos_sommeil_actifs()) == {"A"}
    assert rm.lever_veto_sommeil("A") and rm.lever_veto_sommeil("A")   # idempotent
    assert rm.vetos_sommeil_actifs() == {}
