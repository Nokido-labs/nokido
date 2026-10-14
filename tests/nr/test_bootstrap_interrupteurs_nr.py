"""NR -- le premier amorcage pose access_switches VIDE (parcours paquet, 2026-10-13).

Mesure : installe par pip, la table n'existait nulle part ; le controle des interrupteurs levait « no such table »
et, fail-closed, le hub refusait TOUT appel d'outil, quel que soit le rang (ask comme rag).

Ce qui est garde :
  * base par defaut sans la table -> creee VIDE, et check_access rend « no_switch_match » (decision au rang) ;
  * table presente -> intouchee, ses regles (dont les REFUS) restent ;
  * base DEDIEE declaree (LAFORGE_SWITCHES_DB_PATH) -> non touchee : y creer une table vide effacerait des refus,
    et basculer ce garde est un geste owner.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
for p in (RACINE / "tools", RACINE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_db_bootstrap as B  # noqa: E402


@pytest.fixture
def base(tmp_path, monkeypatch):
    db = tmp_path / "RAG" / "embeddings.db"
    db.parent.mkdir()
    monkeypatch.setattr(B, "DB", db)
    monkeypatch.delenv("LAFORGE_SWITCHES_DB_PATH", raising=False)
    monkeypatch.delenv("LAFORGE_DB_PATH", raising=False)
    return db


def test_base_neuve_table_vide_et_decision_au_rang(base):
    from nokido_agent.app import forge_access_switches as S
    c = sqlite3.connect(base)
    assert "CREEE vide" in B.poser_interrupteurs(c)
    c.commit()
    assert c.execute("SELECT COUNT(*) FROM access_switches").fetchone()[0] == 0
    c.close()
    S._rules_cache, S._cache_version = None, None
    autorise, raison = S.check_access("EDITOR", "rag", "run", 2, db_path=str(base))
    assert autorise is None and raison == "no_switch_match"


def test_table_presente_intouchee(base):
    from nokido_agent.app.forge_access_switches import DDL
    c = sqlite3.connect(base)
    c.executescript(DDL)
    c.execute("INSERT INTO access_switches (id, agent_pattern, resource_pattern, action, allowed, granted_by) "
              "VALUES ('refus', 'GEMINI', '*', '*', 0, 'OWNER')")
    c.commit()
    assert "intouchee" in B.poser_interrupteurs(c)
    assert c.execute("SELECT allowed FROM access_switches WHERE id='refus'").fetchone() == (0,)
    c.close()


def test_base_dediee_jamais_touchee(base, monkeypatch, tmp_path):
    monkeypatch.setenv("LAFORGE_SWITCHES_DB_PATH", str(tmp_path / "switches.db"))
    c = sqlite3.connect(base)
    assert "geste owner" in B.poser_interrupteurs(c)
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='access_switches'").fetchone()
    c.close()


def test_interrupteurs_vivant_ailleurs_jamais_touches(base, monkeypatch, tmp_path):
    monkeypatch.setenv("LAFORGE_DB_PATH", str(tmp_path / "autre.db"))
    c = sqlite3.connect(base)
    assert "non touchee" in B.poser_interrupteurs(c)
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='access_switches'").fetchone()
    c.close()
