# -*- coding: utf-8 -*-
"""NR -- un echec de synchro `rag_fts` a l'ingestion de veille se COMPTE et se SIGNALE (audit ChatGPT, 15/10).

AVANT : dans `forge_watch_agent._step_ingest`, l'INSERT dans `rag_fts` etait sous un `except` journalise en
DEBUG, et le chunk etait compte ingere quand meme -- present dans `rag_chunks`, INVISIBLE en BM25, et rien ne le
disait. Le lexical prime (doctrine owner du 25/07) : un ecart lexical doit se VOIR.

Contrat verrouille, sur le chemin REEL (`_step_ingest` du module, base SQLite en memoire) :
  1. sans table `rag_fts`, les chunks restent ecrits dans `rag_chunks`, et un evenement critique
     `fts_desync:watch_veille` part avec le compte exact (chunks_sans_fts / chunks) ;
  2. un WARNING nomme l'ecart (« SANS ligne rag_fts ») ;
  3. avec `rag_fts` presente, aucune alerte : le garde ne crie pas a faux.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_watch_agent as W  # noqa: E402

_PROSE = (
    "Le routeur choisit un fournisseur selon la capacite mesuree et le cout observe sur la fenetre recente. "
    "Quand un fournisseur refuse une requete trop longue, la cascade passe au suivant sans relancer le meme. "
    "La mesure de reference est la mediane de cinq passes, et un ecart sous le bruit ne vaut pas un gain. "
)


def _refined() -> list[dict]:
    # Trois sources aux corps DISTINCTS (la garde de deduplication jette un corps repete).
    return [{"url": f"https://exemple.org/article-{i}", "title": f"Article {i}", "keyword": "routeur",
             "relevance": 9, "content": f"Etude numero {i}. " + _PROSE * (i + 1)} for i in range(3)]


def _base(avec_fts: bool) -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(W.DDL_WATCH)
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT, role_hint TEXT,"
              " author TEXT, ingested_at TEXT, created_at TEXT, embedding BLOB, sequence_id INTEGER, meta TEXT,"
              " hash TEXT, canonical_id TEXT, embedding_model TEXT)")
    if avec_fts:
        c.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source, domain)")
    c.commit()
    return c


@pytest.fixture
def alertes(monkeypatch):
    """Capte `forge_critical_events.persist` (aucune base reelle touchee), sous LES DEUX noms d'import."""
    recues: list[tuple] = []
    faux = types.ModuleType("forge_critical_events")
    faux.persist = lambda cle, niveau, details=None, *a, **k: recues.append((cle, niveau, details))
    monkeypatch.setitem(sys.modules, "forge_critical_events", faux)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_critical_events", faux)
    paquet = sys.modules.get("nokido_agent.app")
    if paquet is not None:
        monkeypatch.setattr(paquet, "forge_critical_events", faux, raising=False)
    monkeypatch.setattr(W, "_broadcast", lambda evt: None)
    monkeypatch.delenv("LAFORGE_VEILLE_EMBED_INLINE", raising=False)
    return recues


def test_fts_absent_chunks_ecrits_et_ecart_signale(alertes, caplog):
    c = _base(avec_fts=False)
    with caplog.at_level(logging.WARNING):
        n = W._step_ingest(c, "wj_fts", "routeur", _refined())
    assert n == 3, n
    assert c.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0] == 3   # presents en base...
    fts = [a for a in alertes if a[0] == "fts_desync:watch_veille"]
    assert len(fts) == 1, alertes                                              # ...et l'ecart SE VOIT
    _cle, niveau, details = fts[0]
    assert niveau == "warn"
    assert details["chunks_sans_fts"] == 3 and details["chunks"] == 3, details
    assert details["job_id"] == "wj_fts" and details["exemple"], details
    assert any("SANS ligne rag_fts" in r.getMessage() for r in caplog.records), \
        [r.getMessage() for r in caplog.records]


def test_fts_present_aucune_alerte(alertes, caplog):
    c = _base(avec_fts=True)
    with caplog.at_level(logging.WARNING):
        n = W._step_ingest(c, "wj_ok", "routeur", _refined())
    assert n == 3, n
    assert c.execute("SELECT COUNT(*) FROM rag_fts").fetchone()[0] == 3
    assert not [a for a in alertes if a[0].startswith("fts_desync")], alertes
    assert not any("SANS ligne rag_fts" in r.getMessage() for r in caplog.records)
