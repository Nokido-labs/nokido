# -*- coding: utf-8 -*-
"""NR — cooccurrence_score : rag_fts INDEXE au lieu de LIKE full-scan.

Mesure 2026-08-20 sur la vraie base (466k+ chunks) : l'ancien `text LIKE '%mot%'`
prenait 30,9 s (SCAN rag_chunks) par appel, appele PAR ARETE ; la version rag_fts
0,45 s (index FTS5) -> x69. Regle d'or Nokido : jamais de LIKE primitif -> rag_fts.
Tests HERMETIQUES : base sqlite en memoire, aucun reseau, aucune vraie base.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

import forge_edge_scoring as E  # noqa: E402


def _base(tmp, avec_fts: bool) -> str:
    db = str(tmp)
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE rag_chunks (id TEXT, text TEXT, source TEXT)")
    lignes = [("1", "active inference agent", "s1"),
              ("2", "world model ici", "s1"),
              ("3", "active inference", "s2"),
              ("4", "world model", "s2"),
              ("5", "autre chose", "s3")]
    if avec_fts:
        c.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(source, text)")
    for _id, t, s in lignes:
        c.execute("INSERT INTO rag_chunks VALUES (?,?,?)", (_id, t, s))
        if avec_fts:
            c.execute("INSERT INTO rag_fts (source, text) VALUES (?,?)", (s, t))
    c.commit()
    c.close()
    return db


def test_utilise_fts_et_compte_l_intersection_des_sources(tmp_path):
    db = _base(tmp_path / "r.db", avec_fts=True)
    # 'active inference' -> {s1, s2} ; 'world model' -> {s1, s2} ; inter = 2 sources
    score = E.cooccurrence_score("active inference", "world model", db)
    assert score == min(2 / 10.0, 1.0)


def test_pas_de_cooccurrence_si_sources_disjointes(tmp_path):
    db = _base(tmp_path / "r3.db", avec_fts=True)
    # 'active inference' -> {s1, s2} ; 'autre chose' -> {s3} ; inter = 0
    assert E.cooccurrence_score("active inference", "autre chose", db) == 0.0


def test_repli_like_si_rag_fts_absent(tmp_path):
    db = _base(tmp_path / "r2.db", avec_fts=False)  # pas de table rag_fts
    # s1 (active+world) ET s2 (active+world) -> LIKE compte 2 sources, comme le FTS.
    score = E.cooccurrence_score("active", "world", db)
    assert score == min(2 / 10.0, 1.0)


def test_mots_cles_vides_rendent_zero(tmp_path):
    db = _base(tmp_path / "r4.db", avec_fts=True)
    assert E.cooccurrence_score("", "world model", db) == 0.0


def test_sources_fts_none_si_table_absente(tmp_path):
    db = _base(tmp_path / "r5.db", avec_fts=False)
    c = sqlite3.connect(db)
    try:
        assert E._sources_fts(c, ["active", "inference"]) is None  # pas de rag_fts
    finally:
        c.close()
