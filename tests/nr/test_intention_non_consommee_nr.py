# -*- coding: utf-8 -*-
"""NR — intention NON CONSOMMEE (forge_llama_keeper._maj_inutilite).

Mesure 2026-08-19 : `llama.wanted` etait repose toutes les ~300 s pour un TTL de
900 s. Le drapeau ne perimait donc JAMAIS et protegeait un coder a
`active_conns=0` tenant 4,82 Go. Mesurer l'AGE DU DRAPEAU ne pouvait pas
detecter ca — seule la duree CONTINUE sans servir le demasque.

Tests HERMETIQUES : `_HB` est redirige vers tmp_path, le vrai heartbeat n'est
jamais touche.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

import forge_llama_keeper as K  # noqa: E402

CODER = [(4.8, 1234)]


@pytest.fixture(autouse=True)
def _isole(tmp_path, monkeypatch):
    """Heartbeat hors du working tree + compteur remis a zero entre les cas."""
    monkeypatch.setattr(K, "_HB", str(tmp_path / "llama_keeper.heartbeat"))
    monkeypatch.setattr(K, "_ZERO_CONNS_DEPUIS", 0.0)
    yield
    K._ZERO_CONNS_DEPUIS = 0.0


def test_qui_sert_ne_compte_pas():
    assert K._maj_inutilite(3, CODER) == 0.0
    assert K._ZERO_CONNS_DEPUIS == 0.0


def test_sans_coder_ne_compte_pas():
    assert K._maj_inutilite(0, []) == 0.0


def test_zero_connexion_demarre_le_compteur():
    d = K._maj_inutilite(0, CODER)
    assert d >= 0.0
    assert K._ZERO_CONNS_DEPUIS > 0.0


def test_la_duree_croit_tant_qu_on_ne_sert_pas(monkeypatch):
    faux = [1000.0]
    monkeypatch.setattr(K.time, "time", lambda: faux[0])
    K._maj_inutilite(0, CODER)
    faux[0] = 1300.0
    assert K._maj_inutilite(0, CODER) == pytest.approx(300.0)


def test_une_connexion_remet_le_compteur_a_zero(monkeypatch):
    faux = [1000.0]
    monkeypatch.setattr(K.time, "time", lambda: faux[0])
    K._maj_inutilite(0, CODER)
    faux[0] = 1500.0
    assert K._maj_inutilite(0, CODER) == pytest.approx(500.0)
    assert K._maj_inutilite(1, CODER) == 0.0        # quelqu'un s'en sert
    faux[0] = 1600.0
    assert K._maj_inutilite(0, CODER) == pytest.approx(0.0)  # reparti de zero


def test_le_compteur_survit_a_un_redemarrage(monkeypatch, tmp_path):
    """Sans reprise, un keeper qui redemarre rendrait l'intention menteuse
    protectrice a l'infini : le compteur doit survivre a son porteur."""
    hb = tmp_path / "llama_keeper.heartbeat"
    hb.write_text(json.dumps({"zero_conns_depuis": 1000.0}), encoding="utf-8")
    monkeypatch.setattr(K, "_HB", str(hb))
    monkeypatch.setattr(K.time, "time", lambda: 1700.0)
    assert K._maj_inutilite(0, CODER) == pytest.approx(700.0)


def test_heartbeat_illisible_repart_de_maintenant(monkeypatch, tmp_path):
    """Un antecedent illisible ne doit ni lever ni fabriquer une duree : on
    repart de maintenant (donc on PROTEGE), jamais on n'invente une inutilite."""
    hb = tmp_path / "llama_keeper.heartbeat"
    hb.write_text("{ceci n'est pas du json", encoding="utf-8")
    monkeypatch.setattr(K, "_HB", str(hb))
    monkeypatch.setattr(K.time, "time", lambda: 5000.0)
    assert K._maj_inutilite(0, CODER) == pytest.approx(0.0)


def test_seuil_par_defaut_laisse_le_delai_de_grace():
    """REGRESSION 2026-07-26 : un cerveau qu'on vient d'allumer est inactif PAR
    DEFINITION. Le seuil doit etre largement superieur au temps de chargement
    d'un modele (60-120 s), sinon on refauche les allumages a la naissance."""
    assert K._INUTILE_S >= 300.0
