"""Sampling interne : la POLITIQUE (local-first, garde budget, tracabilite)."""
from __future__ import annotations

import os
import sys

import pytest

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import forge_internal_sampling as isamp  # noqa: E402


@pytest.fixture(autouse=True)
def trace_isole(tmp_path, monkeypatch):
    monkeypatch.setattr(isamp, "_TRACE", tmp_path / "trace.jsonl")


def _router(monkeypatch, capture: dict, retour="reponse"):
    import types
    mod = types.ModuleType("forge_llm_router")

    def router_call(prompt, **kw):
        capture.update(kw)
        capture["prompt"] = prompt
        return retour

    mod.router_call = router_call
    monkeypatch.setitem(sys.modules, "forge_llm_router", mod)


def test_local_par_defaut(monkeypatch):
    """Un organe de fond ne brule pas du quota cloud a l'insu de tous."""
    cap = {}
    _router(monkeypatch, cap)
    assert isamp.sample("x", purpose="t") == "reponse"
    assert cap["force_local"] is True


def test_cloud_est_un_choix_explicite(monkeypatch):
    cap = {}
    _router(monkeypatch, cap)
    monkeypatch.setattr(isamp, "_budget_pressure", lambda: False)
    isamp.sample("x", purpose="t", allow_cloud=True)
    assert cap["force_local"] is False


def test_garde_budget_repasse_en_local(monkeypatch):
    """Cloud autorise mais budget sous pression -> local quand meme."""
    cap = {}
    _router(monkeypatch, cap)
    monkeypatch.setattr(isamp, "_budget_pressure", lambda: True)
    isamp.sample("x", purpose="t", allow_cloud=True)
    assert cap["force_local"] is True


def test_prompt_vide_ne_route_pas(monkeypatch):
    cap = {}
    _router(monkeypatch, cap)
    assert isamp.sample("   ", purpose="t") is None
    assert cap == {}


def test_router_en_erreur_rend_None_sans_lever(monkeypatch):
    """Un organe de fond ne meurt pas parce que le LLM est indisponible."""
    import types
    mod = types.ModuleType("forge_llm_router")

    def boom(prompt, **kw):
        raise RuntimeError("provider down")

    mod.router_call = boom
    monkeypatch.setitem(sys.modules, "forge_llm_router", mod)
    assert isamp.sample("x", purpose="t") is None


def test_reponse_vide_vaut_None(monkeypatch):
    """'' ne doit pas se lire comme une reponse."""
    cap = {}
    _router(monkeypatch, cap, retour="   ")
    assert isamp.sample("x", purpose="t") is None


def test_reponse_dict_supportee(monkeypatch):
    cap = {}
    _router(monkeypatch, cap, retour={"text": "depuis un dict"})
    assert isamp.sample("x", purpose="t") == "depuis un dict"


def test_tracabilite_par_purpose(monkeypatch):
    cap = {}
    _router(monkeypatch, cap)
    isamp.sample("x", purpose="digest_veille")
    u = isamp.usage()
    assert u and u[-1]["purpose"] == "digest_veille" and u[-1]["ok"] is True


def test_budget_pressure_muet_ne_bloque_pas(monkeypatch):
    """Capteur indisponible -> on ne bloque pas (le local reste le defaut)."""
    monkeypatch.setitem(sys.modules, "forge_endocrine", None)
    assert isamp._budget_pressure() is False
