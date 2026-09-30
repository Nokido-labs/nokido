"""NR -- une mission en vol sans progression est REPRISE, une fois, puis abandonnee (veille lot_B_25).

La fiche du 24/09 jugeait le bail « jamais arme » en lisant `lease_until: None` sur les taches AGY.
Mesure du meme jour dans le bus vivant : la reprise NE DEPEND PAS de `lease_until` --
`reclaim_expired` date la derniere progression par `COALESCE(progress_at, updated_at, created_at)` --
et elle a deja servi (3 taches `attempt > 0`, 1 abandon `[lease]`). Le seul NR existant
(`test_reliability_kernel_nr`) ne verifiait que la PRESENCE des colonnes, sur la base vivante, et
n'etait declare nulle part. Celui-ci garde le COMPORTEMENT, sur une base fabriquee au schema reel.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import forge_task_executor as fte  # noqa: E402 -- pas d'importorskip sur un livrable (faux vert)

SCHEMA = ("CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT, agent TEXT, status TEXT DEFAULT 'pending', "
          "result TEXT, created_at TEXT, updated_at TEXT, job_id TEXT, from_agent TEXT, scorecard_json TEXT, "
          "lease_until TEXT, attempt INTEGER DEFAULT 0, checkpoint TEXT DEFAULT '{}', progress_at TEXT, "
          "from_ring INTEGER)")


def _ts(delta_s: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + delta_s))


@pytest.fixture()
def bus(tmp_path, monkeypatch):
    db = tmp_path / "tasks.db"
    con = sqlite3.connect(db)
    con.execute(SCHEMA)
    rows = [
        ("morte", "ANTIGRAVITY", "running", 0, _ts(-7200), '{"lot": 3}'),   # 2 h sans progression
        ("vivante", "ANTIGRAVITY", "running", 0, _ts(-60), "{}"),           # progression recente
        ("finie", "ANTIGRAVITY", "done", 0, _ts(-7200), "{}"),               # hors vol : intouchable
        ("usee", "WORKER_CODE", "claimed", 3, _ts(-7200), "{}"),             # 3 reprises deja
    ]
    for tid, agent, st, att, prog, ck in rows:
        con.execute("INSERT INTO tasks (id, agent, status, attempt, progress_at, updated_at, created_at, checkpoint) "
                    "VALUES (?,?,?,?,?,?,?,?)", (tid, agent, st, att, prog, prog, prog, ck))
    con.commit()
    con.close()
    monkeypatch.setattr(fte, "TASKS_DB", db)
    return db


def _etat(db, tid):
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT status, attempt, lease_until, checkpoint, COALESCE(result,'') FROM tasks WHERE id=?",
                           (tid,)).fetchone()
    finally:
        con.close()


def test_mission_morte_reprise_une_fois_avec_son_checkpoint(bus):
    r = fte.reclaim_expired(timeout_s=1800)
    assert r["reprises"] == 1 and r["detail"][0]["id"] == "morte"
    st, att, bail, ck, _ = _etat(bus, "morte")
    assert (st, att, bail) == ("pending", 1, None)
    assert ck == '{"lot": 3}', "une reprise ne repart pas de zero : le checkpoint est conserve"
    assert fte.reclaim_expired(timeout_s=1800)["reprises"] == 0, "reprise UNE fois : pending n'est plus en vol"


def test_mission_vivante_et_mission_finie_intouchees(bus):
    fte.reclaim_expired(timeout_s=1800)
    assert _etat(bus, "vivante")[:2] == ("running", 0)
    assert _etat(bus, "finie")[:2] == ("done", 0)


def test_au_dela_du_plafond_la_mission_est_abandonnee_et_le_dit(bus):
    r = fte.reclaim_expired(timeout_s=1800)
    assert r["abandonnees"] == 1
    st, att, _, _, res = _etat(bus, "usee")
    assert st == "failed" and att == 4 and res.startswith("[lease] abandonnee")


def test_touch_progress_prolonge_le_bail(bus):
    fte.touch_progress("morte", checkpoint='{"lot": 4}')
    assert fte.reclaim_expired(timeout_s=1800)["reprises"] == 0
    st, _, bail, ck, _ = _etat(bus, "morte")
    assert st == "running" and bail and ck == '{"lot": 4}'
