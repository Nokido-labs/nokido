"""NR -- nokido_ensure_service{webhub, restarted} dit le VRAI (2026-10-28, job_f7a86c53).

Constat : la livraison 9518a0983 calculait `avant` au restart, ne mesurait jamais `apres`, et
rendait au client la sortie brute du superviseur. Quand le stop n'a pas eu d'effet, le start
repond « HTTP 200 {ok: true, already_running: NokidoWebHub} » -- un succes apparent sans
redemarrage.

Contrat garde ici : la reponse porte {avant, apres, etat, superviseur_brut}.
  - RESTARTED           si pid change OU restarts augmente (mesure apres) ;
  - ECHEC_REDEMARRAGE   si mesurable et ni pid ni restarts n'ont change ;
  - ILLISIBLE           si avant ou apres vaut None (jamais un verdict sur du vide).
La traversee est ENTIERE : ensure() tourne du debut a la fin ; seuls le superviseur, le statut
mesure, la sonde HTTP et le world-model sont simules.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
ETATS_MESURES = {"RESTARTED", "ECHEC_REDEMARRAGE", "ILLISIBLE"}


def _module(monkeypatch, etat_init, stop_effectif, illisible=False):
    spec = importlib.util.spec_from_file_location(
        "ensure_webhub_restart_nr", RACINE / "tools" / "forge_ensure_service.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    # Superviseur simule : etat vivant, mutable par stop/start.
    etat = dict(etat_init)

    def superviseur(action, name, timeout=90):
        if action == "stop" and stop_effectif:
            etat.update(status="stopped", pid=None)
        if action == "start":
            if etat["status"] == "running":
                return {"rc": 0, "out": 'HTTP 200 {"ok": true, "already_running": "NokidoWebHub"}',
                        "err": ""}
            etat.update(status="running", pid=etat_init["pid"] + 1, restarts=etat_init["restarts"] + 1)
            return {"rc": 0, "out": 'HTTP 200 {"ok": true, "starting": "NokidoWebHub"}', "err": ""}
        return {"rc": 0, "out": 'HTTP 200 {"ok": true}', "err": ""}

    # Sonde HTTP : ne sert pas avant le stop, puis sert apres le start.
    sonde = iter([False])
    monkeypatch.setattr(m, "_serving", lambda svc: next(sonde, True))
    monkeypatch.setattr(m, "_supervisor", superviseur)
    monkeypatch.setattr(m, "_statut_mesure", lambda name: None if illisible else dict(etat))
    monkeypatch.setattr(m, "_installe", lambda name: True)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_body_world_model",
                        types.SimpleNamespace(guard=lambda n, a: {"allowed": True, "impact": {}}))
    return m


VIVANT = {"pid": 4242, "restarts": 3, "status": "running"}


def test_stop_sans_effet_donne_echec_mesure(monkeypatch):
    m = _module(monkeypatch, VIVANT, stop_effectif=False)
    r = m.ensure("webhub", "restarted")
    assert r.get("etat") == "ECHEC_REDEMARRAGE", r
    assert r["success"] is False, r
    assert r["avant"]["pid"] == 4242 and r["apres"]["pid"] == 4242, r
    assert "superviseur_brut" in r, r


def test_redemarre_mais_ne_sert_pas_n_est_pas_un_succes(monkeypatch):
    """Revue d'integration (CLAUDE 28/10) : success ne dependait plus que du pid. Un service qui redemarre
    (pid change) mais ne SERT pas (vu sur embed) etait declare en succes : TRANSPORT != APPLICATIF."""
    m = _module(monkeypatch, VIVANT, stop_effectif=True)
    # _wait_serving simule : la vraie boucle attend son echeance en temps reel (sleep neutralise, pas l'horloge)
    monkeypatch.setattr(m, "_wait_serving", lambda svc, *a, **k: False)
    r = m.ensure("webhub", "restarted")
    assert r.get("etat") == "RESTARTED", r
    assert r.get("sert") is False, r
    assert r["success"] is False, r


def test_restart_effectif_donne_RESTARTED_avec_avant_apres(monkeypatch):
    m = _module(monkeypatch, VIVANT, stop_effectif=True)
    r = m.ensure("webhub", "restarted")
    assert r.get("etat") == "RESTARTED", r
    assert r["success"] is True, r
    assert r["avant"]["pid"] == 4242 and r["apres"]["pid"] == 4243, r
    assert r["apres"]["restarts"] == 4, r


def test_statut_illisible_donne_ILLISIBLE_jamais_un_verdict(monkeypatch):
    m = _module(monkeypatch, VIVANT, stop_effectif=True, illisible=True)
    r = m.ensure("webhub", "restarted")
    assert r.get("etat") == "ILLISIBLE", r
    assert r["success"] is False, r


def test_already_running_jamais_sans_etat_mesure(monkeypatch):
    m = _module(monkeypatch, VIVANT, stop_effectif=False)
    r = m.ensure("webhub", "restarted")
    assert "already_running" not in json.dumps(
        {k: v for k, v in r.items() if k != "superviseur_brut"}, ensure_ascii=False), r
    assert r.get("etat") in ETATS_MESURES, r
