# -*- coding: utf-8 -*-
"""NR owner 4/11 (« il FAUT savoir ce qui le provoque ») : rafales de 30 Mo du hub toutes les 10,4 s.

Chaine mesuree : le tray appelle get_mode toutes les ~10 s -> post_dispatch -> _query_inbox("TRAY") sur le fil principal.
La requete passait par l'index `status` : pour un agent sans message, SQLite parcourait tous les `unread` de tous les
agents (19 782 pour EVENTBUS_ARCHIVE), soit 7 330 lectures de 4 Ko. Sur une copie de la base, l'index partiel ramene ce
pire cas a 5 lectures.
"""
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "tools"), str(RACINE / "app")]
H = importlib.import_module("hub_lifecycle_hooks")


@pytest.fixture
def base(tmp_path, monkeypatch):
    p = tmp_path / "m2m.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, status TEXT, payload TEXT, created_at TEXT)")
    c.execute("CREATE INDEX idx_agent_messages_status ON agent_messages(status)")
    c.execute("CREATE INDEX idx_agent_messages_to ON agent_messages(to_agent)")
    c.executemany("INSERT INTO agent_messages VALUES (?,?,?,?,?,?)",
                  [("a%d" % i, "x", "EVENTBUS_ARCHIVE", "unread", "p", "t") for i in range(50)]
                  + [("m1", "agy", "agt_claude", "unread", "bonjour", "t"), ("m2", "agy", "claude", "read", "lu", "t")])
    c.commit()
    c.close()
    monkeypatch.setattr(H, "_m2m", lambda: p)
    monkeypatch.setattr(H, "_DB", p)
    monkeypatch.setattr(H, "_INDEX_NONLUS_TENTE", False)
    return p


def _plan(p):
    c = sqlite3.connect(p)
    try:
        return " ".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN " + H.SQL_INBOX, ("a", "b", 3)))
    finally:
        c.close()


def test_la_requete_ne_parcourt_plus_les_non_lus_des_autres(base):
    H._query_inbox("TRAY")
    assert "idx_agent_messages_nonlus" in _plan(base)


def test_les_messages_de_l_agent_restent_rendus(base):
    r = H._query_inbox("CLAUDE")
    assert [m["id"] for m in r["messages"]] == ["m1"], "le lu est ecarte, l'archive des autres aussi"


def test_sans_index_possible_l_inbox_reste_lue(base, monkeypatch):
    """INDEXED BY leve si l'index manque : sans repli, l'erreur etait avalee et l'inbox semblait vide (faux calme)."""
    monkeypatch.setattr(H, "_assurer_index_nonlus", lambda: None)
    r = H._query_inbox("CLAUDE")
    assert [m["id"] for m in r["messages"]] == ["m1"]


def test_jamais_d_index_sur_la_base_rag_de_repli(tmp_path, monkeypatch):
    """_m2m() peut se replier sur RAG/embeddings.db (45 Go) : y creer un index est interdit par la constitution."""
    p = tmp_path / "embeddings.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE agent_messages (id TEXT, from_agent TEXT, to_agent TEXT, status TEXT, payload TEXT, created_at TEXT)")
    c.commit()
    c.close()
    monkeypatch.setattr(H, "_m2m", lambda: p)
    monkeypatch.setattr(H, "_DB", p)
    monkeypatch.setattr(H, "_INDEX_NONLUS_TENTE", False)
    H._query_inbox("CLAUDE")
    c = sqlite3.connect(p)
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='idx_agent_messages_nonlus'").fetchone()[0] == 0
    c.close()


def test_un_sondage_get_mode_ne_declenche_pas_l_inbox(base, monkeypatch):
    appels = []
    monkeypatch.setattr(H, "_query_inbox", lambda agent: appels.append(agent) or {"messages": [], "jobs": []})
    monkeypatch.setattr(H, "_inject_agents", lambda: {"TRAY"})
    assert H.post_dispatch({"agent": "TRAY", "tool": "get_mode", "session_id": "s"}, "reponse") == "reponse"
    assert appels == []
    H.post_dispatch({"agent": "TRAY", "tool": "run", "session_id": "s"}, "reponse")
    assert appels == ["TRAY"], "les autres outils gardent l'inbox"
