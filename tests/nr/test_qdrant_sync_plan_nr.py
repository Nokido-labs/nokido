# -*- coding: utf-8 -*-
"""NR - le drain Qdrant ne balaie JAMAIS rag_chunks (2026-09-06).

Mesure sur la base reelle (EXPLAIN QUERY PLAN, 24,9 Go) : avec `JOIN`, SQLite
mettait rag_chunks en boucle EXTERNE (`SCAN c`) pour 40 lignes en attente, toutes
les 30 s -> 112 Mo/s de lecture permanente, service coupe le 05/09 -- 5e incarnation
du balayage complet sur cette base (GROUP BY source 23/08, COUNT(*) 03/09, jointure
FTS5 03/09, organ_pulse 05/09). `CROSS JOIN` impose l'ordre de boucle.

Contrats, verifies sur une base fabriquee au meme schema (le plan ne depend pas
du volume, seulement du schema et de la forme de la requete) :
  1. le plan de la requete de drain commence par la file d'attente, et rag_chunks
     n'y apparait qu'en SEARCH par cle, jamais en SCAN ;
  2. la requete est bien celle que le daemon execute (lue dans sa source, pas
     recopiee : un test qui recopie la requete protege une copie).
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools" / "forge_qdrant_sync_daemon.py"


def _requete_du_daemon() -> str:
    txt = SRC.read_text(encoding="utf-8")
    # La requete est ecrite en chaines adjacentes dans conn.execute(...) : on la
    # reconstitue depuis la source pour tester CE QUI TOURNE.
    m = re.search(r'"SELECT p\.chunk_id, c\.embedding, c\.source, c\.domain "\s*'
                  r'"([^"]+)"\s*"([^"]+)"', txt)
    assert m, "requete de drain introuvable dans la source du daemon"
    return "SELECT p.chunk_id, c.embedding, c.source, c.domain " + m.group(1) + m.group(2)


def _base_fabriquee(p: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(p))
    c.executescript(
        "CREATE TABLE rag_chunks(id TEXT PRIMARY KEY, embedding BLOB, source TEXT, domain TEXT);"
        "CREATE TABLE qdrant_sync_pending(chunk_id TEXT PRIMARY KEY, queued_at REAL);"
    )
    for i in range(50):
        c.execute("INSERT INTO rag_chunks VALUES(?,?,?,?)", (f"c{i}", b"\x00" * 8 if i % 3 else None, "s", "d"))
    for i in range(5):
        c.execute("INSERT INTO qdrant_sync_pending VALUES(?,?)", (f"c{i}", 0.0))
    c.commit()
    return c


def test_le_drain_ne_balaie_jamais_rag_chunks(tmp_path):
    c = _base_fabriquee(tmp_path / "x.db")
    q = _requete_du_daemon()
    assert "CROSS JOIN" in q, "l'ordre de boucle doit etre impose, pas laisse au planificateur"
    plan = [r[3] for r in c.execute("EXPLAIN QUERY PLAN " + q, (512,))]
    c.close()
    assert plan, "plan vide"
    assert plan[0].startswith("SCAN p") or plan[0].startswith("SEARCH p"), plan
    assert not any(step.startswith("SCAN c") for step in plan), f"rag_chunks balaye : {plan}"
    assert any("SEARCH c" in step for step in plan), f"rag_chunks doit etre cherche par cle : {plan}"


def test_la_purge_cherche_rag_chunks_par_cle(tmp_path):
    """Le second SQL du drain (purge des ids sans vecteur) : meme contrat."""
    c = _base_fabriquee(tmp_path / "y.db")
    q = ("SELECT p.chunk_id FROM qdrant_sync_pending p LEFT JOIN rag_chunks c ON c.id = p.chunk_id "
         "WHERE c.id IS NULL OR c.embedding IS NULL LIMIT 512")
    plan = [r[3] for r in c.execute("EXPLAIN QUERY PLAN " + q)]
    c.close()
    assert not any(step.startswith("SCAN c") for step in plan), plan
