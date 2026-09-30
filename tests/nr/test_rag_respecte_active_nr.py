# -*- coding: utf-8 -*-
"""NR 2026-09-23 — la recherche RAG respecte `active` (decision owner, option 1).

Mesure : seul forge_epistemic_retrieve filtrait `active`. Le moteur principal
chargeait TOUT rag_chunks dans self.chunks : un chunk marque active=0 restait
trouvable (dense ET lexical, le lexical se rattachant via self.chunks). Marquer
les 633 408 chunks de pxpipe (resultats d'evaluation) n'aurait rien change —
et leur chargement pese sur la RAM du hub.
"""
import sqlite3
import threading

import pytest

from nokido_agent.app import forge_rag_engine as re_mod

COLS = "id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT, role_hint TEXT, " \
       "embedding BLOB, meta TEXT, quality_score REAL"


def _base(tmp_path, avec_active=True):
    db = tmp_path / "e.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE rag_chunks (%s%s)" % (COLS, ", active INTEGER" if avec_active else ""))
    lignes = [("vif", 1), ("mort", 0), ("ancien", None)] if avec_active else [("vif",), ("mort",)]
    for l in lignes:
        if avec_active:
            c.execute("INSERT INTO rag_chunks (id, text, source, domain, active) VALUES (?,?,?,?,?)",
                      (l[0], "texte " + l[0], "s/" + l[0], "d", l[1]))
        else:
            c.execute("INSERT INTO rag_chunks (id, text, source, domain) VALUES (?,?,?,?)",
                      (l[0], "texte " + l[0], "s/" + l[0], "d"))
    c.commit()
    c.close()
    return db


def _moteur(tmp_path, db, monkeypatch):
    monkeypatch.setenv("LAFORGE_VEC_SIDECAR_PORT", "1")        # pas de blobs vecteurs
    monkeypatch.setattr(re_mod, "_db_connect", lambda *a, **k: sqlite3.connect(db))
    e = re_mod.RAGEngine.__new__(re_mod.RAGEngine)
    e._chunks_lock = threading.RLock()
    e.expected_dim = 1024
    e.rag_dir = tmp_path
    e.emb_file = tmp_path / "absent.json"
    e.chunks = []
    return e


def test_le_chargement_exclut_les_chunks_inactifs(tmp_path, monkeypatch):
    e = _moteur(tmp_path, _base(tmp_path), monkeypatch)
    e._load_embeddings()
    assert sorted(c["id"] for c in e.chunks) == ["ancien", "vif"]   # NULL = actif


def test_base_sans_colonne_active_charge_tout_sans_basculer(tmp_path, monkeypatch):
    """Une base sans la colonne ne doit PAS faire echouer le SELECT : l'echec
    basculerait en silence vers les anciens formats (arrow/json)."""
    e = _moteur(tmp_path, _base(tmp_path, avec_active=False), monkeypatch)
    e._load_embeddings()
    assert sorted(c["id"] for c in e.chunks) == ["mort", "vif"]


def test_le_lexical_ne_rend_pas_un_chunk_inactif(tmp_path, monkeypatch):
    db = _base(tmp_path)
    c = sqlite3.connect(db)
    c.execute("CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, content='rag_chunks', "
              "content_rowid='rowid')")
    c.execute("INSERT INTO rag_chunks_fts(rag_chunks_fts) VALUES ('rebuild')")
    c.commit()
    c.close()
    e = _moteur(tmp_path, db, monkeypatch)
    monkeypatch.setattr(re_mod, "_EMBEDDINGS_DB", db)
    e._load_embeddings()
    scores = e._scores_lexicaux("texte")
    ids_touches = {e.chunks[i]["id"] for i, s in enumerate(scores) if s}
    assert "mort" not in ids_touches and "vif" in ids_touches
