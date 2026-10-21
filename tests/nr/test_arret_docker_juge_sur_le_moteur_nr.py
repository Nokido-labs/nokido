"""NR -- l'arret gouverne de Docker se juge sur le MOTEUR, pas sur un conteneur arrete (2026-10-20).

Mesure du 20/10 : `nokido_ensure_service{docker, stopped}` a rendu success=True avec daemon_encore_up=True -- la regle
`ok = (encore is False) or bool(detail.get("stopped"))` comptait un conteneur arrete (crawl4ai) comme un arret reussi,
alors que le moteur repondait encore et que la VM WSL gardait 3,7 Go. REQUESTED n'est pas ACHIEVED. Et
`docker desktop stop` peut etre asynchrone : une sonde unique aussitot apres ne prouve rien.

Ce qui est garde : moteur toujours debout = echec (meme si des conteneurs sont arretes) ; moteur qui s'eteint pendant
le delai d'attente = succes ; sonde illisible = echec « effet NON verifie », jamais un succes par defaut.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _module(monkeypatch, reponses):
    spec = importlib.util.spec_from_file_location("ensure_docker_moteur_nr", RACINE / "tools" / "forge_ensure_service.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_resource_manager",
                        types.SimpleNamespace(get_active_intents=lambda: {}))
    monkeypatch.setitem(sys.modules, "forge_docker_keeper", types.SimpleNamespace(
        _release_docker=lambda: {"stopped": ["laforge-crawl4ai-1"], "engine": "stop demande (rc=0)"}))
    suite = iter(reponses)

    def sonde():
        r = next(suite, reponses[-1])
        if isinstance(r, Exception):
            raise r
        return r
    faux = types.SimpleNamespace(_docker_daemon_up=sonde)
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_searxng_keeper", faux)
    import nokido_agent.tools as paquet
    monkeypatch.setattr(paquet, "forge_searxng_keeper", faux, raising=False)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    return m


def test_moteur_toujours_debout_est_un_echec_meme_avec_un_conteneur_arrete(monkeypatch):
    r = _module(monkeypatch, [True])._stop_docker_gouverne(delai_s=6, pas_s=2)
    assert r["success"] is False, r
    assert r["detail"]["daemon_encore_up"] is True
    assert "moteur" in r["detail"].get("verdict", "") and "NON" in r["detail"].get("verdict", "")


def test_un_arret_asynchrone_constate_pendant_le_delai_est_un_succes(monkeypatch):
    r = _module(monkeypatch, [True, True, False])._stop_docker_gouverne(delai_s=10, pas_s=2)
    assert r["success"] is True, r
    assert r["detail"]["daemon_encore_up"] is False


def test_une_sonde_illisible_n_est_jamais_un_succes(monkeypatch):
    r = _module(monkeypatch, [RuntimeError("pipe docker illisible")])._stop_docker_gouverne(delai_s=4, pas_s=2)
    assert r["success"] is False, r
    assert "NON verifie" in r["detail"].get("sonde_daemon", "")
