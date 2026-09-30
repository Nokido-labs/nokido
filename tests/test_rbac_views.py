"""Tests endpoints FastAPI rbac_views."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))


@pytest.fixture
def app(tmp_path, monkeypatch):
    db = tmp_path / "embeddings.db"
    c = sqlite3.connect(str(db))
    c.execute("""
        CREATE TABLE forge_entities (
            entity_id TEXT PRIMARY KEY, entity_type TEXT, display_name TEXT,
            ring_level INTEGER, capabilities TEXT, token_hash TEXT,
            is_active INTEGER, created_at TEXT, last_seen TEXT, meta TEXT)
    """)
    c.executemany("INSERT INTO forge_entities VALUES (?,?,?,?,?,?,?,?,?,?)", [
        ("agt_claude", "llm", "Claude", 1, "[]", None, 1, "", "", "{}"),
        ("agt_gemini", "llm", "Gemini", 3, "[]", None, 1, "", "", "{}"),
    ])
    c.commit(); c.close()

    import forge_rbac_mapping as fm
    monkeypatch.setattr(fm, "DB", db)
    fm._MIGRATED = False

    from app.web_hub.rbac_views import router
    a = FastAPI()
    a.include_router(router)
    return a


def test_list_entities_200(app):
    r = TestClient(app).get("/api/rbac/entities")
    assert r.status_code == 200
    ids = {e["entity_id"] for e in r.json()["entities"]}
    assert "agt_claude" in ids
    assert "agt_gemini" in ids


def test_get_entity_200(app):
    r = TestClient(app).get("/api/rbac/entities/agt_claude")
    assert r.status_code == 200
    body = r.json()
    assert body["ring_level"] == 1
    assert body["os_account"]["zone"] == "trusted"


def test_get_entity_404(app):
    r = TestClient(app).get("/api/rbac/entities/ghost")
    assert r.status_code == 404


def test_patch_entity_200(app):
    c = TestClient(app)
    r = c.patch("/api/rbac/entities/agt_gemini",
                json={"zone": "sandbox-offline", "reason": "test"})
    assert r.status_code == 200
    assert r.json()["os_account"]["zone"] == "sandbox-offline"


def test_patch_rejects_unknown_zone(app):
    r = TestClient(app).patch("/api/rbac/entities/agt_claude",
                              json={"zone": "moon"})
    assert r.status_code == 422


def test_patch_requires_zone(app):
    r = TestClient(app).patch("/api/rbac/entities/agt_claude", json={})
    assert r.status_code == 400


def test_audit_appears_after_patch(app):
    c = TestClient(app)
    c.patch("/api/rbac/entities/agt_gemini",
            json={"zone": "sandbox-offline", "reason": "audit_check"})
    r = c.get("/api/rbac/audit?limit=5")
    assert r.status_code == 200
    log = r.json()["log"]
    assert any(e["reason"] == "audit_check" for e in log)


def test_rbac_page_html(app):
    r = TestClient(app).get("/rbac")
    assert r.status_code == 200
    assert "RBAC mapping" in r.text
    assert "fetch" in r.text
