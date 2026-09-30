"""TDD/Unit tests for forge_pool_registry."""
from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))

import forge_pool_registry as fpr  # noqa: E402


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Redirige DEFAULT_DB vers un fichier temporaire pour chaque test."""
    test_db = tmp_path / "test_embeddings.db"
    monkeypatch.setattr(fpr, "DEFAULT_DB", test_db)
    # Réinitialise la table
    fpr.init_db()
    yield
    if test_db.exists():
        try:
            os.remove(test_db)
        except Exception:
            pass


def test_db_initialization():
    """Vérifie que la base est correctement initialisée."""
    conn = fpr.get_db_connection()
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='forge_pool_registry'")
        assert cursor.fetchone() is not None
    finally:
        conn.close()


def test_publish_and_retrieve():
    """Vérifie le stockage et la fusion partielle des métriques."""
    # Publication initiale
    success = fpr.publish("test_cli", {
        "kind": "cli",
        "capability_tags": ["code", "rust"],
        "cost": 0.1,
        "latency_ms": 250.0,
        "quota_restant": 95.0,
        "available": 1
    })
    assert success is True

    # Vérification dans la base
    conn = fpr.get_db_connection()
    try:
        row = conn.execute("SELECT * FROM forge_pool_registry WHERE member='test_cli'").fetchone()
        assert row is not None
        assert row["kind"] == "cli"
        assert row["cost"] == 0.1
        assert row["latency_ms"] == 250.0
        assert row["quota_restant"] == 95.0
        assert row["available"] == 1
    finally:
        conn.close()

    # Mise à jour partielle (ex: latence uniquement)
    success = fpr.publish("test_cli", {
        "latency_ms": 500.0
    })
    assert success is True

    conn = fpr.get_db_connection()
    try:
        row = conn.execute("SELECT * FROM forge_pool_registry WHERE member='test_cli'").fetchone()
        assert row["latency_ms"] == 500.0
        assert row["cost"] == 0.1  # Doit être préservé
    finally:
        conn.close()


def test_best_selection_by_capabilities():
    """Vérifie que le membre ayant les capacités requises est préféré."""
    fpr.publish("member_generic", {
        "kind": "model",
        "capability_tags": ["llm"],
        "cost": 0.0,
        "latency_ms": 100.0,
        "quota_restant": 100.0,
        "available": 1
    })
    fpr.publish("member_coder", {
        "kind": "model",
        "capability_tags": ["llm", "code"],
        "cost": 0.05,
        "latency_ms": 150.0,
        "quota_restant": 100.0,
        "available": 1
    })

    # Sans tag particulier, member_generic est meilleur car plus rapide et moins coûteux
    assert fpr.best("llm") == "member_generic"

    # Pour une tâche de code, member_coder est préféré malgré le coût/latence plus élevé
    assert fpr.best("code") == "member_coder"
    assert fpr.best("llm", need_caps=["code"]) == "member_coder"


def test_best_selection_excludes_unavailable():
    """Vérifie que les membres indisponibles ou hors-quota sont exclus."""
    fpr.publish("member_fast_dead", {
        "kind": "model",
        "capability_tags": ["llm"],
        "cost": 0.0,
        "latency_ms": 50.0,
        "quota_restant": 100.0,
        "available": 0  # indisponible
    })
    fpr.publish("member_slow_alive", {
        "kind": "model",
        "capability_tags": ["llm"],
        "cost": 0.0,
        "latency_ms": 500.0,
        "quota_restant": 100.0,
        "available": 1
    })

    assert fpr.best("llm") == "member_slow_alive"


def test_best_selection_excludes_zero_quota():
    """Vérifie qu'un membre sans quota restant est exclu."""
    fpr.publish("member_no_quota", {
        "kind": "model",
        "capability_tags": ["llm"],
        "cost": 0.0,
        "latency_ms": 50.0,
        "quota_restant": 0.0,  # pas de quota
        "available": 1
    })
    fpr.publish("member_has_quota", {
        "kind": "model",
        "capability_tags": ["llm"],
        "cost": 0.1,
        "latency_ms": 100.0,
        "quota_restant": 10.0,
        "available": 1
    })

    assert fpr.best("llm") == "member_has_quota"
