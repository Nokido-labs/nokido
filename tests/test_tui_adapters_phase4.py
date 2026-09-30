"""Tests adapter RBAC TUI."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from tui_adapters import rbac_adapter as ra  # noqa: E402


def test_list_mappings_safe_no_db():
    """Sans DB / module → ne crash pas, retourne list vide."""
    # Force ImportError-like en mockant l'import
    with patch.dict(sys.modules, {"forge_rbac_mapping": None}):
        # Quand sys.modules[x]=None → import raise. Wrapper l'attrape.
        out = ra.list_mappings_safe()
    assert isinstance(out, list)


def test_list_mappings_safe_returns_list_when_module_ok(tmp_path, monkeypatch):
    """DB temp avec 1 entity → wrapper renvoie 1 mapping."""
    db = tmp_path / "embeddings.db"
    c = sqlite3.connect(str(db))
    c.execute("""
        CREATE TABLE forge_entities (
            entity_id TEXT PRIMARY KEY, entity_type TEXT, display_name TEXT,
            ring_level INTEGER, capabilities TEXT, token_hash TEXT,
            is_active INTEGER, created_at TEXT, last_seen TEXT, meta TEXT)
    """)
    c.execute("INSERT INTO forge_entities VALUES (?,?,?,?,?,?,?,?,?,?)",
              ("agt_test", "llm", "Test", 1, "[]", None, 1, "", "", "{}"))
    c.commit(); c.close()
    import forge_rbac_mapping as fm
    monkeypatch.setattr(fm, "DB", db)
    fm._MIGRATED = False
    out = ra.list_mappings_safe()
    assert any(m["entity_id"] == "agt_test" for m in out)
