# -*- coding: utf-8 -*-
"""Régression Agent Policier — primitive capacité x périmètre.

PROUVE (2026-07-08) que forge_access_switches délivre DÉJÀ l'implication wildcard
hiérarchique `domain:action:instance` via fnmatch (item3 veille Tapestry = couvert
par l'existant, aucun matcher net-new). Convention retenue : capacités écrites en
`domain:action:instance` ; wildcard EXPLICITE requis (`db:admin:*`) — un grant sans
`:*` (`db:admin`) NE couvre PAS les sous-instances (explicite > implicite = sécu).
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "app"))
import forge_access_switches as fas  # noqa: E402


def _fresh_db():
    d = tempfile.mkdtemp()
    db = os.path.join(d, "acl.db")
    conn = sqlite3.connect(db)
    conn.executescript(fas.DDL)
    conn.commit()
    conn.close()
    return db


def _grant(db, agent_pattern, resource_pattern, action="*"):
    fas.create_switch(agent_pattern, resource_pattern, action, True, "pytest", db_path=db)


def _chk(db, agent, resource, action="read"):
    fas._cache_version = -1  # force reload depuis la db temp (cache global)
    return fas.check_access(agent, resource, action, ring=3, db_path=db)


def test_wildcard_instance_covers_all_instances():
    db = _fresh_db()
    _grant(db, "AGENT_X", "db:admin:*")
    assert _chk(db, "AGENT_X", "db:admin:tasks")[0] is True
    assert _chk(db, "AGENT_X", "db:admin:secrets", "write")[0] is True


def test_wildcard_does_not_leak_across_domain():
    db = _fresh_db()
    _grant(db, "AGENT_X", "db:admin:*")
    # fs:* hors périmètre db:admin:* -> pas de match (délégué au ring système)
    assert _chk(db, "AGENT_X", "fs:write:x")[0] is None


def test_domain_wildcard_covers_deep():
    db = _fresh_db()
    _grant(db, "AGENT_Z", "db:*")
    assert _chk(db, "AGENT_Z", "db:admin:tasks")[0] is True
    assert _chk(db, "AGENT_Z", "db:read:rows")[0] is True


def test_missing_parts_are_NOT_implicit_wildcard():
    """Design Nokido : wildcard explicite requis (contraire à Shiro missing-parts).
    Un grant `db:admin` ne couvre PAS `db:admin:tasks` — évite l'élargissement
    silencieux d'un droit. Pour couvrir les instances : écrire `db:admin:*`."""
    db = _fresh_db()
    _grant(db, "AGENT_Y", "db:admin")
    assert _chk(db, "AGENT_Y", "db:admin:tasks")[0] is None


def test_deny_override_beats_allow():
    db = _fresh_db()
    _grant(db, "AGENT_D", "db:*")
    fas.create_switch("AGENT_D", "db:admin:*", "*", False, "pytest", db_path=db)  # DENY
    # deny-override : la règle DENY db:admin:* prime sur l'ALLOW db:*
    assert _chk(db, "AGENT_D", "db:admin:tasks")[0] is False
    assert _chk(db, "AGENT_D", "db:read:rows")[0] is True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
