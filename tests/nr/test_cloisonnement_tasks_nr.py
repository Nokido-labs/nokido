"""NR 30/10 -- cloisonnement de tasks.db : un executeur ne RECLAME pas la tache d'un autre agent
(item P1_audit_cloisonnement_inter_llm_ponts_certifies_20261024, axe tasks.db).

Signatures lues (tools/forge_task_executor.py) :
  L1015 def _claim_enforce() -> bool                      (LAFORGE_CLAIM_ENFORCE == "1")
  L1021 def _autoriser_reclamation(agent_tache: str, identite: dict | None) -> tuple[bool, str]
  L1035 def _reclamer(conn, task_id, agent_tache, identite, enforce: bool = True) -> bool

TROU MESURE 30/10 : le refus d'un sujet non autorise ne s'APPLIQUE que sur LAFORGE_CLAIM_ENFORCE=1 (« observer avant
d'enforcer ») ; en production le journal dit « [claim][observe] refuserait » et la tache est prise quand meme. Le
dernier test le documente en xfail STRICT : il basculera le jour ou l'application sera le defaut. Rendu OPENCODE_GLM
(769501024) reecrit : `T` utilise avant import, monkeypatch sur un Path.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402

COLONNES = ("id TEXT PRIMARY KEY, description TEXT, agent TEXT, status TEXT, result TEXT, created_at TEXT, "
            "updated_at TEXT, job_id TEXT, from_agent TEXT, scorecard_json TEXT, lease_until TEXT, attempt INTEGER, "
            "checkpoint TEXT, progress_at TEXT, from_ring INTEGER")
B_PROUVE = {"sub": "AGENT_B", "act": "forge_task_executor", "prouve": True}


@pytest.fixture()
def base(tmp_path, monkeypatch):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (%s)" % COLONNES)
    c.execute("INSERT INTO tasks (id, description, agent, status, created_at) VALUES (?,?,?,?,?)",
              ("t_a", "tache de AGENT_A", "AGENT_A", "pending", "2026-10-30T20:00:00"))
    c.commit()
    c.close()
    monkeypatch.setattr(T, "TASKS_DB", db)
    monkeypatch.setattr(T, "_estampiller_proprietaire", lambda *a, **k: None)
    monkeypatch.setattr(T, "_publier_tache", lambda *a, **k: None)
    return db


def _statut(db):
    return sqlite3.connect(str(db)).execute("SELECT status FROM tasks WHERE id='t_a'").fetchone()[0]


def test_autre_agent_prouve_refuse_avec_le_motif_reel():
    ok, motif = T._autoriser_reclamation("AGENT_A", B_PROUVE)
    assert ok is False
    assert "n'est pas l'agent cible AGENT_A et n'a aucune delegation declaree pour lui" in motif


def test_identite_non_prouvee_refusee():
    ok, motif = T._autoriser_reclamation("AGENT_A", {"sub": "AGENT_A"})
    assert ok is False and "NON PROUVEE" in motif


def test_delegation_declaree_autorisee():
    ok, _ = T._autoriser_reclamation("AGENT_A", dict(B_PROUVE, servables=["agent_a"]))
    assert ok is True


def test_reclamation_appliquee_laisse_la_tache_pending(base):
    conn = T._db()
    try:
        assert T._reclamer(conn, "t_a", "AGENT_A", B_PROUVE, enforce=True) is False
    finally:
        conn.close()
    assert _statut(base) == "pending"


def test_le_proprietaire_prouve_reclame_sa_tache(base):
    conn = T._db()
    try:
        assert T._reclamer(conn, "t_a", "AGENT_A", {"sub": "AGENT_A", "prouve": True}, enforce=True) is True
    finally:
        conn.close()
    assert _statut(base) == "running"


@pytest.mark.xfail(strict=True, reason="TROU: tools/forge_task_executor.py:1018 -- refus en OBSERVATION par defaut "
                                       "(LAFORGE_CLAIM_ENFORCE absent) : la tache d'autrui est prise quand meme")
def test_par_defaut_la_tache_d_autrui_n_est_pas_prise(base, monkeypatch):
    monkeypatch.delenv("LAFORGE_CLAIM_ENFORCE", raising=False)
    conn = T._db()
    try:
        T._reclamer(conn, "t_a", "AGENT_A", B_PROUVE, enforce=T._claim_enforce())
    finally:
        conn.close()
    assert _statut(base) == "pending"
