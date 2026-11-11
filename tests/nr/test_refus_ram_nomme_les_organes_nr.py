# -*- coding: utf-8 -*-
"""NR -- owner 9/11 « il faut que Nokido ait une visibilite parfaite sur ses processus, sinon il ne pourra jamais
s'auto-reguler ». Mesure du 9/11 : run_job refuse « RISQUE EMBOLIE RAM (84.1% ...) » sans dire QUI tient la memoire,
alors que le corps sait l'attribuer (SOI 9,4 Go, dont NokidoTraceSidecar 1,5 Go, enfants de Defaut2 1,47 Go).
Un refus doit nommer les organes les plus lourds ; une attribution illisible est DITE, jamais tue."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_lane_admission as la  # noqa: E402
from nokido_agent.app import forge_resource_manager as rm  # noqa: E402


def _o(pct, age=0.0, src="psutil", dispo=3.7):
    return {"ram_pct": pct, "age_s": age, "source": src, "ram_dispo_gb": dispo}


def test_top_par_organe_agrege_et_trie():
    paires = [(0.5, "NokidoTraceSidecar"), (1.0, "NokidoTraceSidecar"), (0.7, "NokidoMCP"),
              (1.2, "NokidoTaskExecutorOpencodeDefaut2"), (0.1, "NokidoOllama")]
    top = rm.top_par_organe(paires, n=3)
    assert [t["organe"] for t in top] == ["NokidoTraceSidecar", "NokidoTaskExecutorOpencodeDefaut2", "NokidoMCP"]
    assert abs(top[0]["gb"] - 1.5) < 1e-9


def test_le_resume_nomme_les_organes_du_corps_en_tete():
    a = {"verdict": "NOYAU", "soi_gb": 9.4, "non_soi_gb": 11.7, "incertain_gb": 0.0, "illisibles": 1,
         "top_soi": [{"organe": "NokidoTraceSidecar", "gb": 1.5}, {"organe": "NokidoMCP", "gb": 0.7}],
         "top_handles": [{"name": "audiodg.exe", "handles": 690705}]}
    s = rm.resume_attribution(a)
    assert "soi: NokidoTraceSidecar 1.5 Go" in s
    assert s.index("soi: NokidoTraceSidecar") < s.index("handles:")


def test_un_refus_ram_dit_qui_tient_la_memoire():
    d = la.arbitrer_ram([_o(84.2)], remesurer=lambda: None,
                        attribuer=lambda: {"verdict": "SOI", "soi_gb": 9.4, "non_soi_gb": 2.0, "incertain_gb": 0.0,
                                           "illisibles": 0, "top_soi": [{"organe": "NokidoTraceSidecar", "gb": 1.5}]})
    assert d["ok"] is False
    assert "RISQUE EMBOLIE RAM" in d["motif"]
    assert "tient" in d["motif"] and "NokidoTraceSidecar 1.5 Go" in d["motif"]


def test_attribution_illisible_est_dite_pas_tue():
    def _boum():
        raise RuntimeError("registre muet")

    d = la.arbitrer_ram([_o(84.2)], remesurer=lambda: None, attribuer=_boum)
    assert d["ok"] is False and "attribution ILLISIBLE (RuntimeError)" in d["motif"]
