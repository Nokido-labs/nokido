"""Index partiel de travail du rattrapage de vectorisation (decision owner 24/10, creation de nuit).

`idx_embedding_null` garde les lignes deja SKIP_* (leur embedding reste NULL) : le rattrapage
les retraverse. L'index `idx_embed_a_faire` (WHERE embedding IS NULL AND embedding_model IS
NULL) n'en contient que le travail RESTANT. Contrat, sur base temoin uniquement :
  - `--mesurer` n'ecrit rien (ni index, ni interrupteur) ;
  - `creer()` cree l'index, pose l'interrupteur du rattrapage PENDANT la creation et le retire
    apres (s'il l'a pose lui-meme), et rend un rapport mesure (duree, plans avant/apres) ;
  - une CI en cours = refus, rien d'ecrit ;
  - une fois l'index present, le lot du rattrapage le PREFERE (les SKIP_* ne sont plus lus).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

it = pytest.importorskip("forge_index_travail_embed")
bf = pytest.importorskip("forge_embed_backfill_cool")


def _base(tmp_path) -> Path:
    db = tmp_path / "rag.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, domain TEXT, origin TEXT,"
        " embedding BLOB, embedding_model TEXT);"
        "CREATE INDEX idx_embedding_null ON rag_chunks(id) WHERE embedding IS NULL;"
    )
    for i in range(50):
        con.execute("INSERT INTO rag_chunks VALUES (?,?,?,?,NULL,'SKIP_TIER')", ("a%03d" % i, "x" * 80, "d", "o"))
    for i in range(20):
        con.execute("INSERT INTO rag_chunks VALUES (?,?,?,?,NULL,NULL)", ("b%03d" % i, "x" * 80, "d", "o"))
    con.commit()
    con.close()
    return db


def _index(db):
    con = sqlite3.connect(db)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    finally:
        con.close()


def test_mesurer_n_ecrit_rien(tmp_path):
    db = _base(tmp_path)
    off = tmp_path / "embed_backfill.off"
    rapport = it.mesurer(db)
    assert "idx_embed_a_faire" not in _index(db) and not off.exists()
    assert rapport["index_present"] is False and rapport["plans"], rapport


def test_creer_pose_puis_retire_l_interrupteur(tmp_path, monkeypatch):
    db = _base(tmp_path)
    off = tmp_path / "embed_backfill.off"
    vus = []
    vrai = it._creer_index

    def _espion(conn):
        vus.append(off.exists())
        return vrai(conn)

    monkeypatch.setattr(it, "_creer_index", _espion)
    monkeypatch.setattr(it, "ci_en_cours", lambda: None)
    rapport = it.creer(db, interrupteur=off)
    assert vus == [True], "le rattrapage n'etait pas coupe pendant la creation"
    assert not off.exists(), "l'interrupteur pose par l'outil n'a pas ete retire"
    assert "idx_embed_a_faire" in _index(db)
    assert rapport["cree"] is True and rapport["duree_s"] >= 0 and rapport["plans_apres"], rapport
    # tranche le filtre par tier : combien de lignes NON marquees restent (index seul)
    assert rapport["reste_a_faire"] == 20, rapport


def test_ci_en_cours_refuse_sans_rien_ecrire(tmp_path, monkeypatch):
    db = _base(tmp_path)
    off = tmp_path / "embed_backfill.off"
    monkeypatch.setattr(it, "ci_en_cours", lambda: "pid 1234 ci_local.py")
    rapport = it.creer(db, interrupteur=off)
    assert rapport["cree"] is False and "CI" in rapport["refus"], rapport
    assert "idx_embed_a_faire" not in _index(db) and not off.exists()


def test_le_rattrapage_prefere_l_index_de_travail(tmp_path, monkeypatch):
    db = _base(tmp_path)
    monkeypatch.setattr(it, "ci_en_cours", lambda: None)
    it.creer(db, interrupteur=tmp_path / "embed_backfill.off")
    emises = []

    class _Enregistreuse(sqlite3.Connection):
        def execute(self, sql, params=(), /):
            emises.append(sql)
            return super().execute(sql, params)

    vrai = sqlite3.connect
    monkeypatch.setattr(bf, "DB", db)
    monkeypatch.setattr(bf, "CURSEUR_FICHIER", tmp_path / "curseur.json")
    monkeypatch.setattr(bf, "INTERRUPTEUR", tmp_path / "embed_backfill.off")
    monkeypatch.setattr(bf.sqlite3, "connect", lambda *a, **k: vrai(str(db), factory=_Enregistreuse, timeout=5))
    monkeypatch.setattr(bf, "set_idle_priority", lambda: None)
    monkeypatch.setattr(bf, "should_throttle", lambda *a: (False, 0, 0))
    monkeypatch.setattr(bf, "brain_batch", lambda textes, timeout_s=0: [])
    monkeypatch.setattr(bf.backfill, "_curseur", "", raising=False)
    bf.backfill(32, 32, 0, 100, 100)
    lots = [s for s in emises if s.strip().upper().startswith("SELECT ID, TEXT")]
    assert lots and "idx_embed_a_faire" in lots[0], lots[:1]
