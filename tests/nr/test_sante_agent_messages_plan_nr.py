"""NR : COUNT sur agent_messages (sante) -- plans figes sur base temoin (schema M2M reel)."""
import sqlite3

from nokido_agent.app.forge_db_path import M2M_SCHEMA

_REAL = (
    " AND to_agent NOT IN ('EVENTBUS_ARCHIVE','cli_capture') "
    "AND (method IS NULL OR (method NOT LIKE 'tool.%' AND method != 'conversation.turn'))"
)


def _base():
    c = sqlite3.connect(":memory:")
    for s in (M2M_SCHEMA if isinstance(M2M_SCHEMA, (tuple, list)) else [M2M_SCHEMA]):
        c.execute(s)
    c.execute("INSERT INTO agent_messages(id,from_agent,to_agent,method,status,created_at)"
              " VALUES('a','x','y','m','unread','2026-10-01')")
    return c


def _plan(c, sql, params=()):
    return " | ".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN " + sql, params))


def test_plans_agent_messages_mesures():
    c = _base()
    qs = {
        "proprio_unread": "SELECT COUNT(*) FROM agent_messages WHERE status='unread'",
        "sante_total": "SELECT COUNT(*) FROM agent_messages WHERE 1=1" + _REAL,
        "sante_today": "SELECT COUNT(*) FROM agent_messages WHERE created_at >= '2026'" + _REAL,
        "sante_unread": "SELECT COUNT(*) FROM agent_messages WHERE status='unread' AND created_at >= '2026'" + _REAL,
        "sante_by_from": "SELECT from_agent, COUNT(*) FROM agent_messages GROUP BY from_agent ORDER BY 2 DESC LIMIT 10",
    }
    qs["sante_total"] = "SELECT COUNT(*) FROM agent_messages WHERE rowid > 0" + _REAL
    qs["sante_by_from"] = ("SELECT from_agent, COUNT(*) FROM (SELECT from_agent FROM "
                           "agent_messages NOT INDEXED WHERE rowid > 0) GROUP BY from_agent "
                           "ORDER BY 2 DESC LIMIT 10")
    for k, q in qs.items():
        p = _plan(c, q)
        assert "SCAN agent_messages" not in p.replace("SCAN agent_messages USING", ""), (k, p)
        assert "SEARCH" in p, (k, p)


def test_source_sante_borne_et_dit_ce_quelle_ecarte():
    from nokido_agent.app import forge_health_diagnostic as hd
    src = open(hd.__file__, encoding="utf-8").read()
    assert 'COUNT(*) FROM agent_messages WHERE 1=1' not in src
    assert "agent_messages_ecartes" in src
    c = _base()
    assert "MAX(rowid) FROM agent_messages" in open(
        hd.__file__.replace("forge_health_diagnostic", "forge_proprioception"),
        encoding="utf-8").read()
