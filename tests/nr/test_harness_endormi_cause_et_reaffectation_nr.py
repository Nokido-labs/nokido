# -*- coding: utf-8 -*-
"""NR -- defaut 1 : classement cause echec harness worker endormi/mort et refus de reaffectation sur voie perimee.

Mesure job_115ff28d et job_8d21c7fe : worker harness endormi/pouls perime,
la cause d'echec doit etre classee HARNESS_WORKER et non INCONNU,
et la reaffectation ne doit pas selectionner une voie dont le harness est perime.
"""
from __future__ import annotations

import datetime
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_task_executor as T  # noqa: E402


def test_classement_cause_harness_worker_endormi_ou_perime():
    rendu_vibe = "[HARNESS WORKER pouls perime de 646 s] Vibe non lance"
    assert T.classer_cause_echec(rendu_vibe) == "HARNESS_WORKER"

    rendu_claude = "[HARNESS WORKER pouls perime de 320 s] claude -p non lance"
    assert T.classer_cause_echec(rendu_claude) == "HARNESS_WORKER"

    rendu_muet = "harness MUET apres 600 s (NokidoHarnessWorker arrete ou occupe ?) -- job vibe_123"
    assert T.classer_cause_echec(rendu_muet) == "HARNESS_WORKER"


def test_candidat_eligible_refuse_voie_harness_si_pouls_perime(tmp_path, monkeypatch):
    monkeypatch.delenv("LAFORGE_HARNESS_POULS_IGNORE", raising=False)
    hb = tmp_path / "harness_worker.heartbeat"
    # Pouls vieux de 1000s (> 300s)
    ts = (datetime.datetime.now() - datetime.timedelta(seconds=1000)).isoformat(timespec="seconds")
    hb.write_text(json.dumps({"ts": ts, "pid": 1}), encoding="utf-8")
    monkeypatch.setattr(T, "_HARNESS_HEARTBEAT", hb)

    # Simuler executeur qui bat
    monkeypatch.setattr(T, "_executeur_bat", lambda a: True)
    monkeypatch.setattr(T, "_executeur_suspendu", lambda a: False)
    monkeypatch.setattr(T, "_opencode_hors_quota", lambda a: False)
    monkeypatch.setattr(T, "statut_coupe_circuit", lambda a, **kw: ("CLOSED", ""))
    monkeypatch.setattr(T, "surface_est_indisponible", lambda a: None)

    # MISTRAL et CLAUDE_HEADLESS passent par le harness -> ineligibles
    assert T._candidat_eligible("MISTRAL") is False
    assert T._candidat_eligible("CLAUDE_HEADLESS") is False

    # Une surface hors harness (ex: ANTIGRAVITY) reste eligible
    assert T._candidat_eligible("ANTIGRAVITY") is True


def test_reaffectation_ne_choisit_pas_voie_harness_si_pouls_perime(tmp_path, monkeypatch):
    monkeypatch.delenv("LAFORGE_HARNESS_POULS_IGNORE", raising=False)
    hb = tmp_path / "harness_worker.heartbeat"
    ts = (datetime.datetime.now() - datetime.timedelta(seconds=1000)).isoformat(timespec="seconds")
    hb.write_text(json.dumps({"ts": ts, "pid": 1}), encoding="utf-8")
    monkeypatch.setattr(T, "_HARNESS_HEARTBEAT", hb)

    # Base tasks SQLite factice
    db_file = tmp_path / "tasks.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, description TEXT, reaffectations TEXT)")
    conn.execute("INSERT INTO tasks VALUES ('job_115ff28d', 'OPENCODE_DEFAUT3', 'running', 'audit code', NULL)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(T, "_db", lambda: sqlite3.connect(db_file))
    monkeypatch.setattr(T, "_executeur_bat", lambda a: True)
    monkeypatch.setattr(T, "_executeur_suspendu", lambda a: False)
    monkeypatch.setattr(T, "_opencode_hors_quota", lambda a: False)
    monkeypatch.setattr(T, "statut_coupe_circuit", lambda a, **kw: ("CLOSED", ""))
    monkeypatch.setattr(T, "surface_est_indisponible", lambda a: None)

    task = {"id": "job_115ff28d", "agent": "OPENCODE_DEFAUT3", "description": "audit code"}
    # Ordre de repli proposant MISTRAL (voie harness tombee) puis ANTIGRAVITY
    choix = T._reaffecter(task, "NON LIVRE", ordre=("MISTRAL", "ANTIGRAVITY"))
    assert choix == "ANTIGRAVITY"
