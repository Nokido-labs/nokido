"""NR RED -- choix owner du 9/11 : « requalifier + NR » pour le constat perpetuel `attestation_commit_anterieur`.

Mesure (sandbox/critical_events.db, ids 103003/103084) : la vieille tache AGY job_af6dbf75_1792605013_claude_handoff_next,
marquee done en citant 94e3c518b (anterieur de 10 min a sa creation, 0 commit), est re-emise en `high` a CHAQUE tick :
`_remesurer_attestation` rend SUSPECT pour toujours, car il relit la tache SANS regarder son statut. Une tache
requalifiee (status hors done/completed, ex. failed + cause_echec ATTESTATION_INVALIDE, resultat annote, rien
supprime) n'atteste plus rien : son constat est RESOLU, donc acquittable.
Contrat : app/forge_delivery_integrity._remesurer_attestation -> etat RESOLU si status not in ('done','completed').
Garde : une tache encore done garde son verdict actuel (jamais RESOLU par ce chemin). Aucun acces au RAG.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_delivery_integrity as D  # noqa: E402

SHA = "94e3c518b"


def _base(tmp_path, status):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, created_at TEXT, description TEXT, result TEXT)")
    res = json.dumps({"intent": "OK_DONE", "pointer_ref": "commit:%s" % SHA})
    c.execute("INSERT INTO tasks VALUES ('t1', 'ANTIGRAVITY', ?, '2026-10-22T10:00:00', 'consigne', ?)", (status, res))
    c.commit()
    c.close()
    return db


def test_tache_requalifiee_rend_le_constat_resolu(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "TASKS_DB", _base(tmp_path, "failed"))
    r = D._remesurer_attestation("t1:%s" % SHA)
    assert r["etat"] == "RESOLU", r
    assert "failed" in r["motif"], r


def test_tache_encore_done_jamais_resolue_par_ce_chemin(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "TASKS_DB", _base(tmp_path, "done"))
    r = D._remesurer_attestation("t1:%s" % SHA)
    assert r["etat"] != "RESOLU" or "ne cite plus" in r["motif"], r
