"""NR -- les transitions de tache (running, terminee) sont PUBLIEES sur le bus d'essaim (forge_swarm_bus).

Item SSoT p1_swarm_en_direct_graphique_2026-10-14 ; mesure 19/10 03:04 : sandbox/reflexion.jsonl (miroir du bus, suivi
par /api/swarm/stream) vivant mais SANS aucun task_* : le travail des executeurs etait invisible au flux. L'executeur
publie `task_running` et `task_done` (agent, statut) ; best-effort, ne casse jamais la transition ; interrupteur
NOKIDO_BUS_TACHES coupe par le conftest (aucun test n'ecrit le vrai miroir).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402


def _base(tmp_path):
    con = sqlite3.connect(tmp_path / "t.db")
    con.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, result TEXT, updated_at TEXT, description TEXT)")
    con.execute("INSERT INTO tasks VALUES ('job_x', 'ANTIGRAVITY', 'pending', NULL, NULL, 'd')")
    con.commit()
    return con


def _capture(monkeypatch):
    vus = []
    import nokido_agent.app.forge_swarm_bus as B
    monkeypatch.setattr(B, "publish", lambda kind, data=None, topic="swarm": vus.append((kind, data, topic)))
    monkeypatch.setenv("NOKIDO_BUS_TACHES", "1")
    return vus


def test_running_et_done_sont_publies(tmp_path, monkeypatch):
    vus = _capture(monkeypatch)
    con = _base(tmp_path)
    T._mark_running(con, "job_x")
    T._mark_done(con, "job_x", "resultat", False)
    kinds = [k for k, _, _ in vus]
    assert kinds == ["task_running", "task_done"]
    assert vus[0][1]["agent"] == "ANTIGRAVITY" and vus[1][1]["statut"] == "failed"


def test_la_reclamation_publie_task_running(tmp_path, monkeypatch):
    """Constat 19/10 03:33 : la voie AGY reclame par `_reclamer` (pas `_mark_running`) -> aucun task_running au bus."""
    vus = _capture(monkeypatch)
    con = _base(tmp_path)
    assert T._reclamer(con, "job_x", "ANTIGRAVITY", None, enforce=False) is True
    assert [k for k, _, _ in vus] == ["task_running"] and vus[0][1]["agent"] == "ANTIGRAVITY"


def test_un_bus_qui_leve_ne_casse_pas_la_transition(tmp_path, monkeypatch):
    import nokido_agent.app.forge_swarm_bus as B

    def boom(*a, **k):
        raise OSError("miroir illisible")
    monkeypatch.setattr(B, "publish", boom)
    monkeypatch.setenv("NOKIDO_BUS_TACHES", "1")
    con = _base(tmp_path)
    T._mark_running(con, "job_x")
    assert con.execute("SELECT status FROM tasks").fetchone()[0] == "running"


def test_le_conftest_coupe_le_bus_des_tests():
    import os
    assert os.environ.get("NOKIDO_BUS_TACHES") == "0"
