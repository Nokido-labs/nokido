# -*- coding: utf-8 -*-
"""NR -- owner 30/10 « c'est trop lent » : une tache deposee pendant la sieste de l'executeur se prend
sans attendre POLL_INTERVAL. Seule une HAUSSE des taches pending reveille ; une base illisible jamais."""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as fte  # noqa: E402


def _base(chemin: Path) -> None:
    c = sqlite3.connect(chemin)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT)")
    c.commit()
    c.close()


def _ecrire(chemin: Path, sql: str, *args) -> None:
    time.sleep(0.02)  # mtime_ns distinct
    c = sqlite3.connect(chemin)
    c.execute(sql, args)
    c.commit()
    c.close()


def test_depot_reveille(tmp_path):
    db = tmp_path / "tasks.db"
    _base(db)
    etat = {"empreinte": fte._empreinte_db(db), "pending": fte._taches_pending(db)}
    assert not fte._reveil_tache_deposee(etat, db)
    _ecrire(db, "INSERT INTO tasks VALUES (?, 'pending')", "t1")
    assert fte._reveil_tache_deposee(etat, db)


def test_reclamation_ne_reveille_pas(tmp_path):
    db = tmp_path / "tasks.db"
    _base(db)
    _ecrire(db, "INSERT INTO tasks VALUES (?, 'pending')", "t1")
    etat = {"empreinte": fte._empreinte_db(db), "pending": fte._taches_pending(db)}
    _ecrire(db, "UPDATE tasks SET status='running' WHERE id=?", "t1")
    assert not fte._reveil_tache_deposee(etat, db)


def test_base_illisible_ne_reveille_jamais(tmp_path):
    db = tmp_path / "absente.db"
    etat = {"empreinte": fte._empreinte_db(db), "pending": fte._taches_pending(db)}
    assert etat["pending"] == -1
    assert not fte._reveil_tache_deposee(etat, db)
