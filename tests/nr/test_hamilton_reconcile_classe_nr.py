# -*- coding: utf-8 -*-
"""NR HAMILTON RED_4 (pair_1200324b1e5391b0, spec AGY 6a2393bfc) : protection au restart.

Deux fiches running vivantes (un DIFFERABLE, un CRITIQUE) + une morte, machine saturee :
la morte rend sa lane, le DIFFERABLE est SIGNALE A_SUSPENDRE avec motif, le CRITIQUE n'est pas
touche. Jamais de kill (decision owner 16/10 : survivant DIFFERABLE = SUSPENSION). Mesure
indisponible = saturation pour le seul DIFFERABLE (doctrine du doute) ; classe absente = NORMAL.
"""
import json
import sys
import time
from datetime import datetime

import pytest

from nokido_agent.app import forge_job_runner as J
from nokido_agent.app import forge_lane_admission as A


class _NoSuch(Exception):
    pass


class _Proc:
    def __init__(self, pid):
        if pid == 9999:
            raise _NoSuch()
        self.pid = pid

    def create_time(self):
        return time.time() - 3600

    def kill(self):
        raise AssertionError("JAMAIS de kill a la reconciliation")

    terminate = suspend = kill


class _FauxPsutil:
    Process = _Proc
    NoSuchProcess = _NoSuch


@pytest.fixture
def fiches(monkeypatch, tmp_path):
    debut = datetime.now().isoformat()
    for jid, pid, classe in (("J_morte", 9999, "DIFFERABLE"), ("J_diff", 1002, "DIFFERABLE"),
                             ("J_crit", 1001, "CRITIQUE"), ("J_sans", 1003, None)):
        rec = {"job_id": jid, "status": "running", "pid": pid, "lane": "lane_" + jid, "started": debut,
               "rc_file": str(tmp_path / (jid + ".rc"))}
        if classe:
            rec["classe"] = classe
        (tmp_path / (jid + ".json")).write_text(json.dumps(rec), encoding="utf-8")
    monkeypatch.setattr(J, "JOBS_DIR", tmp_path)
    monkeypatch.setitem(sys.modules, "psutil", _FauxPsutil)
    liberees = []
    monkeypatch.setattr(A, "release", lambda lane, jid: liberees.append(lane))
    return liberees


def _par_fiche(out):
    return {d["fiche"]: d for d in out["details"]}


def test_red4_sature_differable_signale_critique_intact(monkeypatch, fiches):
    # 19/10 : la reconciliation lit etat_ressources (mesure SANS effet), plus check_ressources (qui evincait)
    monkeypatch.setattr(A, "etat_ressources", lambda *a, **k: {"sature": True, "motif": "RISQUE EMBOLIE RAM (92% > 85%)"})
    out = J.reconcile_jobs(apply=True)
    d = _par_fiche(out)
    assert d["J_morte.json"]["verdict"] == "dead" and fiches == ["lane_J_morte"]
    assert d["J_diff.json"]["verdict"] == "A_SUSPENDRE" and "EMBOLIE" in d["J_diff.json"]["motif"]
    assert "J_crit.json" not in d and "J_sans.json" not in d  # CRITIQUE et NORMAL (classe absente) intacts
    assert out["a_suspendre"] == 1 and out["vivants"] == 3


def test_red4_hors_pression_rien_a_suspendre(monkeypatch, fiches):
    monkeypatch.setattr(A, "etat_ressources", lambda *a, **k: {"sature": False, "motif": ""})
    out = J.reconcile_jobs(apply=True)
    assert out["a_suspendre"] == 0 and "J_diff.json" not in _par_fiche(out)


def test_red4_mesure_indisponible_signale_le_differable_seul(monkeypatch, fiches):
    def casse(*a, **k):
        raise RuntimeError("sonde")
    monkeypatch.setattr(A, "etat_ressources", casse)
    d = _par_fiche(J.reconcile_jobs(apply=True))
    assert d["J_diff.json"]["verdict"] == "A_SUSPENDRE" and "mesure indisponible" in d["J_diff.json"]["motif"]
    assert "J_sans.json" not in d
