"""NR 31/10 -- un daemon reveille apres delestage ne refait plus un cycle complet qu'il vient de faire.

Mesure 31/10 (journal du superviseur) : NokidoRSSWatcher mis en sommeil (POST /supervisor/sleep, RAM 96 %) puis reveille
3 min plus tard, a 09:21, 09:35, 09:55 -- et a CHAQUE reveil un cycle complet (reseau, ingestion, lecture du coffre)
alors que le precedent datait de 13 min pour un intervalle de 360 min. hebbian_linker et skill_curator idem (progres_ts
~09:55). Cause : forge_heartbeat.Cadence.__init__ pose `_du = True` (« le premier tour travaille ») sans relire le
dernier cycle REUSSI deja publie dans son battement (progres_ts / progres_ok). Un cycle echoue, lui, est retente.
"""
from __future__ import annotations

import json
import time

from nokido_agent.app import forge_heartbeat as HB


def _battement(tmp_path, nom, il_y_a_s, ok=True):
    (tmp_path / "sandbox").mkdir(exist_ok=True)
    (tmp_path / "sandbox" / ("%s.heartbeat" % nom)).write_text(
        json.dumps({"progres_ts": time.time() - il_y_a_s, "progres_ok": ok, "cycle_s": 21600.0}), encoding="utf-8")


def _cadence(monkeypatch, tmp_path, nom, **k):
    monkeypatch.setattr(HB, "_ROOT", tmp_path)
    monkeypatch.setattr(HB.Cadence, "battre", lambda self: True)       # aucun ecrit pendant le test
    monkeypatch.setattr(HB.Cadence, "_accorder", lambda self: None)
    return HB.Cadence(nom, cycle_s=21600, **k)


def test_cycle_reussi_recent_pas_de_cycle_au_reveil(monkeypatch, tmp_path):
    _battement(tmp_path, "rss_watcher", il_y_a_s=13 * 60)
    assert _cadence(monkeypatch, tmp_path, "rss_watcher").tour() is False


def test_cycle_ancien_le_cycle_est_du(monkeypatch, tmp_path):
    _battement(tmp_path, "rss_watcher", il_y_a_s=7 * 3600)
    assert _cadence(monkeypatch, tmp_path, "rss_watcher").tour() is True


def test_cycle_echoue_est_retente(monkeypatch, tmp_path):
    _battement(tmp_path, "rss_watcher", il_y_a_s=60, ok=False)
    assert _cadence(monkeypatch, tmp_path, "rss_watcher").tour() is True


def test_sans_battement_comportement_d_avant(monkeypatch, tmp_path):
    assert _cadence(monkeypatch, tmp_path, "inconnu").tour() is True


def test_reprise_desactivable(monkeypatch, tmp_path):
    _battement(tmp_path, "rss_watcher", il_y_a_s=60)
    assert _cadence(monkeypatch, tmp_path, "rss_watcher", reprendre=False).tour() is True


def test_le_cycle_redevient_du_a_son_echeance(monkeypatch, tmp_path):
    _battement(tmp_path, "rss_watcher", il_y_a_s=13 * 60)
    cad = _cadence(monkeypatch, tmp_path, "rss_watcher")
    assert cad.tour() is False
    cad._dernier_cycle_ts -= 21600  # le temps passe : l'echeance est atteinte
    assert cad.tour() is True
