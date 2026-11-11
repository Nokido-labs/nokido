# -*- coding: utf-8 -*-
"""NR (owner 3/11 « sur le meme modele que docker : s'il ne porte pas d'intention tu le coupes ») : carcasse Docker.

Mesure du 3/11 18h41-18h55 : moteur Docker ETEINT (docker info DOWN a chaque tick), aucune reclamation, mais Docker
Desktop + sa VM WSL vivants (~5,5 Go : RAM 87,6 % -> 64 % a leur arret ; le vidage de qdrant a 18h49 n'avait rien rendu).
Le keeper ne relachait QUE moteur repondant ; moteur eteint + non voulu = « down par design », surveillance seule ->
la carcasse restait indefiniment, et la garde RAM refusait tout job. Desormais : processus Docker presents, sans
intention, au-dela d'une grace -> relache ; une chaine de veille active ou une intention illisible interdisent (fail-closed).
"""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_docker_keeper as K  # noqa: E402


@pytest.fixture
def keeper(monkeypatch):
    etat = {"voulu": False, "procs": True, "chaines": False}
    relaches = []
    monkeypatch.setattr(K, "_STATE", dict({k: v for k, v in K._STATE.items() if k != "carcasse_depuis"},
                                          last_release_ts=-1e9))
    monkeypatch.setattr(K, "RELEASE_ENABLED", True)
    monkeypatch.setattr(K, "_docker_wanted", lambda: etat["voulu"])
    monkeypatch.setattr(K, "_docker_procs_present", lambda: etat["procs"])
    monkeypatch.setattr(K, "_release_docker", lambda: relaches.append(1) or {"stop": "ok"})
    monkeypatch.setattr(K, "_audit", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_resource_manager",
                        types.SimpleNamespace(get_active_intents=lambda: {"chains_active": etat["chaines"]}))
    return etat, relaches


def test_carcasse_sans_intention_coupee_apres_la_grace(keeper):
    etat, relaches = keeper
    assert K._tick_carcasse(1000.0) is None and relaches == []           # premier constat : grace qui commence
    assert K._tick_carcasse(1000.0 + K.CARCASSE_GRACE_S - 1) is None and relaches == []
    assert K._tick_carcasse(1000.0 + K.CARCASSE_GRACE_S) is not None and relaches == [1]


def test_une_intention_interdit_la_coupure(keeper):
    etat, relaches = keeper
    etat["voulu"] = True
    for t in (0.0, K.CARCASSE_GRACE_S * 3):
        assert K._tick_carcasse(t) is None
    assert relaches == []


def test_sans_processus_docker_rien_a_couper_et_la_grace_repart(keeper):
    etat, relaches = keeper
    K._tick_carcasse(0.0)
    etat["procs"] = False
    assert K._tick_carcasse(K.CARCASSE_GRACE_S) is None
    etat["procs"] = True
    assert K._tick_carcasse(K.CARCASSE_GRACE_S + 1) is None and relaches == []   # nouvelle carcasse = nouvelle grace


def test_une_chaine_de_veille_active_interdit_la_coupure(keeper):
    etat, relaches = keeper
    etat["chaines"] = True
    K._tick_carcasse(0.0)
    assert K._tick_carcasse(K.CARCASSE_GRACE_S * 2) is None and relaches == []


def test_refractaire_pas_de_stop_repete(keeper, monkeypatch):
    etat, relaches = keeper
    monkeypatch.setattr(K, "_RELEASE_REFRACTORY_S", K.CARCASSE_GRACE_S * 10)
    K._tick_carcasse(0.0)
    assert K._tick_carcasse(K.CARCASSE_GRACE_S) is not None and relaches == [1]
    t = K.CARCASSE_GRACE_S + 1
    K._tick_carcasse(t)                                      # Desktop survit au stop : nouvelle grace...
    assert K._tick_carcasse(t + K.CARCASSE_GRACE_S) is None and relaches == [1]   # ...mais refractaire : pas de 2e stop


def test_intention_illisible_on_ne_coupe_pas(keeper, monkeypatch):
    etat, relaches = keeper

    def _casse():
        raise RuntimeError("base d'intentions illisible")
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_resource_manager",
                        types.SimpleNamespace(get_active_intents=_casse))
    K._tick_carcasse(0.0)
    assert K._tick_carcasse(K.CARCASSE_GRACE_S * 2) is None and relaches == []
