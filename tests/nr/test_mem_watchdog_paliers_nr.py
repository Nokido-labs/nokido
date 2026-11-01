# -*- coding: utf-8 -*-
"""NR paliers relatifs du chien de garde memoire : rss et horloge injectes, ni thread ni processus, rien dans sandbox/ reel."""
import json

import pytest

from app.hardware import mem_watchdog as mw


@pytest.fixture
def w(monkeypatch, tmp_path):
    monkeypatch.delenv("LAFORGE_MEM_TRACE", raising=False)
    monkeypatch.setattr(mw, "_ETAT_PATH", tmp_path / "hub_mem_palier.json")
    monkeypatch.setattr(mw, "_LOGS_DIR", tmp_path)
    monkeypatch.setattr(mw.gc, "collect", lambda *a: 0)
    return mw.MemWatchdog(warn_mb=300, dump_mb=500, poll_interval=30)


def _amorce(w, base=100.0, n=12):
    for i in range(n):
        w._check(rss=base, maintenant=float(i))
    return float(n)


def test_base_illisible_n_est_pas_calme(w):
    for i in range(9):
        w._check(rss=100.0, maintenant=float(i))
    assert w.status()["palier"] == "ILLISIBLE"
    w._check(rss=100.0, maintenant=9.0)
    assert w.status()["palier"] == "CALME"


def test_repli_absolu_tant_que_base_illisible(w):
    """Mesure 28/10 15:40 : le hub DEMARRE a 1103 Mo et vit autour de 500 Mo ; l'ancien repli warn/dump (300/500)
    le declarait DETRESSE a chaque demarrage (et refusait les run synchrones lourds). Base illisible : seul le
    plafond absolu prouve une detresse ; sinon ILLISIBLE, sans intention (ni CALME, ni fausse detresse)."""
    w._check(rss=600.0, maintenant=0.0)
    assert w.status()["palier"] == "ILLISIBLE"
    assert w.status()["intentions"] == []
    w._check(rss=1600.0, maintenant=1.0)
    assert w.status()["palier"] == "DETRESSE"


def test_paliers_par_ratio_et_intentions_cumulatives(w):
    t = _amorce(w)
    w._check(rss=130.0, maintenant=t)
    s = w.status()
    assert s["palier"] == "PREFERENCE"
    assert s["intentions"] == ["preferer_jobs_detaches", "differer_taches_lourdes_in_process"]
    w._check(rss=160.0, maintenant=t + 1)
    s = w.status()
    assert s["palier"] == "GENE" and s["intentions"][-2:] == ["gc_collect", "vider_caches_bornes"]
    w._check(rss=250.0, maintenant=t + 2)
    s = w.status()
    assert s["palier"] == "DETRESSE" and s["intentions"][-1] == "dump_borne" and len(s["intentions"]) == 5


def test_plafond_absolu_donne_detresse(w, monkeypatch):
    monkeypatch.setattr(mw, "PLAFOND_MB", 1500.0)
    t = _amorce(w, base=1400.0)
    w._check(rss=1500.0, maintenant=t)
    assert w.status()["palier"] == "DETRESSE"


def test_hysteresis_a_la_descente(w):
    t = _amorce(w)
    w._check(rss=130.0, maintenant=t)
    w._check(rss=120.0, maintenant=t + 1)  # < 1.25 mais >= 1.25*0.9 : on reste
    assert w.status()["palier"] == "PREFERENCE"
    w._check(rss=105.0, maintenant=t + 2)
    assert w.status()["palier"] == "CALME"


def test_journal_a_la_transition_seulement(w, caplog):
    t = _amorce(w)
    with caplog.at_level("DEBUG", logger="Nokido.MemWatchdog"):
        for i in range(5):
            w._check(rss=160.0, maintenant=t + i)
    msgs = [r for r in caplog.records if r.levelno >= 20]
    assert len(msgs) == 1 and msgs[0].levelname == "WARNING"


def test_niveaux_de_journal_par_palier(w, caplog):
    t = _amorce(w)
    with caplog.at_level("INFO", logger="Nokido.MemWatchdog"):
        w._check(rss=130.0, maintenant=t)
        w._check(rss=160.0, maintenant=t + 1)
        w._check(rss=250.0, maintenant=t + 2)
    assert [r.levelname for r in caplog.records] == ["INFO", "WARNING", "ERROR"]


def test_etat_publie_atomiquement(w, tmp_path):
    t = _amorce(w)
    w._check(rss=130.0, maintenant=t)
    d = json.loads((tmp_path / "hub_mem_palier.json").read_text(encoding="utf-8"))
    assert set(d) == {"ts", "rss_mb", "base_mb", "ratio", "palier", "intentions"}
    assert d["palier"] == "PREFERENCE" and d["base_mb"] == 100.0
    assert list(tmp_path.glob("*.tmp")) == []


def test_fenetre_glissante(w, monkeypatch):
    monkeypatch.setattr(mw, "BASE_FENETRE_S", 100.0)
    for i in range(12):
        w._check(rss=100.0, maintenant=float(i))
    for i in range(12):
        w._check(rss=100.0, maintenant=1000.0 + i)
    assert len(w._echantillons) == 12


def test_gc_et_dump_seulement_sur_demande(w, monkeypatch):
    appels = []
    monkeypatch.setattr(mw.gc, "collect", lambda *a: appels.append(1) or 0)
    t = _amorce(w)
    w._check(rss=250.0, maintenant=t)
    assert appels == [] and not w._tracing
