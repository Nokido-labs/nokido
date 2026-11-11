# -*- coding: utf-8 -*-
"""NR (owner 3/11, debat 2 Claude x AGY, docs/debats/SYNTHESE_DEBATS_SOIF_AUTOREGULATION_20261103.md) : boucles fermees.

Mesure 3/11 : la garde d'admission refusait tout a 87 % ; son effecteur (request_resources) ne connait que les modeles
et a rendu 0 Go pendant qu'une carcasse Docker/WSL sans intention tenait ~5,5 Go. Le vidage du working set de qdrant
« reussissait » sans rien rendre, et recommencait a chaque fin de refractaire. Invariants :
1. un refus d'admission sans gain suffisant appelle l'effecteur de SUBSTRAT (en arriere-plan : jamais geler le hub) ;
2. le substrat n'est relache que SANS intention, sans chaine active, intentions lisibles ; refractaire respecte ;
3. un effecteur MESURE ce qu'il rend ; une voie sterile allonge son refractaire, une voie feconde le remet a zero.
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
import forge_lane_admission as LA  # noqa: E402


# --- 1. admission : refus sans gain -> effecteur de substrat ---------------------------------------------------------
def _admission(monkeypatch, dispo_avant, dispo_apres):
    vals = iter([dispo_avant, dispo_apres])
    monkeypatch.setattr(LA, "_ram_dispo_go", lambda: next(vals, dispo_apres))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_resource_manager",
                        types.SimpleNamespace(request_resources=lambda **k: {"evicted": []}))
    appels = []
    monkeypatch.setattr(LA, "_relacher_substrat_async", lambda: appels.append(1) or {"substrat": "relache_demandee"})
    return appels


def test_refus_sans_gain_appelle_l_effecteur_de_substrat(monkeypatch):
    appels = _admission(monkeypatch, 2.9, 2.9)
    out = LA._try_reserve(4.0)
    assert appels == [1] and out["gain_mesure_go"] == 0.0 and out["substrat"] == "relache_demandee", out


def test_assez_de_ram_apres_eviction_pas_de_substrat(monkeypatch):
    appels = _admission(monkeypatch, 2.9, 4.5)
    out = LA._try_reserve(4.0)
    assert appels == [] and out["gain_mesure_go"] == pytest.approx(1.6)


# --- 2. substrat : seulement sans intention ----------------------------------------------------------------------
@pytest.fixture
def keeper(monkeypatch, tmp_path):
    etat = {"voulu": False, "procs": True, "chaines": 0, "illisible": False}
    relaches = []
    # 3/11 : le refractaire est PARTAGE sur disque (test_refractaire_substrat_partage_nr) -- jamais le vrai sandbox/
    if hasattr(K, "_FICHIER_SUBSTRAT"):
        monkeypatch.setattr(K, "_FICHIER_SUBSTRAT", tmp_path / "docker.substrat_release.json")
    monkeypatch.setattr(K, "_STATE", dict({k: v for k, v in K._STATE.items()}, last_release_ts=-1e9))
    monkeypatch.setattr(K, "RELEASE_ENABLED", True)
    monkeypatch.setattr(K, "_docker_wanted", lambda: etat["voulu"])
    monkeypatch.setattr(K, "_docker_procs_present", lambda: etat["procs"])
    monkeypatch.setattr(K, "_release_docker", lambda: relaches.append(1) or {"engine": "stop demande (rc=0)"})
    monkeypatch.setattr(K, "_audit", lambda *a, **k: None)

    def _intents():
        if etat["illisible"]:
            raise RuntimeError("illisible")
        return {"chains_active": etat["chaines"]}
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_resource_manager",
                        types.SimpleNamespace(get_active_intents=_intents))
    return etat, relaches


def test_substrat_sans_intention_relache_sans_grace(keeper):
    etat, relaches = keeper
    r = K.relacher_substrat_sans_intention(1000.0)
    assert r["relache"] is True and relaches == [1]


@pytest.mark.parametrize("cle, valeur, motif", [("voulu", True, "intention"), ("procs", False, "absent"),
                                                ("chaines", 2, "chaine"), ("illisible", True, "illisible")])
def test_substrat_jamais_relache_sous_intention(keeper, cle, valeur, motif):
    etat, relaches = keeper
    etat[cle] = valeur
    r = K.relacher_substrat_sans_intention(1000.0)
    assert r["relache"] is False and motif in r["motif"] and relaches == []


def test_substrat_refractaire(keeper, monkeypatch):
    etat, relaches = keeper
    monkeypatch.setattr(K, "_RELEASE_REFRACTORY_S", 600.0)
    K.relacher_substrat_sans_intention(1000.0)
    r = K.relacher_substrat_sans_intention(1100.0)
    assert r["relache"] is False and "refractaire" in r["motif"] and relaches == [1]


# --- 3. effecteur qui mesure son gain (qdrant) ---------------------------------------------------------------------
def test_vidage_sterile_allonge_le_refractaire(monkeypatch):
    base = K._QDRANT_REFRACTAIRE_S
    assert K.decider_vidage_qdrant(90.0, 6.0, 0.2, 0.0, base + 1, sterile=0)[0] is True
    assert K.decider_vidage_qdrant(90.0, 6.0, 0.2, 0.0, base + 1, sterile=2)[0] is False   # 4x la base
    assert K.decider_vidage_qdrant(90.0, 6.0, 0.2, 0.0, 4 * base + 1, sterile=2)[0] is True


def _vidage(monkeypatch, avant, apres):
    vals = iter([avant, apres])
    monkeypatch.setattr(K, "_ram_dispo_go", lambda: next(vals, apres))
    monkeypatch.setattr(K, "mesurer_qdrant", lambda: (90.0, 6.0, 0.2, 1234))
    monkeypatch.setattr(K, "_vider_ws_processus", lambda pid: (True, "EmptyWorkingSet=True"))
    monkeypatch.setattr(K, "_audit", lambda *a, **k: None)
    monkeypatch.setattr(K, "_dernier_vidage_qdrant", None)
    monkeypatch.setattr(K, "_qdrant_sterile", 0)


def test_vidage_sans_gain_compte_sterile(monkeypatch):
    _vidage(monkeypatch, 3.0, 3.05)
    r = K._tick_vidage_qdrant(1e6, _attendre=lambda s: None)
    assert r["gain_go"] == pytest.approx(0.05) and K._qdrant_sterile == 1


def test_vidage_fecond_remet_a_zero(monkeypatch):
    _vidage(monkeypatch, 3.0, 5.0)
    monkeypatch.setattr(K, "_qdrant_sterile", 3)
    K._tick_vidage_qdrant(1e6, _attendre=lambda s: None)
    assert K._qdrant_sterile == 0
