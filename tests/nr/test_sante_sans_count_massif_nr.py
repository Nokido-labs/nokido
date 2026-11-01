"""NR : le cycle de sante ne balaie plus les tables par COUNT(*) sans WHERE.

Mesure 21/10 : ~101 cycles/24 h ; `audit_tables_empty` faisait COUNT(*) sur ~110 tables
(jusqu'a 32,7 M lignes par cycle) et `audit_messages` un COUNT sur ~2,1 M entrees d'index.
Usage reel : la premiere ne decide que « vide » / « < 5 lignes » (sonde bornee LIMIT 5,
exacte) ; la seconde n'affiche qu'un ordre de grandeur (ESTIMATION = MAX(rowid), seek).
Base sqlite temporaire : la vraie base RAG n'est jamais ouverte.
"""

import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "app"))

import forge_health_diagnostic as H  # noqa: E402

_COUNT_NU = re.compile(r"select\s+count\(\*\)\s+from\s+(?!.*\bwhere\b)", re.I | re.S)


def _tracer(conn):
    vus = []
    conn.set_trace_callback(vus.append)
    return vus


def _count_nus(vus):
    return [q for q in vus if _COUNT_NU.search(q) and "sqlite_master" not in q]


@pytest.fixture
def base(tmp_path):
    c = sqlite3.connect(str(tmp_path / "t.db"))
    c.executescript(
        "CREATE TABLE vide (x);"
        "CREATE TABLE peu (x); INSERT INTO peu VALUES (1),(2),(3);"
        "CREATE TABLE gros (x);"
        "CREATE TABLE sans_rowid (k TEXT PRIMARY KEY, v) WITHOUT ROWID;"
        "INSERT INTO sans_rowid VALUES ('a',1);"
        "CREATE TABLE network_log (x); CREATE TABLE shared_prompt_log (x);"
        "CREATE TABLE conversation_log (x);"
        "CREATE TABLE agent_messages (from_agent, to_agent, method, payload, status, created_at);"
    )
    c.executemany("INSERT INTO gros VALUES (?)", [(i,) for i in range(50)])
    c.executemany("INSERT INTO network_log VALUES (?)", [(i,) for i in range(7)])
    c.commit()
    yield c
    c.close()


def test_tables_empty_sans_count_nu_et_resultat_coherent(base):
    vus = _tracer(base)
    r = H.audit_tables_empty(base)
    assert _count_nus(vus) == []
    assert "vide" in r["empty_tables"]
    assert "gros" not in r["empty_tables"]
    assert {"table": "peu", "rows": 3} in r["low_population_tables"]
    assert all(e["table"] != "gros" for e in r["low_population_tables"])
    assert "sans_rowid" in {e["table"] for e in r["low_population_tables"]}


def test_messages_sans_count_nu_estimation_et_inconnu(base, tmp_path, monkeypatch):
    from nokido_agent.app import forge_db_path as _fdp
    m2m = tmp_path / "m2m.db"
    m = sqlite3.connect(str(m2m))
    m.execute("CREATE TABLE agent_messages (from_agent, to_agent, method, payload, status, created_at)")
    m.commit()
    m.close()
    monkeypatch.setattr(_fdp, "m2m_path", lambda *a, **k: str(m2m))
    monkeypatch.setattr(_fdp, "journal_path", lambda *a, **k: None, raising=False)
    base.execute("DROP TABLE shared_prompt_log")  # illisible -> None, jamais 0 invente
    vus = _tracer(base)
    r = H.audit_messages(base)
    assert _count_nus(vus) == []
    assert r["network_log_total"] == 7
    assert r["conversation_log_total"] == 0
    assert r["shared_prompt_log_total"] is None
    assert r["totaux_logs_estimation"] is True


def test_estimer_lignes_cas_limites(base):
    assert H._estimer_lignes(base, "network_log") == 7
    assert H._estimer_lignes(base, "vide") == 0
    assert H._estimer_lignes(base, "sans_rowid") is None
    assert H._estimer_lignes(base, "absente") is None
