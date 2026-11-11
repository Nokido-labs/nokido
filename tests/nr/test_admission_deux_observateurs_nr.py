"""NR — garde d'admission a DEUX OBSERVATEURS (24/10 : refus sur un instantane de 35 s a 97 %,
mesure directe a 69 %). La protection contre l'embolie n'est jamais relachee."""
from __future__ import annotations

import app.forge_lane_admission as la


def _o(pct, age, src, dispo=8.0):
    return {"ram_pct": pct, "ram_dispo_gb": dispo, "age_s": age, "source": src}


def test_instantane_perime_vs_lecture_fraiche_remesure_admis():
    appels = []

    def rem():
        appels.append(1)
        return _o(69.1, 0.0, "psutil", 7.31)

    d = la.arbitrer_ram([_o(97.2, 35.0, "sampler"), _o(69.1, 0.0, "psutil", 7.31)], remesurer=rem)
    assert appels, "divergence > 10 points : re-mesure immediate"
    assert d["ok"] is True


def test_deux_lectures_fraiches_au_dessus_du_seuil_refus_avec_source_et_age():
    d = la.arbitrer_ram([_o(96.0, 2.0, "sampler"), _o(97.0, 0.0, "psutil")],
                        remesurer=lambda: _o(96.5, 0.0, "psutil"))
    assert d["ok"] is False
    assert d["source"] and d["age_s"] is not None
    assert "source" in d["motif"] and "age" in d["motif"]


def test_desaccord_persistant_refus_ram_desaccord_journalise(monkeypatch):
    journal = []
    monkeypatch.setattr(la, "_journaliser_refus", lambda m, s, lane="": journal.append(m))
    d = la.arbitrer_ram([_o(97.0, 3.0, "sampler"), _o(69.0, 0.0, "psutil")],
                        remesurer=lambda: _o(69.0, 0.0, "psutil"))
    assert d["ok"] is False and d["ram_desaccord"] is True
    assert d["retry_after"] > 0
    assert any("ram_desaccord" in m for m in journal)
    assert "97.0" in d["motif"] and "69.0" in d["motif"]


def test_refus_en_nr_sans_attribution_reelle():
    """10/11 (pre-vol job_fa2fd1001593) : le refus appelait `_qui_tient(None)` -> attribuer_pression() REEL
    (11,3 s a froid, mesure job_f8d12ac54be7) -> >30 s sous 5 workers -> pytest-timeout os._exit -> gw1 mort,
    suite figee. En NR, l'attribution par defaut est neutralisee (tests/nr/conftest.py) ; injectee, elle reste reelle."""
    import time
    t0 = time.time()
    d = la.arbitrer_ram([_o(96.0, 2.0, "sampler"), _o(97.0, 0.0, "psutil")],
                        remesurer=lambda: _o(96.5, 0.0, "psutil"))
    assert d["ok"] is False and time.time() - t0 < 2.0
    assert "neutralisee" in d["motif"]
    assert la._qui_tient(lambda: {"injecte": 1}) != la._qui_tient()  # pylint: disable=protected-access


def test_reserve_absolue_toujours_appliquee_et_refus_porte_source_et_age():
    d = la.arbitrer_ram([_o(70.0, 0.0, "psutil", dispo=3.9)])
    assert d["ok"] is False and d["source"] == "psutil" and d["age_s"] == 0.0
