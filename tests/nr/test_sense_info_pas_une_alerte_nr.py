"""NR - le sens n'affiche pas une arrivee de CLI comme une alerte organe (5/11).

Mesure du 5/11 : `[sense] ⚠ 5 alerte(s) organe : cli_present | cli_present | ...` a chaque tour.
`forge_presence` persiste `cli_present` en severite `info`, consomme par la coagulation ; le
lecteur du sens les prenait pour des alertes. Filtrer a l'affichage seul serait un faux calme :
`unprocessed` lit les plus anciens d'abord, avec une limite, et douze `info` boucheraient la
fenetre devant une vraie panne. Seule la severite exacte `info` est ecartee : une valeur
inattendue reste visible (constitution, liste blanche).
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import claude_inbox_tick as T  # noqa: E402
from nokido_agent.app import forge_critical_events as CE  # noqa: E402


@pytest.fixture
def poser(monkeypatch, tmp_path):
    monkeypatch.setattr(CE, "DB_PATH", tmp_path / "critical_events.db")
    monkeypatch.setattr(CE, "_INITIALIZED", False)
    monkeypatch.setattr(T, "SENSE_STATE", tmp_path / "sense.json")
    monkeypatch.setattr(T, "_hub_health", lambda: {"up": True, "etat": "OK", "body": {}})
    monkeypatch.setattr(T, "_hub_pulse", lambda: {})
    CE._init_db()

    def _poser(kind: str, severity: str) -> None:
        c = sqlite3.connect(str(CE.DB_PATH))
        try:
            c.execute(
                "INSERT INTO forge_critical_events (ts, kind, severity, payload) VALUES (?, ?, ?, '{}')",
                (time.time(), kind, severity),
            )
            c.commit()
        finally:
            c.close()

    return _poser


def test_arrivee_de_cli_n_est_pas_une_alerte(poser):
    poser("cli_present", "info")
    assert "alerte(s) organe" not in str(T._sense())


def test_fenetre_bouchee_par_info_ne_cache_pas_une_panne(poser):
    for _ in range(12):
        poser("cli_present", "info")
    poser("panne_reelle", "warn")
    sortie = str(T._sense())
    assert "panne_reelle" in sortie
    assert "cli_present" not in sortie


def test_severite_inattendue_reste_visible(poser):
    poser("evenement_etrange", "bizarre")
    assert "evenement_etrange" in str(T._sense())


def test_les_consommateurs_voient_toujours_les_info(poser):
    poser("cli_present", "info")
    assert [e["kind"] for e in CE.unprocessed(10)] == ["cli_present"]
