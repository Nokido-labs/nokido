# -*- coding: utf-8 -*-
"""Test T1 ADAPT (memory_decay AGY) : la lecture RAG incremente access_count.

_log_query (choke point du chemin dense) doit incrementer access_count des ids
retournes — le signal que forge_auto_compact consomme (purge access_count<3).
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from forge_mcp_registry import ToolRegistry  # noqa: E402


def _tmp_db(tmp_path):
    db = tmp_path / "embeddings.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, access_count INTEGER DEFAULT 0)")
    con.executemany("INSERT INTO rag_chunks (id, text) VALUES (?, ?)",
                    [("c1", "alpha"), ("c2", "beta"), ("c3", "gamma")])
    con.commit()
    con.close()
    return db


def test_log_query_incremente_access_count(tmp_path):
    reg = ToolRegistry.__new__(ToolRegistry)
    reg.db_path = _tmp_db(tmp_path)

    reg._log_query("test topic", {}, ["c1", "c2"], 12)
    reg._log_query("test topic 2", {}, ["c1"], 8)

    con = sqlite3.connect(str(reg.db_path))
    counts = dict(con.execute("SELECT id, access_count FROM rag_chunks").fetchall())
    n_log = con.execute("SELECT COUNT(*) FROM query_log").fetchone()[0]
    con.close()

    assert counts == {"c1": 2, "c2": 1, "c3": 0}
    assert n_log == 2


def test_log_query_best_effort_sans_colonne(tmp_path):
    # DB sans access_count : la lecture ne doit JAMAIS casser (try/except global).
    db = tmp_path / "embeddings.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT)")
    con.execute("INSERT INTO rag_chunks (id, text) VALUES ('c1', 'alpha')")
    con.commit()
    con.close()

    reg = ToolRegistry.__new__(ToolRegistry)
    reg.db_path = db
    reg._log_query("topic", {}, ["c1"], 5)  # ne leve pas
