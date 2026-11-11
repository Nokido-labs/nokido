# -*- coding: utf-8 -*-
"""NR owner 4/11 : gpu_pct est lu par des gardes (forge_sandbox_exec, nokido_hub). Deux defauts mesures.

1. La sonde lancait PowerShell avec un plafond de 2 s (gpu_sample_ms 2019,7 publie, 3 None sur 3 en job) et ne voyait que le
   moteur 3D : une charge compute etait invisible.
2. Sur echec, l'ancienne valeur etait republiee comme une mesure. UNKNOWN n'est pas une valeur : on publie None.
"""
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "app")]
from nokido_agent.app import forge_resource_manager as RM  # noqa: E402
from nokido_agent.app import forge_vitals_channels as VC  # noqa: E402


def test_la_sonde_ne_lance_plus_de_powershell(monkeypatch):
    def refus(*_a, **_k):
        raise AssertionError("un processus a ete lance")
    monkeypatch.setattr(subprocess, "run", refus)
    monkeypatch.setattr(VC, "lire_gpu_pct", lambda: 12.5)
    assert RM._sample_gpu_win32() == 12.5


def test_une_lecture_impossible_rend_none(monkeypatch):
    monkeypatch.setattr(VC, "lire_gpu_pct", lambda: None)
    assert RM._sample_gpu_win32() is None


@pytest.mark.parametrize("g3d,gcp,attendu", [(10.0, 40.0, 40.0), (70.0, 5.0, 70.0), (130.0, 0.0, 100.0)])
def test_le_pourcentage_retient_le_moteur_le_plus_charge(monkeypatch, g3d, gcp, attendu):
    monkeypatch.setattr(VC, "_pdh_gpu_ouvrir", lambda: "")
    monkeypatch.setattr(VC, "_pdh_gpu_collecter", lambda: True)
    monkeypatch.setitem(VC._PDH_GPU, "amorce", True)
    monkeypatch.setattr(VC, "_pdh_gpu_tableau", lambda cle: [])
    monkeypatch.setattr(VC, "agreger_gpu", lambda *_a: {"g3d": g3d, "gcp": gcp})
    assert VC.lire_gpu_pct() == attendu


def test_compteur_refuse_ou_premiere_collecte_rend_none(monkeypatch):
    monkeypatch.setattr(VC, "_pdh_gpu_ouvrir", lambda: "refuse")
    assert VC.lire_gpu_pct() is None
    monkeypatch.setattr(VC, "_pdh_gpu_ouvrir", lambda: "")
    monkeypatch.setattr(VC, "_pdh_gpu_collecter", lambda: True)
    monkeypatch.setitem(VC._PDH_GPU, "amorce", False)
    assert VC.lire_gpu_pct() is None


def test_un_echec_ne_republie_pas_l_ancienne_valeur(monkeypatch):
    monkeypatch.setattr(RM, "_sample_gpu_win32", lambda: None)
    monkeypatch.setitem(RM._SNAPSHOT, "gpu_pct", 42.0)
    monkeypatch.setattr(RM, "_last_gpu_check_ts", 0.0)
    monkeypatch.setattr(RM, "_gpu_suspended_until_ts", 0.0)
    out = RM._sample_once()
    assert out["gpu_pct"] is None, "une mesure ratee n'est pas l'ancienne mesure"
