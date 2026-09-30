"""NR — le rattrapage d'embeddings ne relit plus la base a chaque lot (lecteur principal de l'homeostasie, 2026-09-23).

Ecrit ROUGE avant correctif. Feu vert owner : `tools/forge_embed_backfill_cool.py` seul.

LE DEFAUT. Pendant l'ingestion 6f, l'hormone TSH_VECTORIZATION monte, l'orchestrateur prend le role
`rag_warmer` et lance `backfill()` DANS SON PROCESSUS : il a lu 9,8 Go en 3 min (episode 21:10, aucun
bilan `health` a ce moment). EXPLAIN reel : le COMPTE et le LOT passent par `idx_emb_null_origin`, index
partiel qui ne porte PAS `embedding_model` => chaque chunk sans embedding (2,56 M + l'ingestion du soir)
est LU pour tester la colonne ; et les lignes deja marquees SKIP_TIER restent dans l'index (leur
embedding reste NULL) : chaque lot les RELIT avant de trouver les suivantes.

LE NR, SUR LE CHEMIN REEL (`backfill()` avec base temoin au meme schema, dependances externes neutralisees) :
  - aucune instruction ne balaie `rag_chunks` hors d'un index couvrant ;
  - aucun chunk n'est relu d'un lot a l'autre ;
  - le compte est DECLARE comme borne haute (il inclut les SKIP_*).
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


def _base(tmp_path) -> Path:
    db = tmp_path / "rag.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, domain TEXT, origin TEXT,"
        " embedding BLOB, embedding_model TEXT);"
        "CREATE INDEX idx_embedding_null ON rag_chunks(id) WHERE embedding IS NULL;"
        "CREATE INDEX idx_emb_null_origin ON rag_chunks(origin) WHERE embedding IS NULL;"
    )
    long = "x" * 80
    for i in range(200):  # deja sautes : SKIP_TIER, embedding toujours NULL
        con.execute("INSERT INTO rag_chunks VALUES (?,?,?,?,NULL,'SKIP_TIER')", ("a%04d" % i, long, "d", "o"))
    for i in range(120):  # a traiter
        con.execute("INSERT INTO rag_chunks VALUES (?,?,?,?,NULL,NULL)", ("b%04d" % i, long, "d", "o"))
    con.commit()
    con.close()
    return db


def _lancer(tmp_path, monkeypatch, limit=96):
    db = _base(tmp_path)
    emises, lus = [], []

    class _Enregistreuse(sqlite3.Connection):
        def execute(self, sql, params=(), /):
            emises.append((sql, tuple(params)))
            cur = super().execute(sql, params)
            if sql.strip().upper().startswith("SELECT ID, TEXT"):
                rows = cur.fetchall()
                lus.extend(r[0] for r in rows)
                return _Rendu(rows)
            return cur

    class _Rendu:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    vrai = sqlite3.connect
    monkeypatch.setattr(bf, "DB", db)
    monkeypatch.setattr(bf.sqlite3, "connect", lambda *a, **k: vrai(str(db), factory=_Enregistreuse, timeout=5))
    monkeypatch.setattr(bf, "set_idle_priority", lambda: None)
    monkeypatch.setattr(bf, "should_throttle", lambda *a: (False, 0, 0))
    monkeypatch.setattr(bf, "brain_batch", lambda textes, timeout_s=0: [])  # embedder absent : 0 vecteur
    if hasattr(bf.backfill, "_curseur"):
        monkeypatch.setattr(bf.backfill, "_curseur", "", raising=False)
    res = bf.backfill(limit, 32, 0, 100, 100)
    return db, emises, lus, res


def test_aucun_balayage_hors_index_couvrant(tmp_path, monkeypatch):
    db, emises, _, _ = _lancer(tmp_path, monkeypatch)
    con = sqlite3.connect(db)
    fautives = []
    # SEULE exception, MESUREE : le compte dont le WHERE est EXACTEMENT le predicat de l'index
    # partiel (`embedding IS NULL`) ne lit pas la table — 6,2 s pour 5 718 767 entrees sur la base
    # reelle (23/09), la ou relire les lignes couterait des dizaines de Go. EXPLAIN l'etiquette
    # « USING INDEX » et non « COVERING » : l'etiquette trompe sur ce cas precis, pas la mesure.
    exacte = "SELECT COUNT(*) FROM rag_chunks INDEXED BY idx_embedding_null WHERE embedding IS NULL"
    for sql, params in emises:
        if " ".join(sql.split()) == exacte:
            continue
        if sql.strip().upper().startswith("SELECT"):
            plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql, params)]
            if any(l.startswith("SCAN rag_chunks") and "COVERING INDEX" not in l for l in plan):
                fautives.append((" ".join(sql.split())[:90], plan))
    con.close()
    assert not fautives, "lecture de chaque ligne sans embedding : %s" % fautives


def test_aucun_chunk_relu_d_un_lot_a_l_autre(tmp_path, monkeypatch):
    _, _, lus, _ = _lancer(tmp_path, monkeypatch)
    doublons = {i for i in lus if lus.count(i) > 1}
    assert not doublons, "%d chunk(s) relus d'un lot a l'autre (ex. %s)" % (len(doublons), sorted(doublons)[:3])
    assert not any(i.startswith("a") for i in lus), "des chunks deja SKIP_TIER ont ete relus"


def test_le_compte_est_une_borne_haute_declaree(tmp_path, monkeypatch):
    _, _, _, res = _lancer(tmp_path, monkeypatch)
    assert res.get("null_borne_haute") == 320, res  # 200 SKIP_TIER + 120 a traiter : borne, pas un compte exact
