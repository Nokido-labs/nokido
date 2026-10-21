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


def _rss_fixe(monkeypatch, mw, mo: float) -> None:
    monkeypatch.setattr(mw, "_rss_mb", lambda: float(mo))


def test_sans_demande_le_gardien_n_arme_jamais_tracemalloc(monkeypatch, tmp_path):
    """Mesure 16/10 (Windows, journal NokidoMCP.log : 7 « tracemalloc active », 0 desactivation ; « RAM CRITIQUE 550MB
    >= 500MB » encore a 09:30). La lecture ctypes d'avant 72acf25c9 ECHOUAIT sous Windows (API 0, GetLastError 6) :
    le gardien ne se declenchait jamais. RSS lue juste + warn 300 / dump 500 Mo + hub a 500-800 Mo = hub en PERMANENCE
    sous tracemalloc(10) -- ast.parse x6, introspect x2,6 (banc C:/tmp/diag_introspect) -- et, au-dela de 500 Mo, un
    instantane + statistics (2,8 s) + GC force + fichier de dump TOUTES LES 30 s. Le tracage devient une DEMANDE."""
    import tracemalloc
    mw = _module()
    monkeypatch.delenv("LAFORGE_MEM_TRACE", raising=False)
    monkeypatch.setattr(mw, "_LOGS_DIR", tmp_path)
    appels = []
    monkeypatch.setattr(mw.gc, "collect", lambda *a: appels.append(1) or 0)
    _rss_fixe(monkeypatch, mw, 600)
    w = mw.MemWatchdog(warn_mb=300, dump_mb=500, poll_interval=30)
    for _ in range(3):
        w._check()
    assert not w._tracing and not tracemalloc.is_tracing(), "tracemalloc arme sans demande"
    assert list(tmp_path.glob("mem_dump_*")) == [] and appels == [], "dump ou GC force sans demande"


def test_le_niveau_est_dit_a_la_transition_pas_a_chaque_tick(monkeypatch, caplog):
    mw = _module()
    monkeypatch.delenv("LAFORGE_MEM_TRACE", raising=False)
    _rss_fixe(monkeypatch, mw, 600)
    w = mw.MemWatchdog(warn_mb=300, dump_mb=500, poll_interval=30)
    with caplog.at_level("INFO", logger="Nokido.MemWatchdog"):
        for _ in range(4):
            w._check()
    assert sum("RAM CRITIQUE" in r.getMessage() for r in caplog.records) == 1, "le meme niveau repete a chaque tick"


def test_sur_demande_le_dump_est_borne_dans_le_temps(monkeypatch, tmp_path):
    """Le diagnostic reste disponible (LAFORGE_MEM_TRACE=1) : un dump + un GC force au plus par fenetre."""
    import tracemalloc
    mw = _module()
    monkeypatch.setenv("LAFORGE_MEM_TRACE", "1")
    monkeypatch.setattr(mw, "_LOGS_DIR", tmp_path)
    appels = []
    monkeypatch.setattr(mw.gc, "collect", lambda *a: appels.append(1) or 0)
    _rss_fixe(monkeypatch, mw, 600)
    w = mw.MemWatchdog(warn_mb=300, dump_mb=500, poll_interval=30)
    try:
        for _ in range(3):
            w._check()
        assert w._tracing, "le diagnostic demande doit tracer"
        assert len(list(tmp_path.glob("mem_dump_*"))) == 1 and len(appels) == 1, "dump et GC bornes dans le temps"
    finally:
        if w._tracing:
            w._stop_tracing()
        if tracemalloc.is_tracing():
            tracemalloc.stop()


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
