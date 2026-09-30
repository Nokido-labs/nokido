"""Capacites portees par les services — la source qui manquait le 24-07.

Sans elle, l'eviction a endormi les trois piliers du RAG : `predict_impact` ne voit
que les dependances DECLAREES (ordre de demarrage) et le filtre process ne voit
qu'un nom d'executable. Ni l'un ni l'autre ne sait ce qu'un service SERT.
"""
from __future__ import annotations

import os
import sys

import pytest

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import forge_service_capabilities as sc  # noqa: E402


@pytest.mark.parametrize("service", [
    "NokidoLlamaEmbed",      # embedding
    "NokidoQdrantServer",    # dense_search
    "NokidoQdrantSidecar",   # dense_search
    "NokidoLlamaReranker",   # reranking
    "LaForgeMCP",            # hub
])
def test_les_organes_endormis_le_24_07_sont_desormais_critiques(service):
    """Les trois piliers du RAG (+ le hub) doivent etre reconnus intouchables."""
    assert sc.is_critical(service), f"{service} devrait etre critique"
    assert sc.why_critical(service), "un refus doit pouvoir s'expliquer"


def test_service_quelconque_nest_pas_critique():
    assert sc.is_critical("NokidoServiceQuelconque") is False
    assert sc.why_critical("NokidoServiceQuelconque") == ""


def test_la_declaration_prime_sur_le_repli(monkeypatch):
    """services.toml fait foi ; le repli n'est qu'un filet."""
    monkeypatch.setattr(sc, "_CACHE", {"NokidoLlamaEmbed": []})
    assert sc.is_critical("NokidoLlamaEmbed") is False


def test_capacite_declaree_non_critique(monkeypatch):
    monkeypatch.setattr(sc, "_CACHE", {"SvcX": ["telemetrie"]})
    assert sc.capabilities_of("SvcX") == ["telemetrie"]
    assert sc.is_critical("SvcX") is False


def test_audit_expose_ce_qui_repose_sur_le_repli():
    a = sc.audit()
    assert "encore_sur_repli" in a and "capacites_critiques" in a
    # Le repli doit etre visible : c'est une dette, pas un acquis.
    assert isinstance(a["encore_sur_repli"], list)


def test_eviction_saute_un_porteur_de_capacite_critique(monkeypatch):
    """Le branchement reel : un organe critique ne doit JAMAIS sortir candidat."""
    import psutil

    import forge_resource_manager as rm

    class _Mem:
        rss = 5 * 1024 ** 3

    class _P:
        info = {"pid": 42, "name": "llama-server.exe", "memory_info": _Mem()}

    import types
    pr = types.ModuleType("forge_port_reconcile")
    pr._supervisor_ports = lambda: {8099: ("NokidoLlamaEmbed", 42)}
    pr._is_descendant = lambda pid, anc, d=3: False
    monkeypatch.setitem(sys.modules, "forge_port_reconcile", pr)
    wm = types.ModuleType("forge_body_world_model")
    wm.predict_impact = lambda s, a: {"verdict": "safe"}   # le world-model dit OUI...
    monkeypatch.setitem(sys.modules, "forge_body_world_model", wm)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [_P()])
    monkeypatch.setenv("LAFORGE_EVICT_DYNAMIC", "1")

    # ...et pourtant l'embedder ne doit PAS etre candidat.
    assert rm._heavy_evictable_services() == []
