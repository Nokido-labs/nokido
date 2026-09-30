# -*- coding: utf-8 -*-
"""
forge_db.py — Connexion SQLite centralisée avec PRAGMAs optimaux
================================================================
Remplace sqlite3.connect() direct partout dans le codebase.
Garantit que chaque connexion a les bons PRAGMAs WAL + perf.

Usage :
    from forge_db import get_conn, get_conn_readonly

    # Lecture/écriture
    with get_conn() as conn:
        conn.execute("INSERT INTO ...")

    # Lecture seule (plus rapide, pas de lock)
    with get_conn_readonly() as conn:
        rows = conn.execute("SELECT ...").fetchall()
"""

from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"

# PRAGMAs appliqués à chaque connexion
# Références : sqlite.org/pragma.html + fly.io/blog/sqlite-internals
_PRAGMAS_RW = [
    "PRAGMA journal_mode=WAL",  # Multi-writers safe
    "PRAGMA synchronous=NORMAL",  # Safe avec WAL, 5x plus rapide que FULL
    "PRAGMA cache_size=-64000",  # 64MB page cache RAM
    "PRAGMA mmap_size=2147483648",  # 2GB mmap — lectures depuis RAM OS
    "PRAGMA temp_store=MEMORY",  # Sorts/GROUP BY en RAM
    "PRAGMA wal_autocheckpoint=500",  # Checkpoint toutes les 500 pages
    # Aligne sur forge_db_path.open_writer (2026-09-23) : sans lui, le WAL n'est
    # jamais reduit a la remise a zero (doc sqlite.org/wal.html) -> 48 Go mesures.
    "PRAGMA journal_size_limit=67108864",
    "PRAGMA foreign_keys=ON",  # Cohérence référentielle
    "PRAGMA busy_timeout=10000",  # 10s avant SQLITE_BUSY (multi-agents)
]

_PRAGMAS_RO = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA cache_size=-64000",
    "PRAGMA mmap_size=2147483648",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA query_only=ON",  # Lecture stricte — bloque tout DML
]


def _apply_pragmas(conn: sqlite3.Connection, readonly: bool = False):
    pragmas = _PRAGMAS_RO if readonly else _PRAGMAS_RW
    for pragma in pragmas:
        conn.execute(pragma)


@contextmanager
def get_conn(timeout: float = 10.0):
    """Connexion lecture/écriture avec PRAGMAs optimaux."""
    conn = sqlite3.connect(str(DB), timeout=timeout)
    try:
        _apply_pragmas(conn, readonly=False)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_conn_readonly(timeout: float = 5.0):
    """Connexion lecture seule — plus rapide, pas de lock WAL."""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=timeout)
    try:
        _apply_pragmas(conn, readonly=True)
        yield conn
    finally:
        conn.close()


def quick_read(sql: str, params: tuple = ()) -> list:
    """Lecture rapide one-shot."""
    with get_conn_readonly() as conn:
        return conn.execute(sql, params).fetchall()


def quick_write(sql: str, params: tuple = ()) -> int:
    """Écriture one-shot — retourne lastrowid."""
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid
