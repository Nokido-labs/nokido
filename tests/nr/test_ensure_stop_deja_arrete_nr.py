# -*- coding: utf-8 -*-
"""NR -- ensure(svc, "stopped") sur un service deja arrete (30/10).

Mesure du 30/10 (NokidoLlamaKeeper.log 09:12-09:17) :
  Le keeper detecte la dette resorbee sur NokidoEmbedTrigger (dette=0),
  appelle ensure('NokidoEmbedTrigger', 'stopped').
  Or le service est deja sorti (code=1 a 09:12:43).
  forge_supervisor_ctl stop NokidoEmbedTrigger renvoie rc!=0 (rc=4 : service
  sans port declare -> effet non verifiable dans _verifier_effet).
  ensure() evaluait ok = r['rc'] == 0 -> False, rendant success=False.
  Le keeper ne posait jamais _DRAIN_ARRET_TS et re-emettait stop toutes les 30s.

Contrats :
  1. Si _supervisor('stop', name) renvoie rc!=0 mais que _statut_mesure(name)
     constate status in ('stopped', 'sleeping') et pid is None : ensure() doit renvoyer
     success=True et signaler 'deja_arrete'.
  2. Si _statut_mesure(name) est None (superviseur illisible ou indisponible) :
     ensure() doit renvoyer success=False (UNKNOWN != NO : jamais True sur une non-mesure).
  3. Si _statut_mesure(name) indique un service actif (ex. status=='running', pid!=None) :
     ensure() doit renvoyer success=False.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import tools.forge_ensure_service as fes  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def test_ensure_stop_deja_arrete_succes(monkeypatch):
    """Cas 1 : _supervisor rc!=0 (ex rc=4), _statut_mesure constate status stopped + pid None -> success True + deja_arrete."""
    monkeypatch.setattr(fes, "_supervisor", lambda act, name, timeout=90: {
        "rc": 4, "out": '{"effet": "ILLISIBLE", "preuve": "le service ne declare pas de port"}', "err": ""
    })
    monkeypatch.setattr(fes, "_statut_mesure", lambda name: {"status": "stopped", "pid": None, "restarts": 0})
    monkeypatch.setattr(fes, "_installe", lambda name: True)

    res = fes.ensure("NokidoEmbedTrigger", "stopped")
    assert res["success"] is True, f"Attendu success=True quand le service est deja arrete, recu: {res}"
    assert res.get("deja_arrete") is True or "deja_arrete" in str(res.get("detail", "")), (
        f"Attendu indicateur 'deja_arrete', recu: {res}"
    )


def test_ensure_stop_deja_arrete_alias_embed_succes(monkeypatch):
    """Cas 1bis : meme comportement via alias 'embed' (mappe sur NokidoLlamaEmbed)."""
    monkeypatch.setattr(fes, "_supervisor", lambda act, name, timeout=90: {
        "rc": 4, "out": '{"effet": "ILLISIBLE"}', "err": ""
    })
    monkeypatch.setattr(fes, "_statut_mesure", lambda name: {"status": "stopped", "pid": None, "restarts": 0})
    monkeypatch.setattr(fes, "_installe", lambda name: True)

    res = fes.ensure("embed", "stopped")
    assert res["success"] is True
    assert res["mapped"] == "NokidoLlamaEmbed"
    assert res.get("deja_arrete") is True or "deja_arrete" in str(res.get("detail", ""))


def test_ensure_stop_statut_illisible_echec_fail_closed(monkeypatch):
    """Cas 2 : _supervisor rc!=0, statut None (superviseur illisible) -> success False (UNKNOWN != NO)."""
    monkeypatch.setattr(fes, "_supervisor", lambda act, name, timeout=90: {
        "rc": 4, "out": "ERR", "err": "timeout supervisor"
    })
    monkeypatch.setattr(fes, "_statut_mesure", lambda name: None)
    monkeypatch.setattr(fes, "_installe", lambda name: True)

    res = fes.ensure("NokidoEmbedTrigger", "stopped")
    assert res["success"] is False, "UNKNOWN != NO : un statut illisible ne doit JAMAIS donner success=True"
    assert not res.get("deja_arrete"), "deja_arrete ne doit pas etre pose sur statut illisible"


def test_ensure_stop_service_encore_vivant_echec(monkeypatch):
    """Cas 3 : _supervisor rc!=0, statut montre process vivant (pid present, status running) -> success False."""
    monkeypatch.setattr(fes, "_supervisor", lambda act, name, timeout=90: {
        "rc": 3, "out": '{"effet": "NON_ATTEINT"}', "err": ""
    })
    monkeypatch.setattr(fes, "_statut_mesure", lambda name: {"status": "running", "pid": 12345, "restarts": 1})
    monkeypatch.setattr(fes, "_installe", lambda name: True)

    res = fes.ensure("NokidoEmbedTrigger", "stopped")
    assert res["success"] is False
    assert not res.get("deja_arrete")
