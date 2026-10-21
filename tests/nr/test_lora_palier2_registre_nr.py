# -*- coding: utf-8 -*-
"""NR (lora_signal_usage_cause_2026-10-02, PALIER 2, derogation owner 19/10) : l'outil `rag` sert des morceaux CITABLES.

Palier 1 (cb5290873) : `ask` note et cite en interne. Les CLI externes (Claude Code, AGY, Vibe, OpenCode) appellent
l'outil `rag` puis ecrivent ailleurs : sans identifiant dans la sortie, rien ne peut etre rattache. Le repli BM25 -- qui
sert la majorite des recherches reelles -- n'appelait meme pas noter(). Desormais : chaque extrait porte `[chunk:<id>]`,
la recherche notee rend `[rag_recherche:<rid>]` en pied, et le BM25 note aussi. Interrupteur NOKIDO_RAG_SIGNAL (coupe par
le conftest des NR, rallume ici avec une doublure) : coupe, rien n'est note ni annonce.
"""
import inspect
import sqlite3

from nokido_agent.app import forge_mcp_registry as R
from nokido_agent.app import forge_rag_usage_signal as S


def _registre(tmp_path, monkeypatch):
    db = tmp_path / "rag.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, domain TEXT, text TEXT, embedding BLOB, "
              "active INTEGER, access_count INTEGER)")
    c.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED)")
    for cid, txt in (("c1", "Nengo simule des neurones impulsionnels"), ("c2", "Lava et Nengo pour le neuromorphique")):
        c.execute("INSERT INTO rag_chunks VALUES (?,?,?,?,NULL,1,0)", (cid, "doc/" + cid, "ia", txt))
        c.execute("INSERT INTO rag_fts VALUES (?,?,?,?)", (cid, txt, "doc/" + cid, "ia"))
    c.commit()
    c.close()
    reg = R.ToolRegistry.__new__(R.ToolRegistry)
    reg.db_path = db
    monkeypatch.setattr(reg, "_log_query", lambda *a, **k: None, raising=False)
    notes = []
    monkeypatch.setattr(S, "noter", lambda q, ids, scores=None, source="", mode="": notes.append((list(ids), source, mode))
                        or {"ok": True, "id": "rid42"})
    return reg, notes


def test_le_repli_bm25_note_et_rend_des_morceaux_citables(tmp_path, monkeypatch):
    reg, notes = _registre(tmp_path, monkeypatch)
    monkeypatch.setenv("NOKIDO_RAG_SIGNAL", "1")
    out = reg._rag_bm25_search("nengo neurones", 5)
    assert "[chunk:c1]" in out and "[chunk:c2]" in out
    assert out.rstrip().endswith("[rag_recherche:rid42]")
    assert notes and set(notes[0][0]) == {"c1", "c2"} and notes[0][1:] == ("handle_rag", "bm25")


def test_interrupteur_coupe_rien_n_est_note_ni_annonce(tmp_path, monkeypatch):
    reg, notes = _registre(tmp_path, monkeypatch)
    monkeypatch.setenv("NOKIDO_RAG_SIGNAL", "0")
    out = reg._rag_bm25_search("nengo neurones", 5)
    assert notes == [] and "[rag_recherche:" not in out and "[chunk:c1]" in out


def test_la_voie_dense_marque_aussi_ses_morceaux():
    src = inspect.getsource(R.ToolRegistry._rag_dense_search)
    assert "[chunk:" in src and "[rag_recherche:" in src and "NOKIDO_RAG_SIGNAL" in src
