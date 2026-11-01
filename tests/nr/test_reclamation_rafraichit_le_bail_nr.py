"""NR -- reclamer une tache rafraichit son bail : une autre instance ne la « reprend » plus 28 ms plus tard.

Mesure 24/10 23:00:48 : l'executeur Claude reclame job_b33fd7c4 (pending -> running, .671) ; a .699, l'instance
OpencodeNemotron (reclaim_expired) la voit `running` avec le progress_at de la tentative PRECEDENTE (> 1800 s) et la
remet en pending -- elle tourne pourtant (battement a 23:00:49). Toute tache requalifiee (orpheline, relancee) garde
son vieux progress_at, et reclaim_expired juge sur COALESCE(progress_at, updated_at, created_at) : `_reclamer` ne
posait que updated_at. Contrat : apres `_reclamer`, `reclaim_expired` ne reprend pas la tache.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402


def _base(tmp_path):
    chemin = tmp_path / "tasks.db"
    c = sqlite3.connect(chemin)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT, agent TEXT, status TEXT, result TEXT, "
              "created_at TEXT, updated_at TEXT, job_id TEXT, lease_until TEXT, attempt INTEGER, checkpoint TEXT, "
              "progress_at TEXT, exec_pid TEXT, exec_cree TEXT)")
    vieux = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 3 * 3600))
    c.execute("INSERT INTO tasks (id, description, agent, status, created_at, updated_at, attempt, progress_at) "
              "VALUES ('t_relancee', 'x', 'CLAUDE_HEADLESS', 'pending', ?, ?, 2, ?)", (vieux, vieux, vieux))
    c.commit()
    c.close()
    return chemin


def test_une_tache_reclamee_n_est_pas_reprise_par_une_autre_instance(tmp_path, monkeypatch):
    chemin = _base(tmp_path)

    def _db():
        conn = sqlite3.connect(chemin)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(T, "_db", _db)
    monkeypatch.setattr(T, "_estampiller_proprietaire", lambda conn, task_id: None)
    monkeypatch.setattr(T, "_publier_tache", lambda conn, kind, task_id, statut: None)
    conn = _db()
    assert T._reclamer(conn, "t_relancee", "CLAUDE_HEADLESS", None, enforce=False) is True
    conn.close()
    r = T.reclaim_expired()
    assert r["reprises"] == 0, r
    conn = _db()
    assert conn.execute("SELECT status FROM tasks WHERE id='t_relancee'").fetchone()[0] == "running"
    conn.close()
