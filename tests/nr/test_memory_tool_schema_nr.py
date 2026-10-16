"""NR — l'outil MCP `memory` suit les schemas REELS de la base (2026-10-15).

Mesure (Codex en M2M, reproduit par Claude) : `memory search` -> `no such column: content`,
`memory context` -> `no such column: provider_id`. Schemas lus le 15/10 : `rag_chunks.text`
(pas `content`), `provider_scores(provider, agent_id, ttft_ms, grade, status, measured_at,
priority)`, `fleet_heartbeats(node_id, node_type, last_ping_at, ...)`, `agent_tasks(id,
executor, ...)`. Et le repli de `search` etait un `LIKE '%...%'` sur `rag_chunks` (plus de
20 Go en reel) : il ne tournait que parce que la colonne visee n'existait pas. Corriger la
colonne sans retirer le repli aurait gele la boucle du hub. Ce NR trace chaque requete.
"""
import asyncio
import json
import sqlite3

import pytest

SCHEMA = [
    "CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT)",
    "CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, source, domain)",
    "CREATE TABLE provider_scores (provider TEXT, agent_id TEXT, ttft_ms REAL, grade TEXT,"
    " status TEXT, measured_at TEXT, priority INTEGER)",
    "CREATE TABLE fleet_heartbeats (node_id TEXT, node_type TEXT, last_ping_at TEXT,"
    " last_ping_ms REAL, status TEXT, missed_count INTEGER, meta TEXT)",
    "CREATE TABLE system_rules (id INTEGER PRIMARY KEY, tag TEXT, ring INTEGER, title TEXT,"
    " content TEXT, created_at TEXT)",
    "CREATE TABLE adr_records (id INTEGER PRIMARY KEY, adr_id TEXT, title TEXT, status TEXT,"
    " context TEXT, decision TEXT, consequences_pos TEXT, consequences_neg TEXT, related_adr TEXT,"
    " tags TEXT, ring INTEGER, created_at TEXT, updated_at TEXT, author TEXT, embedding_id TEXT)",
    "CREATE TABLE agent_tasks (id TEXT, created_at TEXT, updated_at TEXT, orchestrator TEXT,"
    " executor TEXT, title TEXT, description TEXT, status TEXT)",
]


@pytest.fixture
def reg(tmp_path, monkeypatch):
    pytest.importorskip("torch", reason="forge_mcp_registry exige torch (pack ml)")
    from nokido_agent.app.forge_mcp_registry import ToolRegistry

    base = tmp_path / "rag.db"
    con = sqlite3.connect(base)
    for ddl in SCHEMA:
        con.execute(ddl)
    for rowid, (cid, texte, dom) in enumerate([
        ("c1", "le moteur lit rag_chunks_fts depuis septembre", "rag"),
        ("c2", "le moteur ecrit aussi des journaux", "systeme"),
    ], start=1):
        con.execute("INSERT INTO rag_chunks(rowid, id, text, source, domain) VALUES (?,?,?,?,?)",
                    (rowid, cid, texte, "nr:" + cid, dom))
        con.execute("INSERT INTO rag_chunks_fts(rowid, text, source, domain) VALUES (?,?,?,?)",
                    (rowid, texte, "nr:" + cid, dom))
    con.execute("INSERT INTO provider_scores VALUES ('groq','x',120,'A','ok','2026-10-15',1)")
    con.execute("INSERT INTO provider_scores VALUES ('cohere','x',300,'B','down','2026-10-14',2)")
    con.execute("INSERT INTO fleet_heartbeats VALUES ('n1','hub','2026-10-15',3,'ok',0,'')")
    con.execute("INSERT INTO system_rules(tag, content) VALUES ('sprint', 'regle de test')")
    con.execute("INSERT INTO agent_tasks(id, executor, description, status, created_at)"
                " VALUES ('t1','CODEX','faire','done','2026-10-15')")
    con.commit()
    con.close()

    requetes = []
    vrai_connect = sqlite3.connect

    def connect_trace(*a, **k):
        c = vrai_connect(*a, **k)
        c.set_trace_callback(requetes.append)
        return c

    monkeypatch.setattr(sqlite3, "connect", connect_trace)
    r = ToolRegistry.__new__(ToolRegistry)
    r.db_path = base
    r._requetes = requetes
    return r


def _appel(reg, **args):
    return json.loads(asyncio.run(reg.handle_memory(args, "CLAUDE", 0)))


def test_search_trouve_par_l_index_du_moteur(reg):
    out = _appel(reg, action="search", query="moteur septembre")
    assert out.get("error") is None
    assert [r["id"] for r in out["results"]][:1] == ["c1"]
    assert "rag_chunks_fts" in out["results"][0]["content"]


def test_search_filtre_par_domaine(reg):
    out = _appel(reg, action="search", query="moteur journaux", domain="systeme")
    assert [r["id"] for r in out["results"]] == ["c2"]


def test_search_n_emet_jamais_de_like(reg):
    _appel(reg, action="search", query="moteur")
    _appel(reg, action="search", query='"ab')   # requete FTS invalide : echec DIT, pas de repli
    assert not [q for q in reg._requetes if " LIKE " in q.upper()]


def test_search_invalide_dit_son_echec(reg):
    out = _appel(reg, action="search", query='"ab')
    assert out["results"] == [] and "error" in out


def test_context_providers_tasks_ne_levent_plus(reg):
    ctx = _appel(reg, action="context")
    assert ctx["providers_up"] == ["groq"]
    assert ctx["active_agents"][0]["id"] == "n1"
    prov = _appel(reg, action="providers")
    assert {p["provider"] for p in prov["providers"]} == {"groq", "cohere"}
    taches = _appel(reg, action="tasks")
    assert taches[0]["task_id"] == "t1" and taches[0]["agent_id"] == "CODEX"
