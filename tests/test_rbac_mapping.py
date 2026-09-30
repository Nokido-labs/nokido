"""Tests forge_rbac_mapping — migration, get/set/list/audit, validation."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import forge_rbac_mapping as fm  # noqa: E402


@pytest.fixture
def db(tmp_path: Path) -> Path:
    p = tmp_path / "embeddings.db"
    c = sqlite3.connect(str(p))
    c.execute("""
        CREATE TABLE forge_entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT,
            display_name TEXT,
            ring_level INTEGER,
            capabilities TEXT,
            token_hash TEXT,
            is_active INTEGER,
            created_at TEXT,
            last_seen TEXT,
            meta TEXT
        )
    """)
    # 4 entities couvrant les tiers
    rows = [
        ("usr_naarob",  "human", "user",      0, "[]", None, 1, "", "", "{}"),
        ("agt_claude",  "llm",   "Claude",      1, "[]", None, 1, "", "", "{}"),
        ("agt_gemini",  "llm",   "Gemini",      3, "[]", None, 1, "", "", "{}"),
        ("wrk_rss",     "worker","RSS Watcher", 4, "[]", None, 1, "", "", "{}"),
    ]
    c.executemany(
        "INSERT INTO forge_entities VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    c.commit()
    c.close()
    fm._MIGRATED = False  # reset cache pour chaque fixture
    return p


# ── Schema migration ────────────────────────────────────────────────────────

def test_migration_adds_column(db: Path):
    c = sqlite3.connect(str(db))
    cols = {r[1] for r in c.execute("PRAGMA table_info(forge_entities)").fetchall()}
    assert "os_account" not in cols
    c.close()
    fm._conn(db).close()  # trigger migration
    c = sqlite3.connect(str(db))
    cols = {r[1] for r in c.execute("PRAGMA table_info(forge_entities)").fetchall()}
    assert "os_account" in cols
    # Audit table créée aussi
    tables = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "rbac_mapping_audit" in tables
    c.close()


def test_migration_idempotent(db: Path):
    fm._conn(db).close()
    fm._MIGRATED = False
    # Second call ne doit pas crasher
    fm._conn(db).close()


# ── Derive ──────────────────────────────────────────────────────────────────

def test_derive_ring_0_system():
    acc = fm.derive_for_ring(0)
    assert acc.zone == "system"
    assert acc.os_user is None


def test_derive_ring_1_trusted():
    acc = fm.derive_for_ring(1)
    assert acc.zone == "trusted"
    assert acc.os_user == "LaForgeTrusted"
    assert acc.os_group == "LaForgeTrustedRunners"


def test_derive_ring_3_sandbox_online():
    acc = fm.derive_for_ring(3)
    assert acc.zone == "sandbox-online"
    assert acc.os_user == "LaForgeSbxOnline"
    assert acc.os_group == "LaForgeSandboxUsers"


def test_derive_ring_4_sandbox_offline():
    acc = fm.derive_for_ring(4)
    assert acc.zone == "sandbox-offline"
    assert acc.os_user == "LaForgeSbxOffline"


# ── get/list ────────────────────────────────────────────────────────────────

def test_get_unknown_returns_empty(db: Path):
    assert fm.get_mapping("inconnu", db_path=db) == {}


def test_get_unset_derives_from_ring(db: Path):
    m = fm.get_mapping("agt_gemini", db_path=db)
    assert m["ring_level"] == 3
    assert m["os_account"]["zone"] == "sandbox-online"
    assert m["os_account"]["os_user"] == "LaForgeSbxOnline"


def test_list_returns_all(db: Path):
    lst = fm.list_mappings(db_path=db)
    assert len(lst) == 4
    ids = {m["entity_id"] for m in lst}
    assert {"usr_naarob", "agt_claude", "agt_gemini", "wrk_rss"} == ids


# ── set ─────────────────────────────────────────────────────────────────────

def test_set_zone_derives_user_group(db: Path):
    r = fm.set_mapping("agt_gemini", zone="sandbox-offline",
                       actor="test", reason="test offline", db_path=db)
    assert r["os_account"]["zone"] == "sandbox-offline"
    assert r["os_account"]["os_user"] == "LaForgeSbxOffline"
    assert r["os_account"]["set_by"] == "test"
    # Verifie persistence
    m = fm.get_mapping("agt_gemini", db_path=db)
    assert m["os_account"]["zone"] == "sandbox-offline"


def test_set_rejects_unknown_zone(db: Path):
    with pytest.raises(ValueError, match="zone inconnue"):
        fm.set_mapping("agt_gemini", zone="moon", db_path=db)


def test_set_rejects_unknown_entity(db: Path):
    with pytest.raises(ValueError, match="entity inconnue"):
        fm.set_mapping("ghost", zone="trusted", db_path=db)


def test_set_validates_user_group_match(db: Path):
    # zone=trusted + user explicit incoherent doit rejeter
    with pytest.raises(ValueError, match="exige os_user"):
        fm.set_mapping("agt_claude", zone="trusted",
                       os_user="LaForgeSbxOffline", db_path=db)


def test_set_writes_audit_row(db: Path):
    fm.set_mapping("agt_gemini", zone="sandbox-offline",
                   actor="alice", reason="downgrade", db_path=db)
    log = fm.audit_log(db_path=db)
    assert len(log) >= 1
    assert log[0]["entity_id"] == "agt_gemini"
    assert log[0]["actor"] == "alice"
    assert log[0]["reason"] == "downgrade"
    assert log[0]["new"]["zone"] == "sandbox-offline"


def test_audit_limit(db: Path):
    for i in range(5):
        fm.set_mapping("wrk_rss", zone="sandbox-offline",
                       reason=f"i{i}", db_path=db)
    assert len(fm.audit_log(limit=3, db_path=db)) == 3
    assert len(fm.audit_log(limit=10, db_path=db)) == 5
