"""Fusion multi-capteurs : c'est le DESACCORD qui porte l'information."""
from __future__ import annotations

import os
import sys
import time

import pytest

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import forge_sensor_fusion_probe as sf  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetique(monkeypatch):
    """Ces tests sont anterieurs a `_fleet` (superviseur interroge en HTTP), a
    `_declared_services` (services.toml) et a `_pid_alive` (OS). Non bouchonnes, ils
    lisaient la MACHINE : mesure 2026-09-24, 5 echecs identiques avant et apres un
    correctif sans rapport (« fantome » pour le pid 42, services declares reels ajoutes
    a probe_all). Un test de verdict ne doit dependre que de ses capteurs simules."""
    monkeypatch.setattr(sf, "_fleet", lambda: {})
    monkeypatch.setattr(sf, "_declared_services", lambda: {})
    monkeypatch.setattr(sf, "_pid_alive", lambda pid: True if pid else None)


def _wire(monkeypatch, registry, listens, hb_age):
    monkeypatch.setattr(sf, "_registry", lambda: registry)
    monkeypatch.setattr(sf, "_port_listens", lambda p, timeout=1.5: listens)
    monkeypatch.setattr(sf, "_heartbeat_age", lambda s: hb_age)


def test_sain(monkeypatch):
    _wire(monkeypatch, {6333: ("Svc", 42)}, True, 10.0)
    r = sf.probe("Svc")
    assert r["verdict"] == "sain" and r["consensus"] is True


def test_le_cas_reel_qdrant(monkeypatch):
    """24-07 : registre stopped (pid=None) alors que le port 6333 servait."""
    _wire(monkeypatch, {}, True, None)
    r = sf.probe("NokidoQdrantServer", port=6333)
    assert r["verdict"] == "vivant_non_revendique"
    assert r["consensus"] is False
    assert any("non revendique" in d for d in r["desaccords"])


def test_revendique_mais_sourd(monkeypatch):
    """Liveness sans readiness : le registre y croit, le port ne repond pas."""
    _wire(monkeypatch, {8099: ("Svc", 7)}, False, 10.0)
    r = sf.probe("Svc")
    assert r["verdict"] == "revendique_mais_sourd"
    assert any("sourd" in d for d in r["desaccords"])


def test_arrete_est_un_consensus(monkeypatch):
    _wire(monkeypatch, {}, False, None)
    r = sf.probe("Svc", port=1234)
    assert r["verdict"] == "arrete" and r["consensus"] is True


def test_sonde_impossible_ne_dit_jamais_sain(monkeypatch):
    """Ne pas pouvoir regarder n'est pas une bonne nouvelle."""
    _wire(monkeypatch, {}, None, None)
    r = sf.probe("Svc", port=9999)
    assert r["verdict"] == "indeterminable"


def test_heartbeat_gele_sur_service_vivant(monkeypatch):
    """Capteur gele, pas service mort : la nuance doit apparaitre."""
    _wire(monkeypatch, {6333: ("Svc", 42)}, True, 5000.0)
    r = sf.probe("Svc")
    assert r["verdict"] == "sain"          # il repond vraiment
    assert any("heartbeat" in d for d in r["desaccords"])  # mais on le SIGNALE
    assert r["consensus"] is False


def test_service_sans_heartbeat_declare_nest_pas_gele(monkeypatch):
    """Mesure 24-07 : NokidoWebHub ne DECLARE aucun heartbeat, et la recherche par
    convention de nom lui attribuait un fichier orphelin de 20,6 jours -> faux
    « capteur gele ». Sans declaration, on ne reproche rien."""
    monkeypatch.setattr(sf, "_declared_heartbeats", lambda: {})
    monkeypatch.setattr(sf, "_registry", lambda: {7400: ("NokidoWebHub", 5)})
    monkeypatch.setattr(sf, "_port_listens", lambda p, timeout=1.5: True)
    r = sf.probe("NokidoWebHub")
    assert r["verdict"] == "sain"
    assert r["desaccords"] == [] and r["consensus"] is True
    assert r["capteurs"]["heartbeat"]["age_s"] is None


def test_heartbeat_declare_et_gele_est_signale(monkeypatch, tmp_path):
    """A l'inverse : un service qui PROMET un heartbeat et ne bat plus doit sonner."""
    hb = tmp_path / "svc.heartbeat"
    hb.write_text("{}", encoding="utf-8")
    os.utime(hb, (time.time() - 5000, time.time() - 5000))
    monkeypatch.setattr(sf, "ROOT", tmp_path)
    monkeypatch.setattr(sf, "_declared_heartbeats", lambda: {"Svc": "svc.heartbeat"})
    monkeypatch.setattr(sf, "_registry", lambda: {1234: ("Svc", 9)})
    monkeypatch.setattr(sf, "_port_listens", lambda p, timeout=1.5: True)
    r = sf.probe("Svc")
    assert any("heartbeat" in d for d in r["desaccords"])


def test_sans_port_connu_reste_prudent(monkeypatch):
    """Sans port ni pouls : on ne sait pas. Avec un pouls frais mais sans revendication,
    l'organe temoigne de lui-meme (branche voulue du 26-07 : 34 daemons sans port sortaient
    « indeterminable » alors qu'ils battaient) -- et ce n'est toujours PAS « sain »."""
    _wire(monkeypatch, {}, None, None)
    assert sf.probe("SvcSansPort")["verdict"] == "indeterminable"
    _wire(monkeypatch, {}, None, 10.0)
    r = sf.probe("SvcSansPort")
    assert r["verdict"] == "vivant_par_heartbeat"


def test_probe_all_couvre_le_registre(monkeypatch):
    monkeypatch.setattr(sf, "_registry", lambda: {1: ("A", 1), 2: ("B", 2)})
    monkeypatch.setattr(sf, "_port_listens", lambda p, timeout=1.5: True)
    monkeypatch.setattr(sf, "_heartbeat_age", lambda s: 5.0)
    assert sorted(r["service"] for r in sf.probe_all()) == ["A", "B"]
