# -*- coding: utf-8 -*-
"""NR (19/10, relecture pair claude.ai pair_0891188ab09db024, verifiee sur piece) : la reconciliation MESURE, elle
n'evince pas -- et son bilan au boot ne perd pas ses incidents.

1. reconcile_jobs appelait check_ressources(heavy=True) pour decider A_SUSPENDRE : sous saturation, celui-ci lance
   `_try_reserve()` (eviction reelle : Ollama, llama-server, conteneurs) et journalise un « refus » -- meme avec
   apply=False, au boot du hub : un bilan pouvait defaire les prechauffages. Desormais `etat_ressources()` : meme mesure,
   meme seuil, AUCUN effet ; mesure indisponible = INCONNU (traite comme saturation pour le seul DIFFERABLE).
2. reconcilier_au_boot retirait `details` et rendait ok:True : une ecriture refusee ou une lane non rendue disparaissait
   du bilan. Elles remontent dans `incidents`.
"""
import json
import sys
import time
from datetime import datetime

import pytest

from nokido_agent.app import forge_job_runner as J
from nokido_agent.app import forge_lane_admission as A


def _interdit(*a, **k):
    raise AssertionError("la reconciliation ne doit ni evincer ni journaliser de refus")


def test_etat_ressources_mesure_sans_effet(monkeypatch):
    monkeypatch.setattr(A, "_get_system_health", lambda: {"ram_pct": 97.0, "ram_dispo_gb": 0.5})
    monkeypatch.setattr(A, "_try_reserve", _interdit)
    monkeypatch.setattr(A, "_journaliser_refus", _interdit)
    e = A.etat_ressources()
    assert e["sature"] is True and "RAM" in e["motif"]
    monkeypatch.setattr(A, "_get_system_health", lambda: {"degraded": True})
    assert A.etat_ressources()["sature"] is None


class _NoSuch(Exception):
    pass


class _Proc:
    def __init__(self, pid):
        self.pid = pid

    def create_time(self):
        return time.time() - 3600


def test_reconcile_n_evince_pas(monkeypatch, tmp_path):
    rec = {"job_id": "J", "status": "running", "pid": 1002, "lane": "l", "started": datetime.now().isoformat(),
           "rc_file": str(tmp_path / "J.rc"), "classe": "DIFFERABLE"}
    (tmp_path / "J.json").write_text(json.dumps(rec), encoding="utf-8")
    monkeypatch.setattr(J, "JOBS_DIR", tmp_path)
    monkeypatch.setitem(sys.modules, "psutil", type("P", (), {"Process": _Proc, "NoSuchProcess": _NoSuch}))
    monkeypatch.setattr(A, "_get_system_health", lambda: {"ram_pct": 97.0, "ram_dispo_gb": 0.5})
    effets = []   # COMPTER : reconcile attrape toute exception, une doublure qui leve passerait inapercue
    monkeypatch.setattr(A, "_try_reserve", lambda *a, **k: effets.append("eviction") or {})
    monkeypatch.setattr(A, "_journaliser_refus", lambda *a, **k: effets.append("refus"))
    out = J.reconcile_jobs(apply=False)
    assert out["a_suspendre"] == 1 and effets == []


def test_le_bilan_au_boot_garde_ses_incidents(monkeypatch):
    monkeypatch.setattr(J, "reconcile_jobs", lambda apply=False: {
        "vus": 2, "dead": 2, "a_suspendre": 0, "vivants": 0, "indetermine": 0,
        "details": [{"fiche": "a.json", "verdict": "dead", "ECRITURE_REFUSEE": "PermissionError"},
                    {"fiche": "b.json", "verdict": "dead", "lane_release_error": "OperationalError"}]})
    r = J.reconcilier_au_boot()
    assert len(r["incidents"]) == 2 and {i["fiche"] for i in r["incidents"]} == {"a.json", "b.json"}
