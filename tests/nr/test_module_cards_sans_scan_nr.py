"""NR — l'ingestion des cartes comportementales ne balaie plus rag_fts (reliquat P0 WAL, 2026-09-23).

Ecrit ROUGE avant correctif.

LE DEFAUT. Apres les correctifs 24f6b1c5e et c1d3f99f4 du hook post-commit, le rejeu
mesurait encore 166 s / 6,2 Go lus par commit, TOUT dans l'etape 4.5
(`forge_module_cards.refresh_changed`, 18:49:10 -> 18:51:54). En cause, dans
`ingest_cards` : `DELETE FROM rag_fts WHERE chunk_id=?`. Or `rag_fts` declare
`chunk_id` UNINDEXED : la clause ne peut pas utiliser l'index plein texte, donc CHAQUE
carte ingeree balaie la table FTS entiere (plan `SCAN rag_fts VIRTUAL TABLE INDEX 0:`).

LE NR, SUR LE CHEMIN REEL. `ingest_cards` est execute sur une base temporaire au
MEME schema ; chaque instruction emise est rejouee en EXPLAIN QUERY PLAN. Et la
PROPRIETE ne bouge pas : apres re-ingestion, une carte a UNE seule ligne FTS, a jour.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.54)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

fmc = pytest.importorskip("forge_module_cards")


def _carte(mod, doc):
    return {"module": mod, "organ": "Qualite", "doc": doc, "summary": "resume",
            "api": [{"name": "f", "args": ["x"]}], "health": "ok"}


def _base(tmp_path):
    db = tmp_path / "rag.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL,"
        " domain TEXT, embedding BLOB, hash TEXT, indexed_at TEXT);"
        "CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED,"
        " domain UNINDEXED);"
    )
    con.close()
    return db


def _ingerer(tmp_path, monkeypatch, cartes_avant, cartes):
    db = _base(tmp_path)
    monkeypatch.setattr(fmc, "DB", str(db))
    fmc.ingest_cards(cartes_avant)  # etat anterieur : cartes deja presentes
    emises = []

    class _Enregistreuse(sqlite3.Connection):
        def execute(self, sql, params=(), /):
            emises.append((sql, tuple(params)))
            return super().execute(sql, params)

    vrai = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: vrai(str(db), factory=_Enregistreuse, timeout=5))
    fmc.ingest_cards(cartes)
    monkeypatch.setattr(sqlite3, "connect", vrai)
    return db, emises


def _plans(db, emises):
    con = sqlite3.connect(db)
    out = []
    for sql, params in emises:
        if sql.strip().upper().startswith(("SELECT", "DELETE", "UPDATE")):
            out.append((" ".join(sql.split())[:110],
                        [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql, params)]))
    con.close()
    return out


def test_aucune_instruction_ne_balaie_rag_fts(tmp_path, monkeypatch):
    avant = {"forge_a.py": _carte("forge_a.py", "ancienne doc alpha")}
    db, emises = _ingerer(tmp_path, monkeypatch, avant, {"forge_a.py": _carte("forge_a.py", "nouvelle doc beta")})
    fautives = [(s, p) for s, p in _plans(db, emises)
                if any(l.startswith("SCAN rag_fts") and l.rstrip().endswith("INDEX 0:") for l in p)
                or any(l.startswith("SCAN rag_chunks") for l in p)]
    assert not fautives, "balayage complet par carte ingeree : %s" % fautives


def test_une_carte_reingeree_a_une_seule_ligne_fts_a_jour(tmp_path, monkeypatch):
    avant = {"forge_a.py": _carte("forge_a.py", "ancienne doc alpha"),
             "forge_b.py": _carte("forge_b.py", "voisine gamma")}
    db, _ = _ingerer(tmp_path, monkeypatch, avant, {"forge_a.py": _carte("forge_a.py", "nouvelle doc beta")})
    con = sqlite3.connect(db)
    lignes_a = con.execute("SELECT text FROM rag_fts WHERE source='card/forge_a.py'").fetchall()
    lignes_b = con.execute("SELECT text FROM rag_fts WHERE source='card/forge_b.py'").fetchall()
    chunk_a = con.execute("SELECT text FROM rag_chunks WHERE source='card/forge_a.py'").fetchall()
    con.close()
    assert len(lignes_a) == 1, "doublon ou perte FTS pour la carte re-ingeree : %s" % lignes_a
    assert "nouvelle doc beta" in lignes_a[0][0] and "ancienne" not in lignes_a[0][0]
    assert len(lignes_b) == 1, "la carte voisine a ete touchee"
    assert len(chunk_a) == 1 and "nouvelle doc beta" in chunk_a[0][0]


def test_premiere_ingestion_sans_ancienne_ligne(tmp_path, monkeypatch):
    """Carte neuve : rien a purger, une ligne creee dans chaque table."""
    db, _ = _ingerer(tmp_path, monkeypatch, {}, {"forge_n.py": _carte("forge_n.py", "neuve delta")})
    con = sqlite3.connect(db)
    n_fts = con.execute("SELECT count(*) FROM rag_fts WHERE source='card/forge_n.py'").fetchone()[0]
    con.close()
    assert n_fts == 1
