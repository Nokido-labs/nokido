# -*- coding: utf-8 -*-
"""NR — le pouls d'un serveur atteste qu'il SERT, pas qu'il existe.

`beat_daemon` impose de battre APRES un cycle reussi, jamais au demarrage : le pouls
doit attester du TRAVAIL. Un serveur HTTP n'a pas de cycle, il attend des requetes, et
les deux facons evidentes de lui donner un pouls sont fausses :

- battre a chaque requete recue -> un serveur SANS TRAFIC voit son pouls geler, et le
  superviseur lit une mort la ou il n'y a qu'un silence de l'utilisateur ;
- battre depuis une boucle qui ne verifie rien -> on atteste l'EXISTENCE du process. Le
  pouls d'un serveur dont la boucle est FIGEE continuerait, et couvrirait exactement la
  panne qu'on veut voir. C'est « SIGNAL != PREUVE DE VIE », paye le 2026-09-05 quand le
  pouls d'un orphelin rehabilitait son organe.

`demarrer_pouls_service_http` sonde donc le serveur sur sa propre URL et ne bat que s'il
REPOND. La MORSURE de ce fichier est `test_un_serveur_qui_ne_repond_pas_ne_bat_pas` :
c'est elle qui distingue ce pouls d'un `while True: beat()`.
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import forge_heartbeat as HB  # noqa: E402


def _port_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _Muet(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):  # silence le serveur de test
        pass


def _serveur(port):
    srv = HTTPServer(("127.0.0.1", port), _Muet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _battements(monkeypatch):
    """Capture les appels a beat_daemon SANS ecrire dans sandbox/."""
    vus = []
    monkeypatch.setattr(HB, "beat_daemon", lambda nom, **kw: vus.append((nom, kw)) or True)
    return vus


def _attendre(pred, limite_s=6.0):
    fin = time.time() + limite_s
    while time.time() < fin:
        if pred():
            return True
        time.sleep(0.15)
    return False


def test_un_serveur_qui_repond_fait_battre(monkeypatch):
    vus = _battements(monkeypatch)
    port = _port_libre()
    srv = _serveur(port)
    try:
        HB.demarrer_pouls_service_http("temoin_vivant",
                                       "http://127.0.0.1:%d/" % port, intervalle_s=5.0)
        assert _attendre(lambda: vus), "aucun battement alors que le serveur repond"
        nom, extra = vus[0]
        assert nom == "temoin_vivant"
        assert extra.get("statut") == 200, "le battement ne porte pas le statut observe"
    finally:
        srv.shutdown()


def test_un_serveur_qui_ne_repond_pas_ne_bat_pas(monkeypatch):
    """MORSURE — un `while True: beat()` rendrait ce test vert a tort.

    Rien n'ecoute sur ce port : si un battement apparait, c'est que le pouls atteste
    l'existence du process au lieu de sa capacite a servir.
    """
    vus = _battements(monkeypatch)
    port = _port_libre()  # personne n'ecoute
    HB.demarrer_pouls_service_http("temoin_mort",
                                   "http://127.0.0.1:%d/" % port, intervalle_s=5.0)
    time.sleep(2.0)
    assert not vus, (
        "le pouls a battu pour un serveur qui ne repond pas : il atteste l'existence "
        "du process, pas le fait qu'il serve"
    )


def test_le_fil_est_daemon_et_ne_retient_pas_le_porteur():
    """Un fil non-daemon empecherait l'arret du service qu'il surveille."""
    port = _port_libre()
    fil = HB.demarrer_pouls_service_http("temoin_fil",
                                         "http://127.0.0.1:%d/" % port, intervalle_s=5.0)
    assert isinstance(fil, threading.Thread)
    assert fil.daemon, "le fil de pouls retiendrait l'arret du porteur"


def test_l_intervalle_a_un_plancher():
    """Une valeur trop basse transformerait le pouls en charge sur son propre serveur."""
    import inspect
    src = inspect.getsource(HB.demarrer_pouls_service_http)
    assert "max(" in src, "aucun plancher sur l'intervalle de sonde"


def test_le_pouls_ne_leve_jamais(monkeypatch):
    """Un pouls qui casse son porteur serait pire que pas de pouls du tout."""
    def _explose(*a, **k):
        raise RuntimeError("temoin")
    monkeypatch.setattr(HB, "beat_daemon", _explose)
    port = _port_libre()
    srv = _serveur(port)
    try:
        fil = HB.demarrer_pouls_service_http("temoin_exception",
                                             "http://127.0.0.1:%d/" % port, intervalle_s=5.0)
        time.sleep(1.5)
        assert fil.is_alive(), "le fil de pouls est mort sur une exception de beat_daemon"
    finally:
        srv.shutdown()
