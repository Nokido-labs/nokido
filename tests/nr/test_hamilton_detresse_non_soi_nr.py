# -*- coding: utf-8 -*-
"""NR — Test de regulation_hamilton_ram en detresse critique NON_SOI.

Contrat :
  1. Sous detresse critique (RAM libre < _CRITIQUE_LIBRE_GB ou palier critique=True) dont la cause
     est NON_SOI : le regulateur propose 'delester_auxiliaires' (action/proposition),
     motif 'detresse critique malgre NON_SOI'.
  2. Proposition seulement : aucune action reelle de kill (gestes vides, choisis vides).
  3. Hors detresse critique : NON_SOI conserve son comportement inchange (aucune proposition).
  4. Pression SOI : comportement inchange (delestage normal des DIFFERABLE).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
import forge_resource_manager as rm


def test_detresse_critique_non_soi_propose_delester_auxiliaires():
    """NON_SOI + RAM LIBRE < _CRITIQUE_LIBRE_GB (0.5 GB) -> propose delester_auxiliaires sans kill."""
    plan = {
        "verdict": "NON_SOI",
        "motif": "pression NON_SOI signalee",
        "delester": [],
        "auxiliaire_observe": [
            {"service": "NokidoTaskExecutorOpencodeGlm", "classe": "DIFFERABLE", "rss_mb": 450.0},
            {"service": "NokidoWatchAgent", "classe": "DIFFERABLE", "rss_mb": 120.0},
        ],
    }
    ram_pct = 96.0  # RAM elevee
    ram_total_gb = 10.0  # Libre = 0.4 GB < 0.5 GB (_CRITIQUE_LIBRE_GB)
    etat = {}
    maintenant = 1234567890.0

    result = rm.regulation_hamilton_ram(plan, ram_pct, ram_total_gb, etat, maintenant)

    assert result.get("action") == "delester_auxiliaires"
    assert result.get("proposition") == "delester_auxiliaires"
    assert "detresse critique malgre NON_SOI" in result["motif"]
    # Proposition seulement : aucun kill reel execute
    assert result["choisis"] == []
    assert result["gestes"] == {}
    assert "NokidoTaskExecutorOpencodeGlm" in result.get("auxiliaires", [])


def test_detresse_critique_flag_propose_delester_auxiliaires():
    """NON_SOI + critique=True -> propose delester_auxiliaires sans kill."""
    plan = {
        "verdict": "NON_SOI",
        "delester": [{"service": "NokidoWatchAgent", "rss_mb": 100.0}],
    }
    ram_pct = 85.0
    ram_total_gb = 16.0
    etat = {}
    maintenant = 1234567890.0

    result = rm.regulation_hamilton_ram(plan, ram_pct, ram_total_gb, etat, maintenant, critique=True)

    assert result.get("action") == "delester_auxiliaires"
    assert result.get("proposition") == "delester_auxiliaires"
    assert "detresse critique malgre NON_SOI" in result["motif"]
    assert result["choisis"] == []
    assert result["gestes"] == {}


def test_non_soi_hors_detresse_aucun_delestage():
    """NON_SOI hors detresse critique (RAM libre >= 0.5 GB, critique=False) -> comportement inchange."""
    plan = {
        "verdict": "NON_SOI",
        "motif": "pression NON_SOI : signalee, jamais delestee",
        "delester": [],
    }
    ram_pct = 85.0
    ram_total_gb = 16.0  # Libre = 2.4 GB >= 0.5 GB
    etat = {}
    maintenant = 1234567890.0

    result = rm.regulation_hamilton_ram(plan, ram_pct, ram_total_gb, etat, maintenant, critique=False)

    assert result.get("action") != "delester_auxiliaires"
    assert result.get("proposition") != "delester_auxiliaires"
    assert result["choisis"] == []
    assert result["gestes"] == {}
    assert "pression NON_SOI" in result["motif"]


def test_soi_pression_delestage_normal():
    """Verdict SOI sous pression -> delestage normal des DIFFERABLE."""
    plan = {
        "verdict": "SOI",
        "motif": "pression SOI",
        "delester": [
            {"service": "svc_gros", "classe": "DIFFERABLE", "rss_mb": 800.0},
            {"service": "svc_petit", "classe": "DIFFERABLE", "rss_mb": 300.0},
        ],
    }
    ram_pct = 85.0
    ram_total_gb = 16.0
    etat = {}
    maintenant = 1234567890.0

    result = rm.regulation_hamilton_ram(plan, ram_pct, ram_total_gb, etat, maintenant)

    assert "pression SOI" in result["motif"]
    assert len(result["choisis"]) > 0
    assert result.get("action") != "delester_auxiliaires"


def test_ram_sous_seuil_sommeil_aucun_geste():
    """RAM sous le seuil de sommeil -> rien a ceder."""
    plan = {
        "verdict": "NON_SOI",
        "delester": [],
    }
    ram_pct = 50.0  # < seuil (~80%)
    ram_total_gb = 16.0

    result = rm.regulation_hamilton_ram(plan, ram_pct, ram_total_gb)

    assert "rien de neuf a ceder" in result["motif"]
    assert result["choisis"] == []
    assert result["gestes"] == {}
    assert result.get("action") != "delester_auxiliaires"
