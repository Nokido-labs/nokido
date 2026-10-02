# -*- coding: utf-8 -*-
"""NR -- la porte d'admission ne fige plus la boucle du hub (2026-10-01).

Journal de forge_loop_sentinel sur 7 jours : 292 gels, 567 s de boucle figee (77 % du
total), tous par handle_run -> check_ressources -> _get_system_health -> _sys_metrics ->
`psutil.cpu_percent(interval=1)`, qui DORT une seconde (jusqu'a 5,5 s avec _try_reserve).
La porte lit desormais le CPU que le sampler de forge_resource_manager mesure deja hors de
toute boucle -- s'il est frais et s'il en porte un. Le piege : `psutil.cpu_percent` leve,
donc toute mesure dormante se voit (source != "sampler").
"""
import importlib
import sys
import time
from pathlib import Path

import psutil
import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def porte(monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("mesure CPU dormante appelee par la porte")
    monkeypatch.setattr(psutil, "cpu_percent", interdit)
    rm = importlib.import_module("nokido_agent.app.forge_resource_manager")
    la = importlib.import_module("nokido_agent.app.forge_lane_admission")
    return la, rm


def test_un_cpu_frais_du_sampler_est_lu_sans_dormir(porte, monkeypatch):
    la, rm = porte
    monkeypatch.setattr(rm, "get_snapshot", lambda: {"ts": time.time() - 2, "cpu_pct": 37.5, "ram_pct": 1.0})
    t0 = time.perf_counter()
    h = la._get_system_health()
    assert time.perf_counter() - t0 < 0.5
    assert h["source"] == "sampler" and h["cpu_pct"] == 37.5
    # la RAM vient de la lecture DIRECTE, pas de l'instantane (reserve absolue exacte)
    assert h["ram_pct"] != 1.0 and h["ram_dispo_gb"] > 0


@pytest.mark.parametrize("instantane", [
    {"ts": 0.0, "cpu_pct": 37.5},                  # jamais echantillonne
    {"ts": time.time() - 3600, "cpu_pct": 37.5},   # sampler fige
    {"ts": time.time(), "ram_pct": 50.0},          # amorce a froid : PAS de CPU, expres
])
def test_sans_cpu_frais_la_porte_ne_l_invente_pas(porte, monkeypatch, instantane):
    la, rm = porte
    monkeypatch.setattr(rm, "get_snapshot", lambda: dict(instantane))
    h = la._get_system_health()
    # repli sur le chemin historique ; ici psutil.cpu_percent est piege -> mesure
    # impossible -> FAIL-CLOSED dit comme tel, jamais un CPU invente depuis l'instantane
    assert h["source"] != "sampler"
    assert h.get("degraded") is True and h["source"] == "indisponible"
