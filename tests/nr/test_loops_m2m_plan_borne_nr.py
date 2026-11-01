"""NR : lectures massives de agent_messages dans forge_autonomous_loops.

Base temoin au schema M2M ; on verifie le PLAN (pas de SCAN de la table) et la reponse.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SCHEMA = """
CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT NOT NULL,
 to_agent TEXT NOT NULL, correlation_id TEXT, method TEXT NOT NULL, payload TEXT,
 result TEXT, status TEXT DEFAULT 'pending', created_at TEXT DEFAULT (datetime('now')),
 read_at TEXT);
CREATE INDEX idx_agent_messages_created_at ON agent_messages(created_at);
CREATE INDEX idx_agent_messages_method ON agent_messages(method);
CREATE INDEX idx_agent_messages_from_agent ON agent_messages(from_agent);
"""


@pytest.fixture()
def loops(tmp_path, monkeypatch):
    from app import forge_autonomous_loops as L
    db = tmp_path / "m2m.db"
    c = sqlite3.connect(db)
    c.executescript(SCHEMA)
    rows = []
    for i in range(12000):
        ancien = i < 6000
        fa = "ANTIGRAVITY" if i % 7 == 0 else "x"
        rows.append((f"id{i}", fa, "claude", f"m{i % 3}", f"p{i}",
                     "2020-01-01 00:00:00" if ancien else f"2026-10-{1 + i % 20:02d} 10:00:00"))
    c.executemany("INSERT INTO agent_messages(id,from_agent,to_agent,method,payload,created_at)"
                  " VALUES (?,?,?,?,?,?)", rows)
    c.commit()
    c.close()
    monkeypatch.setattr(L, "m2m_path", lambda: str(db))
    return L, db


def _plan(db, sql, params=()):
    c = sqlite3.connect(db)
    try:
        return " | ".join(r[-1] for r in c.execute("EXPLAIN QUERY PLAN " + sql, params))
    finally:
        c.close()


def test_frames_plan_et_reponse(loops):
    L, db = loops
    seen = []
    real = sqlite3.connect

    class Spy:
        def __init__(self, c):
            self.c = c

        def execute(self, sql, *a):
            if "upper(from_agent)" in sql:
                seen.append((sql, a[0] if a else ()))
            return self.c.execute(sql, *a)

        def close(self):
            self.c.close()

    L.sqlite3 = type("S", (), {"connect": staticmethod(lambda *a, **k: Spy(real(*a, **k)))})
    try:
        r = L._frames_du_pair("2026-10-01 00:00:00")
    finally:
        L.sqlite3 = sqlite3
    assert seen, "requete frames non observee"
    sql, params = seen[0]
    assert "SCAN agent_messages" not in _plan(db, sql, params)
    ids = {row[0] for row in r}
    assert ids and all(int(i[2:]) >= 7000 for i in ids)  # fenetre 5000 : l'ancien est ecarte


def test_tool_effectiveness_plan(loops):
    L, db = loops
    import inspect
    assert "INDEXED BY idx_agent_messages_created_at" in inspect.getsource(L.pat_tool_effectiveness)
    sql = ("SELECT method, COUNT(*) FROM agent_messages INDEXED BY idx_agent_messages_created_at "
           "WHERE created_at > datetime(?, 'unixepoch') GROUP BY method")
    assert "SEARCH agent_messages USING INDEX idx_agent_messages_created_at" in _plan(db, sql, (1,))
