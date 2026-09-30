# -*- coding: utf-8 -*-
"""NR — la regulation PESE la prothese Docker et peut la COUPER, sous gardes.

Defaut mesure le 2026-09-05 : `docker_status()` rendait `memory_used_mb: 0` en dur,
avec ce commentaire — « MemUsed is not exposed by `docker info` […] we leave 0 here ».
La regulation voyait donc la prothese a RAM NULLE : elle ne pouvait ni la peser ni
decider de la reprendre. Un zero par DEFAUT se lit « charge nulle » et ouvre le garde
en silence (meme famille que le snapshot a froid deja paye ailleurs).

Cote levier, `docker_pause_all()` etait le seul cable : il pause les CONTENEURS, or la
surface est ailleurs — 3 719 Mo mesures dont 2 844 Mo de `vmmemWSL`. Pauser rend donc
presque rien ; seule l'extinction du moteur rend la RAM.

Docker est une PROTHESE, pas un organe (cadrage owner) : l'eteindre n'abime rien.
Mais la couper en boucle est interdit — « lancer Docker OUI, le faire BOUCLER NON ».
D'ou les trois gardes testes ici.
"""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

rm = pytest.importorskip("forge_resource_manager")


class _Proc:
    def __init__(self, nom, rss):
        self.info = {"name": nom, "memory_info": types.SimpleNamespace(rss=rss)}


class _ProcIllisible:
    def __init__(self, nom):
        self.info = {"name": nom, "memory_info": None}


def _faux_psutil(procs):
    faux = types.ModuleType("psutil")
    faux.process_iter = lambda champs=None: iter(procs)
    return faux


MO = 1024 * 1024


def test_surface_mesuree_sans_poste_mutualise(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil",
                        _faux_psutil([_Proc("Docker Desktop.exe", 500 * MO),
                                      _Proc("dockerd.exe", 100 * MO)]))
    s = rm.docker_surface_ram()
    assert s["total_mb"] == 600
    assert s["partage_mb"] == 0
    assert s["attribution"] == "MESUREE"


def test_vmmem_rend_l_attribution_indeterminee(monkeypatch):
    """`vmmemWSL` porte toute distro WSL : sa part Docker n'est pas mesurable."""
    monkeypatch.setitem(sys.modules, "psutil",
                        _faux_psutil([_Proc("Docker Desktop.exe", 500 * MO),
                                      _Proc("vmmemWSL", 2800 * MO)]))
    s = rm.docker_surface_ram()
    assert s["total_mb"] == 3300
    assert s["partage_mb"] == 2800
    assert s["propre_mb"] == 500
    assert s["attribution"] == "INDETERMINE", \
        "un total dont 85 % est mutualise ne doit pas etre presente comme acquis"


def test_processus_illisible_est_compte_pas_efface(monkeypatch):
    """Trois etats : un refus de lecture ne disparait pas dans un total 'complet'."""
    monkeypatch.setitem(sys.modules, "psutil",
                        _faux_psutil([_Proc("dockerd.exe", 100 * MO),
                                      _ProcIllisible("Docker Desktop.exe")]))
    s = rm.docker_surface_ram()
    assert s["illisibles"] == 1
    assert s["total_mb"] == 100


def test_aucun_processus_lisible_rend_illisible_pas_zero(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil",
                        _faux_psutil([_ProcIllisible("dockerd.exe")]))
    s = rm.docker_surface_ram()
    assert s["attribution"] == "ILLISIBLE", "0 mesure ne vaut pas 0 consomme"


def _sans_coupure_reelle(monkeypatch):
    """Neutralise l'effecteur : aucun test ne doit eteindre Docker pour de vrai."""
    faux = types.ModuleType("forge_docker_agent")
    faux.release_daemon = lambda: {"ok": True, "simule": True}
    monkeypatch.setitem(sys.modules, "forge_docker_agent", faux)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_docker_agent", faux)
    monkeypatch.setattr(rm, "_LAST_DOCKER_RELEASE_TS", 0.0, raising=False)


def test_garde_gain_insuffisant(monkeypatch):
    _sans_coupure_reelle(monkeypatch)
    monkeypatch.setattr(rm, "docker_surface_ram",
                        lambda: {"total_mb": 100, "partage_mb": 0, "propre_mb": 100,
                                 "attribution": "MESUREE", "detail": {},
                                 "illisibles": 0})
    v = rm.docker_release_prothese()
    assert v["fait"] is False and "gain insuffisant" in v["raison"]


def test_garde_intention_interdit_la_coupure(monkeypatch):
    _sans_coupure_reelle(monkeypatch)
    monkeypatch.setattr(rm, "docker_surface_ram",
                        lambda: {"total_mb": 3000, "partage_mb": 0, "propre_mb": 3000,
                                 "attribution": "MESUREE", "detail": {},
                                 "illisibles": 0})
    monkeypatch.setattr(rm, "get_active_intents",
                        lambda: {"docker_wanted": True, "chains_active": 0})
    v = rm.docker_release_prothese()
    assert v["fait"] is False and "demande par la cognition" in v["raison"]


def test_garde_surface_illisible_sabstient(monkeypatch):
    _sans_coupure_reelle(monkeypatch)
    monkeypatch.setattr(rm, "docker_surface_ram",
                        lambda: {"total_mb": 0, "attribution": "ILLISIBLE",
                                 "detail": {}, "illisibles": 3})
    v = rm.docker_release_prothese()
    assert v["fait"] is False and "illisible" in v["raison"]


def test_refractaire_interdit_la_dent_de_scie(monkeypatch):
    """Deuxieme coupure d'affilee REFUSEE : c'est la boucle que l'owner interdit."""
    _sans_coupure_reelle(monkeypatch)
    monkeypatch.setattr(rm, "docker_surface_ram",
                        lambda: {"total_mb": 3000, "partage_mb": 0, "propre_mb": 3000,
                                 "attribution": "MESUREE", "detail": {},
                                 "illisibles": 0})
    monkeypatch.setattr(rm, "get_active_intents",
                        lambda: {"docker_wanted": False, "chains_active": 0})
    monkeypatch.setattr(rm, "_audit_lifecycle", lambda *a, **k: None)
    premier = rm.docker_release_prothese()
    assert premier["fait"] is True
    second = rm.docker_release_prothese()
    assert second["fait"] is False and "refractaire" in second["raison"]
