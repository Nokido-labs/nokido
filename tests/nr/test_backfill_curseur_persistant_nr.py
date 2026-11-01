"""Le rattrapage de vectorisation ne retraverse plus la base a chaque reboot (owner 24/10).

CE QUI A ETE PAYE (2026-10-24, reboot de 17:16). Le premier lot apres le redemarrage a lu
8,4 Go en 3,5 min (NokidoHomeostasis, 53 Mo/s, phase pluripotent TIMEOUT >90 s) pour un
travail utile NUL : 6,9 M chunks sans embedding, presque tous deja SKIP_TIER. Cause : le
curseur `backfill._curseur` ne vivait que dans le processus -- vide apres un reboot, le lot
repart du debut de `idx_embedding_null` et relit chaque ligne deja sautee pour tester
`embedding_model`. Et, en fin d'index, un tour COMPLET depuis le debut etait relance.

Contrat, sur le CHEMIN REEL `backfill()` (base temoin au meme schema, embedder neutralise) :
  - le curseur survit a un redemarrage (nouveau processus = attribut vide, fichier d'etat lu) ;
  - en fin d'index, on ne repart JAMAIS de zero : les lignes inserees ensuite sont prises
    par leur rowid (plage bornee) ;
  - un interrupteur fichier coupe le rattrapage SANS une seule requete.
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

bf = pytest.importorskip("forge_embed_backfill_cool")

LONG = "x" * 80


def _base(tmp_path) -> Path:
    db = tmp_path / "rag.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, domain TEXT, origin TEXT,"
        " embedding BLOB, embedding_model TEXT);"
        "CREATE INDEX idx_embedding_null ON rag_chunks(id) WHERE embedding IS NULL;"
        "CREATE INDEX idx_emb_null_origin ON rag_chunks(origin) WHERE embedding IS NULL;"
    )
    for i in range(200):  # deja sautes : SKIP_TIER, embedding toujours NULL
        con.execute("INSERT INTO rag_chunks VALUES (?,?,?,?,NULL,'SKIP_TIER')", ("a%04d" % i, LONG, "d", "o"))
    for i in range(120):  # a traiter
        con.execute("INSERT INTO rag_chunks VALUES (?,?,?,?,NULL,NULL)", ("b%04d" % i, LONG, "d", "o"))
    con.commit()
    con.close()
    return db


def _preparer(tmp_path, monkeypatch, db):
    emises = []

    class _Enregistreuse(sqlite3.Connection):
        def execute(self, sql, params=(), /):
            emises.append((sql, tuple(params)))
            return super().execute(sql, params)

    vrai = sqlite3.connect
    monkeypatch.setattr(bf, "DB", db)
    monkeypatch.setattr(bf, "CURSEUR_FICHIER", tmp_path / "curseur.json")
    monkeypatch.setattr(bf, "INTERRUPTEUR", tmp_path / "embed_backfill.off")
    monkeypatch.setattr(bf.sqlite3, "connect", lambda *a, **k: vrai(str(db), factory=_Enregistreuse, timeout=5))
    monkeypatch.setattr(bf, "set_idle_priority", lambda: None)
    monkeypatch.setattr(bf, "should_throttle", lambda *a: (False, 0, 0))
    monkeypatch.setattr(bf, "brain_batch", lambda textes, timeout_s=0: [])  # embedder absent
    return emises


def _nouveau_processus(monkeypatch):
    """Un reboot : l'etat en memoire du processus est perdu, le fichier reste."""
    monkeypatch.setattr(bf.backfill, "_curseur", "", raising=False)


def _lots(emises):
    return [(sql, p) for sql, p in emises if sql.strip().upper().startswith("SELECT ID, TEXT")]


def test_le_curseur_survit_a_un_redemarrage(tmp_path, monkeypatch):
    db = _base(tmp_path)
    emises = _preparer(tmp_path, monkeypatch, db)
    _nouveau_processus(monkeypatch)
    bf.backfill(64, 32, 0, 100, 100)
    dernier = _lots(emises)[-1]
    emises.clear()
    _nouveau_processus(monkeypatch)
    bf.backfill(32, 32, 0, 100, 100)
    premier_apres_reboot = _lots(emises)[0]
    assert premier_apres_reboot[1][0] not in ("", None), (
        "apres reboot le lot repart du DEBUT de l'index : %r" % (premier_apres_reboot,))
    assert premier_apres_reboot[1][0] > "b", premier_apres_reboot  # au-dela des SKIP_TIER deja traverses
    assert dernier  # le premier passage a bien emis des lots


def test_en_fin_d_index_on_ne_repart_jamais_de_zero(tmp_path, monkeypatch):
    db = _base(tmp_path)
    emises = _preparer(tmp_path, monkeypatch, db)
    _nouveau_processus(monkeypatch)
    bf.backfill(10_000, 32, 0, 100, 100)  # epuise tout
    con = sqlite3.connect(db)
    for i in range(5):  # inserees APRES le passage
        con.execute("INSERT INTO rag_chunks VALUES (?,?,?,?,NULL,NULL)", ("0new%02d" % i, LONG, "d", "o"))
    con.commit()
    con.close()
    emises.clear()
    _nouveau_processus(monkeypatch)
    bf.backfill(10_000, 32, 0, 100, 100)
    lots = _lots(emises)
    assert lots, "les lignes nouvelles n'ont pas ete cherchees"
    assert not any(p and p[0] == "" for _sql, p in lots), "un tour complet depuis le debut a ete relance"
    assert any("ROWID" in sql.upper() for sql, _p in lots), "les nouvelles lignes ne sont pas prises par rowid"


def test_l_interrupteur_coupe_sans_une_requete(tmp_path, monkeypatch):
    db = _base(tmp_path)
    emises = _preparer(tmp_path, monkeypatch, db)
    (tmp_path / "embed_backfill.off").write_text("owner 24/10", encoding="utf-8")
    res = bf.backfill(300, 32, 0, 100, 100)
    assert res.get("stopped") == "interrupteur", res
    assert emises == [], emises
