"""NR -- le gardien memoire lit la RSS COURANTE, en bonnes unites, sur toute plate-forme.

MESURE du 2026-10-14 (organisme macOS, run public 38536079233) : « RAM CRITIQUE 112912MB >= 500MB » sur un
runner de 14 Go. `_rss_mb` divisait `ru_maxrss` par 1024 partout ; sous macOS `ru_maxrss` est en OCTETS (en
kilo-octets sous Linux) et c'est un PIC. Le hub macOS se croyait en crise a chaque controle : tracemalloc arme
en permanence, instantane et GC force toutes les 30 s -- hypothese de son retard sur `/api/login` (P2).
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("mem_watchdog_nr", ROOT / "app" / "hardware" / "mem_watchdog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sans_psutil_avec_pic(monkeypatch, plateforme, ru_maxrss):
    monkeypatch.setitem(sys.modules, "psutil", None)                 # import psutil -> ImportError
    faux = types.ModuleType("resource")
    faux.RUSAGE_SELF = 0
    faux.getrusage = lambda _qui: types.SimpleNamespace(ru_maxrss=ru_maxrss)
    monkeypatch.setitem(sys.modules, "resource", faux)
    monkeypatch.setattr(sys, "platform", plateforme)


def test_macos_ru_maxrss_est_en_octets(monkeypatch):
    mw = _module()
    _sans_psutil_avec_pic(monkeypatch, "darwin", 115_617_792)        # ~110 Mo, la valeur du runner
    assert 100 < mw._rss_mb() < 120, "octets lus comme des Ko : 112 912 « Mo » sur un runner de 14 Go"


def test_linux_ru_maxrss_est_en_kilo_octets(monkeypatch):
    mw = _module()
    _sans_psutil_avec_pic(monkeypatch, "linux", 112_912)
    assert 100 < mw._rss_mb() < 120


def test_psutil_donne_la_rss_courante_d_abord(monkeypatch):
    mw = _module()
    faux = types.ModuleType("psutil")
    faux.Process = lambda: types.SimpleNamespace(memory_info=lambda: types.SimpleNamespace(rss=200 * 1024 * 1024))
    monkeypatch.setitem(sys.modules, "psutil", faux)
    assert round(mw._rss_mb()) == 200


def test_le_controle_reel_ne_crie_pas_sur_un_hub_de_110_mo(monkeypatch):
    mw = _module()
    _sans_psutil_avec_pic(monkeypatch, "darwin", 115_617_792)
    w = mw.MemWatchdog(warn_mb=400, dump_mb=500, poll_interval=30)
    try:
        w._check()
        assert not w._tracing, "tracemalloc arme sur 110 Mo : le hub tournerait ralenti en permanence"
    finally:
        if w._tracing:
            w._stop_tracing()
