# -*- coding: utf-8 -*-
"""NR chasse aux lectures massives : forge_trace_viz.audit_diag / exec_diag.

Avant : COUNT(*) / COUNT(DISTINCT) / GROUP BY sur TOUTE la table audit_log (1,9 M lignes)
a chaque diagnostic. Apres : MAX(rowid) (O(1)) + fenetre bornee des dernieres lignes ;
base illisible -> None (jamais 0). Base sqlite TEMPORAIRE, jamais la vraie.
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


def _audit_db(path, n=50):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE audit_log(id INTEGER PRIMARY KEY, trace_id TEXT, parent_id TEXT, action TEXT)")
    c.executemany("INSERT INTO audit_log(trace_id,parent_id,action) VALUES(?,?,?)",
                  [(f"t{i % 10}", "t1" if i % 2 else "", "a") for i in range(n)])
    c.commit()
    c.close()


def _massif(stmts):
    return [s for s in stmts if re.search(r"COUNT\s*\(", s, re.I) and not re.search(r"rowid\s*>", s, re.I)]


def test_audit_diag_aucun_comptage_massif(tmp_path, monkeypatch):
    db = str(tmp_path / "audit.db")
    _audit_db(db)
    stmts = []

    def fake_conn():
        c = sqlite3.connect(db)
        c.set_trace_callback(stmts.append)
        return c

    monkeypatch.setattr(tv, "_conn", fake_conn)
    monkeypatch.setattr(tv, "init_db", lambda: None)
    monkeypatch.setattr(tv, "_ECHANTILLON", 20, raising=False)
    d = tv.audit_diag()
    assert not _massif(stmts), _massif(stmts)
    assert d["rows"] == 50 and d["estimation"] is True and d["echantillon"] == 20


def test_audit_diag_illisible_est_none(monkeypatch):
    def boom():
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(tv, "_conn", boom)
    monkeypatch.setattr(tv, "init_db", lambda: None)
    d = tv.audit_diag()
    assert d["rows"] is None and d["distinct_traces"] is None


def test_exec_diag_aucun_comptage_massif_et_illisible(tmp_path, monkeypatch):
    db = str(tmp_path / "exec.db")
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE traces(id INTEGER PRIMARY KEY, ts REAL, trace_id TEXT, action_json TEXT, task_type TEXT, success INT)")
    c.executemany("INSERT INTO traces(ts,trace_id,task_type,success) VALUES(1,?,?,1)",
                  [(f"t{i % 5}", "x") for i in range(40)])
    c.commit()
    c.close()
    stmts = []

    def fake_ro():
        k = sqlite3.connect(db)
        k.set_trace_callback(stmts.append)
        return k

    monkeypatch.setattr(tv, "_exec_ro", fake_ro)
    monkeypatch.setattr(tv, "_ECHANTILLON", 10, raising=False)
    d = tv.exec_diag()
    assert not _massif(stmts), _massif(stmts)
    assert d["rows"] == 40

    def boom():
        raise sqlite3.OperationalError("x")

    monkeypatch.setattr(tv, "_exec_ro", boom)
    assert tv.exec_diag()["rows"] is None
