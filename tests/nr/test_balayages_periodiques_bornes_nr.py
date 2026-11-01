"""NR -- les balayages periodiques de rag_chunks sont bornes (P2 coagulation vital, reste (3), 24/10).

Trois sites accuses : forge_resource_manager._backlog_embeddings, forge_heartbeat._rag_stats_fast,
forge_health_diagnostic._audit_rag_chunks_mesure. Les plans sont figes sur une base TEMOIN au schema
reel (jamais la base vivante) : aucun `SCAN rag_chunks`, aucun `TEMP B-TREE`.
"""

from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _temoin(n=300):
    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT,"
        " embedding BLOB, hash TEXT, quality_score REAL, meta TEXT);"
        "CREATE INDEX idx_domain ON rag_chunks(domain);"
        "CREATE INDEX idx_embedding_null ON rag_chunks(id) WHERE embedding IS NULL;"
    )
    for i in range(n):
        con.execute("INSERT INTO rag_chunks VALUES (?,?,?,?,?,?,?,?)",
                    ("c%d" % i, "t", "s", "d%d" % (i % 3), None if i % 2 else b"x" * 8,
                     "h%d" % i, 0.5, "{}"))
    con.commit()
    return con


class _Rec:
    def __init__(self, con):
        self.con, self.sql = con, []

    def execute(self, sql, params=()):
        self.sql.append((sql, tuple(params)))
        return self.con.execute(sql, params)


def _plans_fautifs(con, sqls):
    fautifs = []
    for sql, params in sqls:
        if not sql.strip().upper().startswith("SELECT"):
            continue
        plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql, params)]
        # Borne declaree : un LIMIT (arret anticipe) ou une fenetre de rowid (SEARCH sur la cle) ;
        # un TEMP B-TREE n'est tolere que SUR une fenetre de rowid.
        borne_limit = "LIMIT" in sql.upper()
        fenetre = any("SEARCH rag_chunks USING INTEGER PRIMARY KEY (rowid>" in l for l in plan)
        scan = any("SCAN rag_chunks" in l for l in plan) and not borne_limit
        temp = any("TEMP B-TREE" in l for l in plan) and not fenetre
        if scan or temp:
            fautifs.append((" ".join(sql.split())[:110], plan))
    return fautifs


def test_sante_mesure_sans_scan_ni_temp_btree():
    hd = pytest.importorskip("nokido_agent.app.forge_health_diagnostic")
    con = _temoin()
    rec = _Rec(con)
    r = hd._audit_rag_chunks_mesure(rec)
    rag = [(s, p) for s, p in rec.sql if "rag_chunks" in s]
    assert rag, "aucune requete rag_chunks observee"
    assert not _plans_fautifs(con, rag), _plans_fautifs(con, rag)
    # le sens reste dit : mesure sur fenetre, jamais un 0 invente
    assert r["non_vectorized"] == 150 and r["vectorized"] == 150, r
    assert {d["domain"] for d in r["top_domains"]} == {"d0", "d1", "d2"}
    assert "fenetre" in str(r.get("dette_statut", "")).lower(), r.get("dette_statut")


def test_heartbeat_compte_par_seek(monkeypatch):
    pytest.importorskip("nokido_agent.app.forge_heartbeat")
    import nokido_agent.app.forge_heartbeat as hb

    con = _temoin()
    vus = []

    class _Db:
        def scalar(self, sql, *a):
            vus.append((sql, ()))
            if "rag_chunks" not in sql:
                return None
            return con.execute(sql).fetchone()[0]

    mod = types.ModuleType("nokido_agent.app.forge_db")
    mod.db = _Db()
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_db", mod)
    out = hb._rag_stats_fast()
    rag = [(s, p) for s, p in vus if "rag_chunks" in s]
    assert rag and not _plans_fautifs(con, rag), _plans_fautifs(con, rag)
    assert out["db_chunks"] == 300, out


def test_resource_manager_ne_touche_pas_la_base(monkeypatch):
    rm = pytest.importorskip("nokido_agent.app.forge_resource_manager")

    def _interdit(*a, **k):
        raise AssertionError("connexion SQLite depuis un chemin periodique")

    monkeypatch.setattr(sqlite3, "connect", _interdit)
    monkeypatch.setattr(rm, "_backlog_pending_qualifie", lambda: (77, 1.0, "snapshot"))
    assert rm._backlog_embeddings() == 77
    monkeypatch.setattr(rm, "_backlog_pending_qualifie", lambda: (-1, None, "INCONNU (x)"))
    assert rm._backlog_embeddings() == -1
