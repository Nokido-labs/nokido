"""NR -- au demarrage, l'executeur requalifie ses taches `running` sans proprietaire VIVANT (job_30921191, 22/10).

Vivacite PROUVEE (pid + heure de creation) ; illisible = abstention ; journalise ; aucun vrai processus tue.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402


def _base(tmp_path, monkeypatch, lignes):
    p = tmp_path / "tasks.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, updated_at TEXT, created_at TEXT, "
              "result TEXT, exec_pid INTEGER, exec_cree REAL)")
    for l in lignes:
        c.execute("INSERT INTO tasks (id,agent,status,exec_pid,exec_cree) VALUES (?,?,?,?,?)", l)
    c.commit()
    c.close()
    monkeypatch.setattr(T, "TASKS_DB", p)
    return p


def _etats(p):
    c = sqlite3.connect(p)
    r = dict(c.execute("SELECT id,status FROM tasks").fetchall())
    c.close()
    return r


def test_seule_l_orpheline_est_requalifiee(tmp_path, monkeypatch, caplog):
    p = _base(tmp_path, monkeypatch, [("orph", "A", "running", 111, 1.0),
                                      ("vive", "A", "running", 222, 2.0),
                                      ("autre", "B", "running", 333, 3.0)])
    sonde = lambda pid, cree: pid == 222  # noqa: E731
    with caplog.at_level(logging.WARNING):
        r = T.requalifier_orphelines("A", vivacite=sonde)
    assert _etats(p) == {"orph": "pending", "vive": "running", "autre": "running"}
    assert r["requalifiees"] == ["orph"]
    assert "orph" in caplog.text


def test_illisible_ne_touche_rien(tmp_path, monkeypatch):
    p = _base(tmp_path, monkeypatch, [("x", "A", "running", 111, 1.0),
                                      ("y", "A", "running", None, None)])
    r = T.requalifier_orphelines("A", vivacite=lambda pid, cree: None)
    assert _etats(p) == {"x": "running", "y": "running"}
    assert r["requalifiees"] == []
