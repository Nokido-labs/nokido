"""NR -- le gate P1 ne refuse plus un spawn sur une lecture RAM DEMENTIE par la mesure directe (2026-10-13).

Owner : « non la RAM est a 64 %, ton erreur de mesure est recurrente ! ». Le gate avait refuse sur « RAM 97,6 %
(libre 0,58 Go) » ; la boite noire du hub n'a jamais depasse 85,4 % sur la fenetre, psutil et l'API Windows lisaient
66 %. Le 24/07 deja : « gate a 87,8 % pendant que resource_state lisait 68,3 % ».
"""
from __future__ import annotations

import time

import nokido_agent.app.forge_sandbox_exec as S


def _snap(**kw):
    base = {"ts": time.time(), "ram_pct": 97.6, "ram_free_gb": 0.58, "cpu_pct": 10.0, "disk_pct": 50.0,
            "gpu_pct": 3.0, "sampler": "test"}
    base.update(kw)
    return base


def test_une_lecture_dementie_par_la_mesure_directe_annule_le_refus(monkeypatch):
    monkeypatch.setattr(S, "_ram_directe", lambda: (66.0, 7.84))
    motif = S._ram_dementie(_snap())
    assert motif and "DEMENTI" in motif and "66.0%" in motif


def test_une_lecture_confirmee_garde_le_refus(monkeypatch):
    monkeypatch.setattr(S, "_ram_directe", lambda: (96.0, 0.9))
    assert S._ram_dementie(_snap()) is None


def test_une_mesure_directe_illisible_n_annule_rien(monkeypatch):
    monkeypatch.setattr(S, "_ram_directe", lambda: None)
    assert S._ram_dementie(_snap()) is None, "illisible n'est pas 0 : on ne desarme pas le garde"


def test_un_refus_qui_ne_vient_pas_de_la_ram_n_est_pas_touche(monkeypatch):
    monkeypatch.setattr(S, "_ram_directe", lambda: (40.0, 14.0))
    assert S._ram_dementie(_snap(ram_pct=50.0)) is None
    assert S._ram_dementie(_snap(cpu_pct=99.0)) is None
    assert S._ram_dementie(_snap(gpu_pct=99.0)) is None
    assert S._ram_dementie(_snap(disk_pct=97.0)) is None


def test_le_refus_dit_l_age_la_source_et_la_mesure_directe(monkeypatch):
    monkeypatch.setattr(S, "_ram_directe", lambda: None)
    t = S._temoins_ram(_snap(ts=time.time() - 42, sampler="hub"))
    assert "age 42 s" in t and "source hub" in t and "ILLISIBLE" in t
