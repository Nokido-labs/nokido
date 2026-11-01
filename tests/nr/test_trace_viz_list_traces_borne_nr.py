# -*- coding: utf-8 -*-
"""NR chasse aux lectures massives : forge_trace_viz.list_traces / exec_list_traces.

Avant : GROUP BY trace_id sur TOUTE la table (audit_log ~1,9 M lignes). Apres : le
GROUP BY est borne a une fenetre de rowid recente (_ECHANTILLON) calculee par
MAX(rowid) ; base illisible -> None (jamais [] qui dirait "aucune trace").
Base sqlite TEMPORAIRE, set_trace_callback.
"""
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_trace_viz as tv  # noqa: E402


def _group_by_non_borne(stmts):
    return [s for s in stmts if re.search(r"GROUP\s+BY", s, re.I) and not re.search(r"rowid\s*>", s, re.I)]


def test_list_traces_borne_et_fenetre(tmp_path, monkeypatch):
    db = str(tmp_path / "audit.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE audit_log(id INTEGER PRIMARY KEY, trace_id TEXT, ts REAL, duration_ms REAL, status INT)")
    # 30 anciennes lignes (trace 'vieux') puis 10 recentes (trace 'neuf')
    c.executemany("INSERT INTO audit_log(trace_id,ts,duration_ms,status) VALUES(?,?,1,200)",
                  [("vieux", i) for i in range(30)] + [("neuf", 100 + i) for i in range(10)])
    c.commit()
    c.close()
    stmts = []

    def fake_conn():
        k = sqlite3.connect(db)
        k.set_trace_callback(stmts.append)
        return k

    monkeypatch.setattr(tv, "_conn", fake_conn)
    monkeypatch.setattr(tv, "init_db", lambda: None)
    monkeypatch.setattr(tv, "_ECHANTILLON", 10)
    out = tv.list_traces(20)
    assert not _group_by_non_borne(stmts), _group_by_non_borne(stmts)
    assert [t["trace_id"] for t in out] == ["neuf"] and out[0]["spans"] == 10


def test_list_traces_illisible_none(monkeypatch):
    def boom():
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(tv, "_conn", boom)
    monkeypatch.setattr(tv, "init_db", lambda: None)
    assert tv.list_traces(5) is None


def test_exec_list_traces_borne_et_illisible(tmp_path, monkeypatch):
    db = str(tmp_path / "exec.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE traces(id INTEGER PRIMARY KEY, ts REAL, trace_id TEXT, action_json TEXT, task_type TEXT, success INT)")
    c.executemany("INSERT INTO traces(ts,trace_id,task_type,success) VALUES(?,?,?,1)",
                  [(i, "vieux", "x") for i in range(30)] + [(100 + i, "neuf", "x") for i in range(10)])
    c.commit()
    c.close()
    stmts = []

    def fake_ro():
        k = sqlite3.connect(db)
        k.set_trace_callback(stmts.append)
        return k

    monkeypatch.setattr(tv, "_exec_ro", fake_ro)
    monkeypatch.setattr(tv, "_ECHANTILLON", 10)
    out = tv.exec_list_traces(20)
    assert not _group_by_non_borne(stmts), _group_by_non_borne(stmts)
    assert [t["trace_id"] for t in out] == ["neuf"]

    def boom():
        raise sqlite3.OperationalError("x")

    monkeypatch.setattr(tv, "_exec_ro", boom)
    assert tv.exec_list_traces(5) is None
