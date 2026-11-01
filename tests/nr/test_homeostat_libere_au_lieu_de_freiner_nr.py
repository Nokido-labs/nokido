# -*- coding: utf-8 -*-
"""NR homeostat : docker_wanted SEUL ne doit pas interdire toute eviction (25/10).

docker_wanted seul -> request_resources appele, Docker protege ; chains_active -> seulement run_reclaimers ;
aucun intent -> comportement d'avant (request_resources sans protection).
"""
import sys

import pytest

from nokido_agent.app import forge_resource_manager as R
from nokido_agent.app import forge_sandbox_exec as S


class _Bidon:
    pass


SNAP = {"ram_pct": 96.4, "ram_free_gb": 0.85, "ram_total_gb": 32.0, "top_procs": []}


@pytest.fixture
def cadre(monkeypatch):
    for m in ("win32api", "win32con", "win32event", "win32file", "win32process", "win32profile", "win32security"):
        monkeypatch.setitem(sys.modules, m, _Bidon())
    monkeypatch.setenv("LAFORGE_P1_THROTTLE", "1")
    monkeypatch.setenv("LAFORGE_P1_EVICT", "1")
    monkeypatch.setattr(S, "_ram_dementie", lambda snap: None)
    monkeypatch.setattr(R, "should_throttle", lambda *a, **k: True)
    monkeypatch.setattr(R, "get_snapshot", lambda *a, **k: dict(SNAP))
    appels = {"req": [], "rec": []}

    def _req(needed, allow_evict=False, deleguer=True, **kw):
        appels["req"].append(kw)
        return {"ok": False, "action": ["ollama_unload:x"], "missing_gb": 2.0}

    def _rec(target):
        appels["rec"].append(target)
        return {"ok": False, "action": ["noop"]}

    monkeypatch.setattr(R, "request_resources", _req)
    monkeypatch.setattr(R, "run_reclaimers", _rec)
    return appels


def _spawn():
    try:
        return S.spawn_as_sandbox("cmd /c exit 0", timeout=5)
    except Exception as e:  # noqa: BLE001
        return {"throttled": False, "err": e, "stderr": ""}


def test_docker_wanted_seul_libere_en_protegeant_docker(monkeypatch, cadre):
    monkeypatch.setattr(R, "get_active_intents", lambda: {"chains_active": False, "docker_wanted": True})
    r = _spawn()
    assert len(cadre["req"]) == 1
    assert cadre["req"][0].get("proteger_docker") is True
    assert r.get("throttled") is True
    assert "docker protege" in r["stderr"].lower()


def test_chains_active_reste_reclaimers_seuls(monkeypatch, cadre):
    monkeypatch.setattr(R, "get_active_intents", lambda: {"chains_active": True, "docker_wanted": True})
    r = _spawn()
    assert cadre["req"] == [] and len(cadre["rec"]) == 1
    assert "cognition active" in r["stderr"]


def test_aucun_intent_comportement_actuel(monkeypatch, cadre):
    monkeypatch.setattr(R, "get_active_intents", lambda: {"chains_active": False, "docker_wanted": False})
    _spawn()
    assert len(cadre["req"]) == 1
    assert not cadre["req"][0].get("proteger_docker")
    assert cadre["rec"] == []


def test_request_resources_accepte_proteger_docker():
    import inspect
    assert "proteger_docker" in inspect.signature(R.request_resources).parameters
