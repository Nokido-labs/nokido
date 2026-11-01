# -*- coding: utf-8 -*-
"""NR 2026-10-22 -- Une tache `RESERVE A <AGENT>` n'est jamais reaffectee (echec -> NEED_HUMAN_APPROVAL)."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as te  # noqa: E402


@pytest.mark.parametrize("desc,attendu", [
    ("RESERVE A CLAUDE_HEADLESS audit", "CLAUDE_HEADLESS"),
    ("  reserve   a claude_headless : x", "CLAUDE_HEADLESS"),
    ("audit RESERVE A X", None),
    ("", None),
    (None, None),
])
def test_reservee_a(desc, attendu):
    assert te._reservee_a(desc) == attendu


def _base(tmp_path, monkeypatch, desc):
    db = tmp_path / "tasks.db"
    monkeypatch.setattr(te, "TASKS_DB", db)
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, description TEXT, "
              "reaffectations TEXT, result TEXT)")
    c.execute("INSERT INTO tasks (id, agent, status, description) VALUES ('job_x','CLAUDE_HEADLESS','running',?)",
              (desc,))
    c.commit()
    c.close()
    monkeypatch.setattr(te, "_executeur_bat", lambda agent, **kw: True)
    te.reinitialiser_surfaces_indisponibles()
    return db


def _row(db):
    c = sqlite3.connect(str(db))
    r = c.execute("SELECT agent, status, result FROM tasks WHERE id='job_x'").fetchone()
    c.close()
    return r


def test_reservee_jamais_reaffectee(monkeypatch, tmp_path):
    db = _base(tmp_path, monkeypatch, "RESERVE A CLAUDE_HEADLESS : audit securite")
    task = {"id": "job_x", "agent": "CLAUDE_HEADLESS"}  # description lue en base
    assert te._reaffecter(task, "ECHEC AUTHENTIFICATION : 401 unauthorized", ordre=te._ORDRE_REPLI) is None
    agent, status, result = _row(db)
    assert agent == "CLAUDE_HEADLESS" and status == "failed"
    m2m = json.loads(result)
    assert m2m["intent"] == "NEED_HUMAN_APPROVAL"
    assert m2m["status_code"] == "RESERVEE_NON_REAFFECTABLE"
    assert m2m["pointer_ref"] and "401" in m2m["detail"]
    assert te.surface_est_indisponible("CLAUDE_HEADLESS") is None


def test_non_reservee_reaffectee(monkeypatch, tmp_path):
    db = _base(tmp_path, monkeypatch, "audit securite ordinaire")
    task = {"id": "job_x", "agent": "CLAUDE_HEADLESS", "description": "audit securite ordinaire"}
    vers = te._reaffecter(task, "NON LIVRE apres delegation", ordre=te._ORDRE_REPLI)
    assert vers
    agent, status, _ = _row(db)
    assert agent == vers != "CLAUDE_HEADLESS" and status == "pending"
