"""NR 18/10 -- L1 sait juger une dimension a MINIMISER (chantier 1 du takehome, pas 2).

Carto AGY (job_53f21306) : ecarts_hors_bande et le test « sans gain » de mesurer_apres supposent « plus haut =
mieux » (d = m - r) -- inapplicable a des cycles, une duree, une RAM. `orientation={dimension: "MIN"|"MAX"}`
(MAX par defaut = comportement inchange) ; une orientation inconnue compte comme ECART, jamais comme saine.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_mutation_controller as mc  # noqa: E402

MIN = {"cycles": "MIN"}


def test_ecarts_min_la_hausse_est_un_recul():
    assert [e["dimension"] for e in mc.ecarts_hors_bande({"cycles": 100}, {"cycles": 120}, {}, orientation=MIN)] == ["cycles"]
    assert mc.ecarts_hors_bande({"cycles": 100}, {"cycles": 80}, {}, orientation=MIN) == []


def test_sans_orientation_le_comportement_est_inchange():
    assert mc.ecarts_hors_bande({"cycles": 100}, {"cycles": 120}, {}) == []
    assert [e["dimension"] for e in mc.ecarts_hors_bande({"cycles": 100}, {"cycles": 80}, {})] == ["cycles"]


def test_orientation_inconnue_compte_comme_ecart():
    e = mc.ecarts_hors_bande({"cycles": 100}, {"cycles": 80}, {}, orientation={"cycles": "PLUS"})
    assert [x["dimension"] for x in e] == ["cycles"] and "orientation" in e[0]["motif"]


def _mesurer_apres(monkeypatch, apres):
    etat = {"v": apres}
    monkeypatch.setattr(mc, "_inscrire", lambda rec: "id")
    monkeypatch.setattr(mc, "_poser_frein", lambda motif: None)
    monkeypatch.setattr(mc, "_generation_avant", lambda: None)
    monkeypatch.setattr(mc, "_reverts_consecutifs", lambda: 0)

    def reverter():
        etat["v"] = 100
        return {"ok": True}

    return mc.mesurer_apres("L1", "param:test", "exp", {"cycles": 100}, "E0",
                            lambda: {"cycles": etat["v"]}, reverter,
                            lambda: "E0" if etat["v"] == 100 else "E1", {"cycles": 0}, orientation=MIN)


def test_mesurer_apres_min_garde_une_baisse(monkeypatch):
    assert _mesurer_apres(monkeypatch, 80)["verdict"] == mc.CONSERVE


def test_mesurer_apres_min_defait_une_hausse_et_un_statu_quo(monkeypatch):
    assert _mesurer_apres(monkeypatch, 120)["verdict"] == mc.REVERTE
    assert _mesurer_apres(monkeypatch, 100)["verdict"] == mc.SURVIT_SANS_GAIN


def test_appliquer_et_mesurer_transmet_l_orientation():
    assert "orientation" in inspect.signature(mc.appliquer_et_mesurer).parameters
