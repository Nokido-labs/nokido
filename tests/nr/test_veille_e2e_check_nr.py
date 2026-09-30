# -*- coding: utf-8 -*-
"""NR — le controle E2E de la veille refuse la lecture binaire up/down.

Ce que ce garde protege, c'est la CAPACITE DE DIAGNOSTIC, pas la sante de la chaine :
la chaine traverse une PROTHESE (Docker + `searxng-laforge` + `laforge-crawl4ai`), et
une prothese absente est un etat NOMINAL en on-demand, jamais une maladie. Ce qui
serait grave, c'est un controle qui rende « tout va bien » quand il n'a rien pu voir.

Trois proprietes d'EFFET, chacune payee dans la session du 2026-09-05 :

1. un pouls de keeper PERIME ne vaut pas un verdict — il decrit un passe, pas le
   present (le pouls de `docker_keeper` est reste fige 4 h pendant que le service
   mourait a chaque demarrage) ;
2. « moteur debout mais AUCUN port joignable » designe le COMPTE, pas les services :
   un compte sans acces loopback rend « injoignable » exactement comme un service
   mort, et cette confusion a deja coute un timeout muet de 120 s ;
3. un service qui repond 200 sans servir un seul resultat n'est pas OK — c'est la
   distinction TRANSPORT / APPLICATIF / CAPACITE de la constitution semantique.

Hermetique : aucun reseau, aucun Docker, aucune lecture de la base.
"""
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

e2e = pytest.importorskip("forge_veille_e2e_check")


def _pouls(tmp_path, contenu: dict, age_s: float = 0.0) -> Path:
    f = tmp_path / "docker_keeper.heartbeat"
    f.write_text(json.dumps(contenu), encoding="utf-8")
    if age_s:
        import os
        os.utime(f, (time.time() - age_s, time.time() - age_s))
    return f


def test_pouls_perime_ne_conclut_pas(tmp_path, monkeypatch):
    """Un avis vieux de deux heures ne dit rien du present."""
    f = _pouls(tmp_path, {"health": "ok", "stats": {"daemon_up": True}}, age_s=7200)
    monkeypatch.setattr(e2e, "HB_KEEPER", f)
    r = e2e.etage_prothese()
    assert r["etat"] == "INDETERMINE", "un pouls perime a ete promu en preuve"
    assert "PERIME" in r["raison"]


def test_pouls_absent_est_indetermine(tmp_path, monkeypatch):
    monkeypatch.setattr(e2e, "HB_KEEPER", tmp_path / "rien.heartbeat")
    assert e2e.etage_prothese()["etat"] == "INDETERMINE"


def test_prothese_debout_est_ok(tmp_path, monkeypatch):
    f = _pouls(tmp_path, {"health": "ok", "stats": {"daemon_up": True}})
    monkeypatch.setattr(e2e, "HB_KEEPER", f)
    assert e2e.etage_prothese()["etat"] == "OK"


def test_prothese_a_terre_est_ko_avec_sa_raison(tmp_path, monkeypatch):
    f = _pouls(tmp_path, {"health": "degraded",
                          "stats": {"daemon_up": False, "error": "npipe absent",
                                    "consecutive_failures": 3}})
    monkeypatch.setattr(e2e, "HB_KEEPER", f)
    r = e2e.etage_prothese()
    assert r["etat"] == "KO"
    assert "npipe" in r["raison"], "un KO sans raison se lit comme une panne opaque"


def test_capacite_repond_mais_ne_sert_rien(tmp_path):
    """200 + zero resultat = KO. Repondre n'est pas servir."""
    r = e2e.etage_capacite_searxng(json.dumps({"results": [],
                                               "unresponsive_engines": ["a", "b"]}))
    assert r["etat"] == "KO"
    assert r["resultats"] == 0 and r["moteurs_ko"] == 2


def test_capacite_degradee_nest_ni_ok_ni_ko(tmp_path):
    r = e2e.etage_capacite_searxng(json.dumps({"results": [1, 2],
                                               "unresponsive_engines": ["x"]}))
    assert r["etat"] == "DEGRADE", "un moteur muet ne doit pas passer pour OK"


def test_reponse_non_json_est_indeterminee():
    assert e2e.etage_capacite_searxng("<html>")["etat"] == "INDETERMINE"


def test_moteur_debout_et_ports_muets_accuse_le_compte(tmp_path, monkeypatch):
    """Le cas qui protege d'accuser un service qu'on ne peut pas voir."""
    f = _pouls(tmp_path, {"health": "ok", "stats": {"daemon_up": True}})
    monkeypatch.setattr(e2e, "HB_KEEPER", f)
    monkeypatch.setattr(e2e, "_port", lambda *a, **k: False)
    monkeypatch.setattr(e2e, "etage_chaine", lambda: {"etat": "OK"})
    code = e2e.main()
    assert code == 1
    # `main` imprime le rapport : on verifie la propriete via les etages directement.
    r = {"prothese": e2e.etage_prothese(),
         "searxng": e2e.etage_service("s", "http://127.0.0.1:8080", 8080, "/"),
         "crawl4ai": e2e.etage_service("c", "http://127.0.0.1:11235", 11235, "/")}
    assert r["prothese"]["etat"] == "OK"
    assert r["searxng"]["etat"] == "KO" and r["crawl4ai"]["etat"] == "KO"
    assert "loopback" in r["searxng"]["raison"], \
        "le verdict doit nommer l'hypothese COMPTE, pas accuser le service seul"


def test_sonde_de_port_est_deleguee():
    """Anti-dup : la primitive de sonde vit dans `forge_ports`, pas ici."""
    src = (ROOT / "tools" / "forge_veille_e2e_check.py").read_text(
        encoding="utf-8", errors="replace")
    assert "from nokido_agent.tools.forge_ports import probe" in src
