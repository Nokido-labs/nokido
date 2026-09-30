# -*- coding: utf-8 -*-
"""NR - un contenu qui tient en UN chunk est un rattrapage, pas un 'ignore' (2026-09-05).

Mesure (doi.org, job_8c8196a16a4b) : « 298 -> 3961 chars (x13.3) OK » puis
« ingest sans nouveau chunk (n=1, fresh=0) : ancien chunk CONSERVE ». Or
`_step_ingest` donne a un contenu d'un seul chunk l'id de base SANS suffixe —
c'est l'id de l'ancien chunk tronque, donc INSERT OR REPLACE l'a reecrit en
place. Le controle « ids suffixes = 0 » le declarait conserve, le comptait
ignore, et la memoire des ignorees le bloquait 7 jours.

Le test simule le crawl, l'ingestion (reecriture en place) et la base (sqlite
en memoire, schema minimal) : aucun reseau, aucune base reelle.
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))

bf = pytest.importorskip("forge_veille_backfill")

URL = "https://doi.org/10.1000/xyz"
BASE_ID = "watch_" + hashlib.md5(URL.encode()).hexdigest()[:10]


def _base():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE rag_chunks(id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT)")
    conn.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED)")
    conn.execute("INSERT INTO rag_chunks VALUES (?,?,?,?)", (BASE_ID, "x" * 298, URL, "watch_veille"))
    conn.execute("INSERT INTO rag_fts VALUES (?,?,?,?)", (BASE_ID, "x" * 298, URL, "watch_veille"))
    conn.commit()
    return conn


class _Args:
    apply = True
    redo = False
    audit = False
    min_gain = 3.0


# ZONE REELLE de chaque module, MESUREE dans `tools/forge_veille_backfill.py` et
# non deduite du dossier : le backfill importe crawl/db_path/watch_agent depuis
# `nokido_agent.app`, mais job_progress depuis `nokido_agent.tools`. Se tromper de
# zone repose un patch sans prise, c'est-a-dire le defaut qu'on repare.
_ZONES = {
    "forge_crawl_tool": "app",
    "forge_db_path": "app",
    "forge_watch_agent": "app",
    "forge_job_progress": "tools",
}


def _poser(monkeypatch, nom: str, mod):
    """Pose le faux module sur TOUS les noms par lesquels il peut etre atteint.

    DEFAUT MESURE le 2026-09-10. Ce test patchait `sys.modules["forge_db_path"]`
    pendant que le code importait `nokido_agent.app.forge_db_path` : deux entrees
    DIFFERENTES de `sys.modules`, donc AUCUNE prise. Le vrai `_step_ingest` s'est
    execute contre la VRAIE base — `OperationalError: table rag_chunks has 26
    columns but 4 values were supplied`. Un NR cense n'ouvrir aucune base reelle
    en ouvrait une.

    ⚠️ Le `setattr` n'est pas une ceinture : `from nokido_agent.app import X` lit
    l'ATTRIBUT du paquet quand il existe deja (un autre test l'a importe dans le
    meme processus), et l'attribut passe alors DEVANT `sys.modules`. Sans lui, la
    prise depend de l'ordre des tests.
    """
    zone = _ZONES[nom]
    monkeypatch.setitem(sys.modules, nom, mod)
    monkeypatch.setitem(sys.modules, f"nokido_agent.{zone}.{nom}", mod)
    paquet = sys.modules.get(f"nokido_agent.{zone}")
    if paquet is not None and hasattr(paquet, nom):
        monkeypatch.setattr(paquet, nom, mod)


def _cabler(monkeypatch, conn, contenu: str, n_chunks: int):
    crawl = types.ModuleType("forge_crawl_tool")
    crawl.crawl_url = lambda url, timeout=60: contenu
    dbp = types.ModuleType("forge_db_path")
    # purger_fts est PUR (il n'agit que sur la connexion passee) : le VRAI, pas un double.
    # Un faux module sans lui faisait avaler un ImportError a la resynchro FTS (28/09).
    try:
        from nokido_agent.app.forge_db_path import purger_fts
    except ImportError:
        from forge_db_path import purger_fts
    dbp.purger_fts = purger_fts

    class _Conn:
        """Meme connexion memoire pour tous : close() ne ferme pas."""
        def __getattr__(self, k):
            return getattr(conn, k)

        def close(self):
            pass

    dbp.open_writer = lambda timeout=60.0: _Conn()
    watch = types.ModuleType("forge_watch_agent")

    def _step_ingest(c, job_id, theme, refined):
        texte = refined[0]["content"]
        if n_chunks == 1:
            c.execute("INSERT OR REPLACE INTO rag_chunks VALUES (?,?,?,?)", (BASE_ID, texte, URL, "watch_veille"))
        else:
            for i in range(n_chunks):
                c.execute("INSERT OR REPLACE INTO rag_chunks VALUES (?,?,?,?)",
                          (f"{BASE_ID}_{i}", texte[i::n_chunks], URL, "watch_veille"))
        return n_chunks

    watch._step_ingest = _step_ingest
    prog = types.ModuleType("forge_job_progress")
    prog.emit = lambda *a, **k: False
    for nom, mod in (("forge_crawl_tool", crawl), ("forge_db_path", dbp),
                     ("forge_watch_agent", watch), ("forge_job_progress", prog)):
        _poser(monkeypatch, nom, mod)


def _cand():
    return {"url": URL, "chunk_id": BASE_ID, "n": 1, "len": 298, "total_len": 298, "theme": "t"}


def test_un_seul_chunk_reecrit_en_place_compte_comme_rattrape(monkeypatch):
    conn = _base()
    _cabler(monkeypatch, conn, "y" * 3961, n_chunks=1)
    res = bf._process_one(_cand(), _Args(), "2026-09-05T00:00:00")
    assert res["status"] == "done" and res["n"] == 1, res["log"]
    assert any("REECRIT en place" in l for l in res["log"])
    # la base porte le nouveau texte sous le MEME id, et le lexical est a jour
    assert conn.execute("SELECT LENGTH(text) FROM rag_chunks WHERE id=?", (BASE_ID,)).fetchone()[0] == 3961
    fts = conn.execute("SELECT LENGTH(text) FROM rag_fts WHERE chunk_id=?", (BASE_ID,)).fetchall()
    assert [r[0] for r in fts] == [3961], "rag_fts doit servir le nouveau texte, une seule fois"


def test_plusieurs_chunks_gardent_le_chemin_suffixe(monkeypatch):
    conn = _base()
    _cabler(monkeypatch, conn, "z" * 6000, n_chunks=3)
    res = bf._process_one(_cand(), _Args(), "2026-09-05T00:00:00")
    assert res["status"] == "done" and res["n"] == 3, res["log"]
    assert conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE id=?", (BASE_ID,)).fetchone()[0] == 0, \
        "l'ancien chunk unique est retire quand des chunks suffixes existent"


def test_un_gain_insuffisant_reste_ignore(monkeypatch):
    conn = _base()
    _cabler(monkeypatch, conn, "w" * 400, n_chunks=1)   # x1.3 < min_gain
    res = bf._process_one(_cand(), _Args(), "2026-09-05T00:00:00")
    assert res["status"] == "skip"
    assert conn.execute("SELECT LENGTH(text) FROM rag_chunks WHERE id=?", (BASE_ID,)).fetchone()[0] == 298
