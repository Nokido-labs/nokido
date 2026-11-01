"""NR 30/10 -- l'executif Hamilton n'endort pas un executeur qui a du travail en vol (hors detresse).

Mesure 21:30:37 (laforge-master.log) : « POST /supervisor/sleep/NokidoTaskExecutorOpencodeGlm » pendant que sa tache
job_83b95c11 (traductions) etait running ; l'executeur est mort, relance 1 s plus tard -- travail perdu, aucun gain.
La voie _sleep_service_verdict refusait deja TRAVAIL_EN_VOL ; Hamilton (plan_hamilton -> _ordre_superviseur SUSPENDRE)
ne la consultait pas. Meme doctrine : epargne sauf urgence vitale (detresse), et une file ILLISIBLE epargne aussi.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as RM  # noqa: E402

OCCUPE, OISIF, ILLISIBLE = "NokidoTaskExecutorOpencodeGlm", "NokidoTaskExecutorCodex", "NokidoTaskExecutorMistral"


def _plan(monkeypatch, detresse=False):
    monkeypatch.setattr(RM, "_services_du_toml", lambda: {OCCUPE: {}, OISIF: {}, ILLISIBLE: {}})
    monkeypatch.setattr(RM, "_registre_corps", lambda: {OCCUPE: 1, OISIF: 2, ILLISIBLE: 3})
    monkeypatch.setattr(RM, "_memoire_privee_mb", lambda pid: 50.0)
    monkeypatch.setattr(RM, "classe_hamilton", lambda decl, critique=False: "CONFORT")
    monkeypatch.setattr(RM, "_travail_en_vol",
                        lambda s: {OCCUPE: ["job_83b95c11"], OISIF: [], ILLISIBLE: None}.get(s, []))
    monkeypatch.setattr(RM, "ordre_delestage",
                        lambda candidats, verdict, detresse=False: {"delester": [c["service"] for c in candidats]})
    return RM.plan_hamilton(attrib={"verdict": "SOI"}, detresse=detresse)


def test_executeur_occupe_ou_illisible_epargne_hors_detresse(monkeypatch):
    plan = _plan(monkeypatch)
    assert plan["delester"] == [OISIF]
    epargnes = {e["service"] for e in plan.get("epargnes", [])}
    assert {OCCUPE, ILLISIBLE} <= epargnes


def test_en_detresse_la_survie_passe_d_abord(monkeypatch):
    plan = _plan(monkeypatch, detresse=True)
    assert set(plan["delester"]) == {OCCUPE, OISIF, ILLISIBLE}
