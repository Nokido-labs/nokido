"""NR -- la page /epistemic du portail rend les MEMES faits sans parcourir rag_chunks.

Mesure du 2026-09-24 (chantier UI) : `test_ui_pages_rendent_nr` restait bloque dans
`_conflicts_top` jusqu'au delai de pytest. EXPLAIN sur la base reelle : le planificateur partait
de rag_chunks par l'index non selectif `active` (`MULTI-INDEX OR`) pour joindre 169
revendications ; `_topic_chunks` faisait un `LIKE '%sujet%'` sur toutes les lignes actives.
Les PLANS sont gardes par `test_chemin_chaud_sans_balayage_nr` (epistemic.py y est declare).
Ce NR-ci garde le SENS apres reecriture, sur une base fabriquee au schema reel :
  1. un chunk retire (`active = 0`) n'apparait nulle part ; `active` NULL = jamais retire ;
  2. les conflits comptent les refutations (contradicts / supersedes), pas les soutiens ;
  3. le sujet passe par l'index lexical MAINTENU (`rag_fts`) et le tri reste par poids ;
  4. un sujet sans mot ne lance aucune requete (rien a chercher n'est pas « tout »).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.app.web_hub import epistemic as ep  # noqa: E402

SCHEMA = """
CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL, domain TEXT,
  role_hint TEXT, epistemic_weight REAL, active INTEGER, ingested_at TEXT, version INTEGER, embedding BLOB);
CREATE INDEX idx_rag_chunks_active ON rag_chunks(active);
CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED);
CREATE TABLE chunk_claims (id TEXT PRIMARY KEY, chunk_id TEXT NOT NULL, text TEXT NOT NULL, predicates TEXT,
  confidence_authored REAL, is_technical INTEGER, abstract_embedding BLOB, extracted_by TEXT, extracted_at TEXT);
CREATE INDEX idx_chunk_claims_chunk ON chunk_claims(chunk_id);
CREATE TABLE claim_reevaluations (older_claim_id TEXT NOT NULL, newer_claim_id TEXT NOT NULL,
  reevaluation_type TEXT NOT NULL, confidence REAL, rationale TEXT, detected_by TEXT, detected_at TEXT,
  PRIMARY KEY (older_claim_id, newer_claim_id));
CREATE INDEX idx_reeval_older ON claim_reevaluations(older_claim_id, reevaluation_type);
"""
CHUNKS = [  # id, text, weight, active
    ("k1", "le laser pulse traverse le verre", 0.9, 1),
    ("k2", "un laser continu chauffe la cible", 0.4, None),
    ("k3", "laser retire de la base", 0.99, 0),
    ("k4", "sans rapport avec le sujet", 0.8, 1),
]


def _base(tmp_path) -> Path:
    p = tmp_path / "epi.db"
    con = sqlite3.connect(p)
    con.executescript(SCHEMA)
    for cid, txt, w, act in CHUNKS:
        con.execute("INSERT INTO rag_chunks(id,text,source,domain,role_hint,epistemic_weight,active,version) "
                    "VALUES (?,?,?,?,?,?,?,1)", (cid, txt, "src/" + cid, "physique", "chat", w, act))
        con.execute("INSERT INTO rag_fts(chunk_id,text,source,domain) VALUES (?,?,?,?)", (cid, txt, "src/" + cid, "physique"))
    con.executemany("INSERT INTO chunk_claims(id,chunk_id,text,predicates) VALUES (?,?,?,?)", [
        ("c1", "k1", "le laser traverse", '["traverse"]'),
        ("c2", "k2", "le laser chauffe", '["chauffe"]'),
        ("c3", "k3", "claim retire", '["retire"]'),
        ("c9", "k4", "plus recente", '["autre"]'),
    ])
    con.executemany("INSERT INTO claim_reevaluations(older_claim_id,newer_claim_id,reevaluation_type) VALUES (?,?,?)", [
        ("c1", "c9", "supersedes"), ("c2", "c9", "supports"), ("c3", "c9", "contradicts"),
    ])
    con.commit()
    con.close()
    return p


def _brancher(monkeypatch, chemin: Path):
    def _conn():
        c = sqlite3.connect(chemin)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(ep, "_conn", _conn)


def test_conflits_refutations_seulement_et_retires_exclus(monkeypatch, tmp_path):
    _brancher(monkeypatch, _base(tmp_path))
    top = ep._conflicts_top(20)
    assert [r["chunk_id"] for r in top] == ["k1"], top  # c2 = supports ; c3 = chunk retire
    assert top[0]["n_refutations"] == 1


def test_sujet_par_index_lexical_tri_par_poids_retire_exclu(monkeypatch, tmp_path):
    _brancher(monkeypatch, _base(tmp_path))
    ids = [r["id"] for r in ep._topic_chunks("laser", limit=10)]
    assert ids == ["k1", "k2"], ids  # k3 retire (active=0), k2 active NULL = jamais retire


def test_heatmap_ne_compte_que_les_revendications_actives(monkeypatch, tmp_path):
    _brancher(monkeypatch, _base(tmp_path))
    preds = {r["predicate"] for r in ep._heatmap_predicates("laser")}
    assert preds == {"traverse", "chauffe"}, preds


def test_sujet_sans_mot_ne_lance_rien(monkeypatch, tmp_path):
    appels = []
    monkeypatch.setattr(ep, "_conn", lambda: appels.append(1))
    assert ep._topic_chunks("  ?! ") == [] and appels == []
