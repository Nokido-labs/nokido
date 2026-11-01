"""NR 30/10 -- `task action=status` rend le statut REEL (tasks.db), pas celui de l'assignation (jobs_state).

Mesure : job_83b95c11 rendu « pending » par l'outil hub pendant que tasks.db disait « running » (bail jusqu'a 21:56,
exec_pid 25436) -- handle_task_status donnait la priorite a jobs_state, fige a l'assignation. STATUT DECLARE != REEL.
Desormais : statut de tasks.db quand la tache y est, et l'ecart se DIT dans `statut_jobs_state`.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import nokido_agent.app.forge_jobid as J  # noqa: E402
from nokido_agent.app.forge_mcp_registry import ToolRegistry  # noqa: E402

TID = "job_test_1_claude_handoff_next"


def _soi(tmp_path, statut_db):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT, description TEXT, agent TEXT, status TEXT, result TEXT, job_id TEXT, "
              "from_agent TEXT)")
    if statut_db:
        c.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?)", (TID, "d", "OPENCODE_GLM", statut_db, "", TID, "CLAUDE"))
    c.commit()
    c.close()
    return types.SimpleNamespace(_task_db=lambda: sqlite3.connect(db))


def _ctx(statut):
    return types.SimpleNamespace(job_id=TID, status=statut, agent="OPENCODE_GLM", intent_type="HANDOFF_NEXT",
                                 result_summary=None, error=None)


def test_le_statut_rendu_est_celui_de_tasks_db(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "load_job", lambda jid: _ctx("pending"))
    rep = json.loads(asyncio.run(ToolRegistry.handle_task_status(_soi(tmp_path, "running"), {"task_id": TID},
                                                                 "CLAUDE", 1)))
    assert rep["status"] == "running"
    assert rep["statut_jobs_state"] == "pending"


def test_sans_ligne_tasks_db_le_statut_jobs_state_reste(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "load_job", lambda jid: _ctx("pending"))
    rep = json.loads(asyncio.run(ToolRegistry.handle_task_status(_soi(tmp_path, None), {"task_id": TID},
                                                                 "CLAUDE", 1)))
    assert rep["status"] == "pending" and "statut_jobs_state" not in rep
