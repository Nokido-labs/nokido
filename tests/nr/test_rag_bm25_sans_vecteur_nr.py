# -*- coding: utf-8 -*-
"""NR owner 4/11 (« le disque C sature en E/S ») : vidages de la sentinelle (logs/loop_lag.log 18:32-18:33) -> fil
actif forge_mcp_registry.py:8472 _rag_dense_search = la requete BM25 « ... JOIN rag_chunks c ... WHERE MATCH ? AND
c.embedding IS NOT NULL ORDER BY bm25 LIMIT 50 » : pour CHAQUE correspondance, SQLite lit le vecteur (4 Ko) ->
~15 000 lectures de 4 Ko/s, ~35 Mo par recherche. Le filtre etait redondant (l'appelant ne garde que les ids du cache
vectorise). candidats_bm25 ne touche plus la colonne embedding et rend les memes candidats."""
import importlib
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "app")]
S = importlib.import_module("nokido_agent.app.forge_rag_sql")


def _base():
    cx = sqlite3.connect(":memory:")
    cx.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, embedding BLOB)")
    cx.execute("CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, content='rag_chunks', content_rowid='rowid')")
    lignes = [("c%d" % i, "verrou sqlite reprise %s" % ("docker" if i % 3 else "tache"), b"\0" * 4096)
              for i in range(60)]
    cx.executemany("INSERT INTO rag_chunks VALUES (?,?,?)", lignes)
    cx.execute("INSERT INTO rag_chunks_fts(rowid, text) SELECT rowid, text FROM rag_chunks")
    return cx


def test_bm25_ne_lit_jamais_la_colonne_embedding():
    cx = _base()
    lues = []

    def _auth(action, a1, a2, db, origine):
        if action == sqlite3.SQLITE_READ:
            lues.append((a1, a2))
        return sqlite3.SQLITE_OK
    cx.set_authorizer(_auth)
    ids = S.candidats_bm25(cx, '"docker" OR "verrou"', 50)
    assert ids, "des candidats lexicaux sont rendus"
    assert ("rag_chunks", "embedding") not in lues, "lire le vecteur de chaque correspondance = 4 Ko x N"


def test_memes_candidats_et_limite_respectee():
    cx = _base()
    ids = S.candidats_bm25(cx, '"docker"', 10)
    assert len(ids) == 10 and all(i.startswith("c") for i in ids)
