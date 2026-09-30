"""Eviction identifiee par CAPACITE (et non par port/nom fige).

Mesure du 2026-07-24 : l'echelle rendait `noop` trois fois de suite alors que le
glouton etait un llama-server de 5.59 GB, invisible car `llamacpp_native_status`
ne connait que le port 8091.

Ces tests portent surtout sur les ABSTENTIONS : c'est du code qui arrete des
services, le cout d'evincer a tort depasse celui de refuser un spawn.
"""
from __future__ import annotations

import os
import sys
import types

import psutil
import pytest

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import forge_resource_manager as rm  # noqa: E402


class _Mem:
    def __init__(self, gb):
        self.rss = int(gb * (1024 ** 3))


class _Proc:
    def __init__(self, pid, name, gb):
        self.info = {"pid": pid, "name": name, "memory_info": _Mem(gb)}


def _wire(monkeypatch, procs, ports, verdicts, descendant=False):
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: list(procs))
    pr = types.ModuleType("forge_port_reconcile")
    pr._supervisor_ports = lambda: dict(ports)
    pr._is_descendant = lambda pid, anc, d=3: descendant
    monkeypatch.setitem(sys.modules, "forge_port_reconcile", pr)
    wm = types.ModuleType("forge_body_world_model")
    wm.predict_impact = lambda svc, act: {"verdict": verdicts.get(svc, "safe")}
    monkeypatch.setitem(sys.modules, "forge_body_world_model", wm)
    # Desarmee par defaut depuis le 24-07 : les tests l'arment explicitement.
    monkeypatch.setenv("LAFORGE_EVICT_DYNAMIC", "1")


def test_le_glouton_rattache_et_sûr_est_candidat(monkeypatch):
    _wire(monkeypatch,
          [_Proc(15860, "llama-server.exe", 5.59)],
          {8099: ("NokidoLlamaChat", 15860)},
          {})
    c = rm._heavy_evictable_services()
    assert len(c) == 1
    assert c[0]["service"] == "NokidoLlamaChat" and c[0]["ram_gb"] == pytest.approx(5.59, abs=0.01)


def test_service_non_sur_est_intouchable(monkeypatch):
    """Verdict != safe (essentiel ou dependants) -> jamais evince."""
    _wire(monkeypatch,
          [_Proc(15860, "llama-server.exe", 5.59)],
          {8099: ("NokidoLlamaEmbed", 15860)},
          {"NokidoLlamaEmbed": "dangerous"})
    assert rm._heavy_evictable_services() == []


def test_process_non_rattache_est_laisse_tranquille(monkeypatch):
    """Un gros process qu'on n'arrive pas a rattacher : doute -> abstention."""
    _wire(monkeypatch,
          [_Proc(99999, "llama-server.exe", 4.0)],
          {8099: ("NokidoAutre", 111)},
          {})
    assert rm._heavy_evictable_services() == []


def test_un_moteur_d_index_nest_jamais_evince(monkeypatch):
    """Cas REEL du 24-07 : qdrant juge `safe` (aucun dependant DECLARE) etait le seul
    candidat retenu, devant un llama-server six fois plus gourmand. L'endormir aurait
    casse la recherche dense. Un porteur d'ETAT n'est pas rechargeable a la demande."""
    _wire(monkeypatch,
          [_Proc(13156, "qdrant.exe", 1.2), _Proc(8612, "llama-server.exe", 4.82)],
          {6333: ("NokidoQdrantServer", 13156), 8091: ("NokidoLlamaNative", 8612)},
          {})
    c = rm._heavy_evictable_services()
    assert [x["name"] for x in c] == ["llama-server.exe"]


def test_les_bases_et_navigateurs_sont_hors_perimetre(monkeypatch):
    _wire(monkeypatch,
          [_Proc(1, "firefox.exe", 3.0), _Proc(2, "python.exe", 3.0), _Proc(3, "sqlite3.exe", 2.0)],
          {8001: ("SvcA", 1), 8002: ("SvcB", 2), 8003: ("SvcC", 3)},
          {})
    assert rm._heavy_evictable_services() == []


def test_registre_muet_nevince_rien(monkeypatch):
    """Sans registre, on ne DEVINE pas a qui appartient un process."""
    _wire(monkeypatch, [_Proc(15860, "llama-server.exe", 5.59)], {}, {})
    assert rm._heavy_evictable_services() == []


def test_world_model_absent_nevince_rien(monkeypatch):
    monkeypatch.setattr(psutil, "process_iter",
                        lambda attrs=None: [_Proc(15860, "llama-server.exe", 5.59)])
    pr = types.ModuleType("forge_port_reconcile")
    pr._supervisor_ports = lambda: {8099: ("NokidoLlamaChat", 15860)}
    pr._is_descendant = lambda pid, anc, d=3: False
    monkeypatch.setitem(sys.modules, "forge_port_reconcile", pr)
    monkeypatch.setitem(sys.modules, "forge_body_world_model", None)
    assert rm._heavy_evictable_services() == []


def test_kill_switch(monkeypatch):
    _wire(monkeypatch,
          [_Proc(15860, "llama-server.exe", 5.59)],
          {8099: ("NokidoLlamaChat", 15860)},
          {})
    monkeypatch.setenv("LAFORGE_EVICT_DYNAMIC", "0")
    assert rm._heavy_evictable_services() == []


def test_DESARMEE_par_defaut(monkeypatch):
    """Degat mesure 24-07 : cette selection a endormi Qdrant, l'embedder ET le
    reranker — les trois piliers du RAG. Sans variable, elle ne doit RIEN rendre."""
    _wire(monkeypatch,
          [_Proc(15860, "llama-server.exe", 5.59)],
          {8099: ("NokidoLlamaChat", 15860)},
          {})
    monkeypatch.delenv("LAFORGE_EVICT_DYNAMIC", raising=False)
    assert rm._heavy_evictable_services() == []


def test_les_petits_process_sont_ignores(monkeypatch):
    _wire(monkeypatch,
          [_Proc(15860, "llama-server.exe", 0.3)],
          {8099: ("NokidoLlamaChat", 15860)},
          {})
    assert rm._heavy_evictable_services(min_ram_gb=1.0) == []


def test_tri_du_plus_gourmand_au_moins(monkeypatch):
    _wire(monkeypatch,
          [_Proc(1, "llama-server.exe", 2.0), _Proc(2, "ollama.exe", 5.5),
           _Proc(3, "llama-server.exe", 3.1)],
          {8001: ("SvcA", 1), 8002: ("SvcB", 2), 8003: ("SvcC", 3)},
          {})
    assert [c["ram_gb"] for c in rm._heavy_evictable_services()] == [5.5, 3.1, 2.0]


def test_launcher_indirection_rattache_l_enfant(monkeypatch):
    """Le registre note parfois un LAUNCHER dont l'ENFANT tient le port."""
    _wire(monkeypatch,
          [_Proc(15860, "llama-server.exe", 5.59)],
          {8099: ("NokidoLlamaChat", 4242)},
          {},
          descendant=True)
    c = rm._heavy_evictable_services()
    assert len(c) == 1 and c[0]["service"] == "NokidoLlamaChat"
