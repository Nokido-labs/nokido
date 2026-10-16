"""NR - le sens du hub distingue LENT (delai depasse) et ABSENT (connexion refusee) (15/10).

Mesure du 15/10 : le hook [sense] a crie « HUB :8766 NE REPOND PAS » quatre fois dans la nuit
pendant des elicitations de 120 s et des jobs pytest, alors que /health repondait 200 en 15 ms a
chaque verification ; le tour suivant annoncait « REVENU = restart » sans aucun redemarrage.
Une sonde de 0,6 s rendait deux etats pour trois : un delai n'est pas une panne. Le pouls
(forge_state) est le second observateur. Reseau, pouls et etat sont simules.
"""
from __future__ import annotations

import sys
import time
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import claude_inbox_tick as T  # noqa: E402


def _leve(exc):
    def urlopen(*_a, **_k):
        raise exc
    return urlopen


@pytest.fixture
def sens(monkeypatch, tmp_path):
    monkeypatch.setattr(T, "SENSE_STATE", tmp_path / "sense.json")
    pouls = {"ts": time.time()}
    monkeypatch.setattr(T, "_hub_pulse", lambda: dict(pouls))
    return pouls


@pytest.mark.parametrize("exc", [urllib.error.URLError(TimeoutError("timed out")), TimeoutError("read")])
def test_delai_depasse_rend_lent_pas_absent(monkeypatch, exc):
    monkeypatch.setattr(T.urllib.request, "urlopen", _leve(exc))
    h = T._hub_health()
    assert h["up"] is None and h["etat"] == "LENT"


def test_connexion_refusee_rend_absent(monkeypatch):
    monkeypatch.setattr(T.urllib.request, "urlopen", _leve(urllib.error.URLError(ConnectionRefusedError())))
    h = T._hub_health()
    assert h["up"] is False and h["etat"] == "INJOIGNABLE"


def test_lent_avec_pouls_frais_n_est_pas_une_panne_ni_un_restart(monkeypatch, sens):
    monkeypatch.setattr(T.urllib.request, "urlopen", _leve(urllib.error.URLError(TimeoutError())))
    m = T._sense() or ""
    assert "LENT" in m and "pas tombe" in m and "NE RÉPOND PAS" not in m
    # Le tour suivant, le hub repond : aucun faux « REVENU = restart ».
    monkeypatch.setattr(T, "_hub_health", lambda: {"up": True, "body": {}})
    assert "REVENU" not in (T._sense() or "")


def test_lent_avec_pouls_vieux_alerte_wedge(monkeypatch, sens):
    sens["ts"] = time.time() - 600
    monkeypatch.setattr(T.urllib.request, "urlopen", _leve(urllib.error.URLError(TimeoutError())))
    m = T._sense() or ""
    assert "wedge possible" in m


def test_pouls_non_date_se_replie_sur_le_battement_du_superviseur(monkeypatch, sens, tmp_path):
    # forge_state sans horodatage : le fichier hub.heartbeat (lu par le superviseur) tranche.
    monkeypatch.setattr(T, "_hub_pulse", lambda: {})
    (tmp_path / "sandbox").mkdir()
    (tmp_path / "sandbox" / "hub.heartbeat").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(T, "ROOT", tmp_path)
    monkeypatch.setattr(T.urllib.request, "urlopen", _leve(urllib.error.URLError(TimeoutError())))
    m = T._sense() or ""
    assert "pas tombe" in m and "illisible" not in m


def test_refus_reel_garde_l_alarme_puis_le_retour(monkeypatch, sens):
    monkeypatch.setattr(T.urllib.request, "urlopen", _leve(urllib.error.URLError(ConnectionRefusedError())))
    assert "NE RÉPOND PAS" in (T._sense() or "")
    monkeypatch.setattr(T, "_hub_health", lambda: {"up": True, "body": {}})
    assert "REVENU" in (T._sense() or "")
