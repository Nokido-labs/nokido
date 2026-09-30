"""LEPTIN_MAILBOX_FULL faux positif — audit_messages exclut la telemetrie (2026-07-14).

La glande leptine (source health_diagnostic) comptait 99% de faux "unread" :
agent_messages melange les VRAIS messages inter-agents avec de la TELEMETRIE
(firehose EventBus 'tool.%' vers EVENTBUS_ARCHIVE ; captures 'conversation.turn'
vers cli_capture) + un backlog historique jamais marque 'read'. Resultat : leptine
saturee en permanence -> daemons ralentis pour rien. Ces tests verrouillent le calcul.
"""

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import forge_health_diagnostic as H  # noqa: E402

_SCHEMA = "CREATE TABLE agent_messages (from_agent TEXT, to_agent TEXT, method TEXT, payload TEXT, status TEXT, created_at TEXT);" \
          "CREATE TABLE conversation_log (x); CREATE TABLE network_log (x); CREATE TABLE shared_prompt_log (x);"


def _conn():
    c = sqlite3.connect(":memory:")
    c.executescript(_SCHEMA)
    return c


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _old():
    return (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")


def test_telemetry_and_stale_excluded_from_unread():
    c = _conn()
    rows = [
        # TELEMETRIE (jamais des messages a lire) — doit etre ignoree
        ("CLAUDE", "EVENTBUS_ARCHIVE", "tool.run.arg.code", "{}", "unread", _now()),
        ("CLAUDE", "cli_capture", "conversation.turn", "{}", "unread", _now()),
        # VIEUX message inter-agent non lu (backlog historique) — pas une pression actuelle
        ("agt_gemini", "agt_agy", "task.assign", "{}", "unread", _old()),
        # VRAI message inter-agent recent non lu — LE seul qui doit compter
        ("agt_agy", "agt_claude", "task.assign", "{}", "unread", _now()),
    ]
    c.executemany("INSERT INTO agent_messages VALUES (?,?,?,?,?,?)", rows)
    r = H.audit_messages(c)
    c.close()
    # total = vrais messages inter-agents (2 : vieux + recent), hors telemetrie
    assert r["agent_messages_total"] == 2
    # unread pertinent = seulement le recent non-telemetrie
    assert r["agent_messages_unread"] == 1


def test_pure_telemetry_gives_zero_unread():
    """Une mailbox pleine de PURE telemetrie -> 0 unread pertinent (leptine calme)."""
    c = _conn()
    c.executemany(
        "INSERT INTO agent_messages VALUES (?,?,?,?,?,?)",
        [("CLAUDE", "EVENTBUS_ARCHIVE", "tool.governed_edit.arg.blocks", "{}", "unread", _now()) for _ in range(500)]
        + [("X", "cli_capture", "conversation.turn", "{}", "unread", _now()) for _ in range(500)],
    )
    r = H.audit_messages(c)
    c.close()
    assert r["agent_messages_total"] == 0
    assert r["agent_messages_unread"] == 0
    assert r["agent_messages_pct_unread"] == 0.0
