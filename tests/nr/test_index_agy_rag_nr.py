"""NR -- l'indexeur RAG AGY : schema reel (USER_EXPLICIT/MODEL/SYSTEM) et echec jamais masque."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import forge_conv_indexer as ci  # noqa: E402


def _db(tmp_path):
    db = tmp_path / "r.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, text TEXT, domain TEXT, "
              "ingested_at TEXT, created_at TEXT, active INT DEFAULT 1, retraction_status TEXT)")
    c.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id, source, text)")
    c.commit()
    c.close()
    return db


def _brain(tmp_path):
    logs = tmp_path / "brain" / "u1" / ".system_generated" / "logs"
    logs.mkdir(parents=True)
    rows = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-24T10:00:00Z",
         "content": "question sur le routeur de la forge, longue assez"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "created_at": "2026-10-24T10:00:01Z",
         "content": "reponse detaillee sur le routeur de la forge et son comportement observe en production", "thinking": "SECRETPENSEE"},
    ]
    (logs / "transcript.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return tmp_path / "brain"


def test_agy_indexe_fts_et_roles_normalises(tmp_path, monkeypatch):
    db = _db(tmp_path)
    monkeypatch.setattr(ci, "RAG_DB", db)
    r = ci.index_agy_sessions(brain_dir=_brain(tmp_path))
    assert r["ok"] and r["inserted"] >= 1, r
    cx = sqlite3.connect(db)
    txt = " ".join(x[0] for x in cx.execute("SELECT text FROM rag_chunks"))
    assert "[user]" in txt and "[assistant]" in txt, txt
    assert "USER_EXPLICIT" not in txt and "SECRETPENSEE" not in txt
    assert cx.execute("SELECT count(*) FROM rag_fts WHERE rag_fts MATCH 'source:agy'").fetchone()[0] >= 1


def test_echec_agy_ne_marque_pas_la_passe_complete(tmp_path, monkeypatch):
    db = _db(tmp_path)
    monkeypatch.setattr(ci, "RAG_DB", db)
    monkeypatch.setattr(ci, "doit_differer", lambda *a, **k: (False, "test"))
    monkeypatch.setattr(ci, "index_gemini_sessions", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(ci, "index_codex_sessions", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(ci, "index_agy_sessions", lambda *a, **k: {"ok": False, "error": "acces refuse"})
    etat = tmp_path / "etat.json"
    ci.index_incremental(etat, tmp_path / "vide")
    assert "_derniere_complete" not in json.loads(etat.read_text(encoding="utf-8"))
