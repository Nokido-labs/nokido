"""NR -- conversation_log : surveille, JAMAIS purge tant que rien n'est distille (2026-09-24).

Decision owner : « purge intelligente SI TRAITE, ou compacte, apres en avoir tire la
substantifique moelle ». Mesure du jour : 8 Mo sur six mois, aucun distillateur ne
consomme la table, 0 session couverte par conv_archives -> aucune ligne eligible.
Ce NR fige : la retention MESURE et SIGNALE au-dela du seuil, elle ne supprime rien.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))

import forge_log_retention as lr  # noqa: E402

# PAYE LE 2026-09-29 (CI GitHub run 36572282572, 2e passage) : sur une base temporaire de
# 1,8 Mo, `_surveiller_conversation_log` est reste 30 s dans `con.execute` -- l'attente de
# verrou de son `connect(timeout=30)`, EGALE au timeout pytest par test (30 s). Le thread
# de pytest-timeout a donc tue TOUTE la suite pure (12 900 tests, SUITE_INCOMPLETE) au lieu
# de faire echouer CE test. Passe au 1er passage et la veille : intermittent, sous charge.
# Cause de l'attente NON etablie (verrou externe ou disque sature) -- on ne l'accuse pas.
# Borne au-dessus de l'attente de verrou : une base verrouillee rend `skipped`, et le test
# echoue en le DISANT au lieu d'emporter la suite. Meme remede que le 2026-09-27 (446730160).
pytestmark = pytest.mark.timeout(120)


def _base(tmp_path, n=5, taille=100):
    (tmp_path / "RAG").mkdir()
    db = tmp_path / "RAG" / "embeddings.db"
    cx = sqlite3.connect(db)
    cx.execute("CREATE TABLE conversation_log (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, "
               "ts TEXT NOT NULL, agent TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, "
               "content_hash TEXT NOT NULL, turn_index INTEGER, meta TEXT)")
    for i in range(n):
        cx.execute("INSERT INTO conversation_log (session_id, ts, agent, role, content, content_hash) "
                   "VALUES (?, ?, 'CLAUDE', 'human', ?, ?)",
                   ("s%d" % i, "2026-01-0%dT00:00:00" % (i + 1), "x" * taille, "h%d" % i))
    cx.commit()
    cx.close()
    return db


def _compte(db):
    cx = sqlite3.connect(db)
    try:
        return cx.execute("SELECT COUNT(*) FROM conversation_log").fetchone()[0]
    finally:
        cx.close()


def test_la_retention_ne_supprime_aucune_ligne(tmp_path, monkeypatch):
    db = _base(tmp_path)
    monkeypatch.setattr(lr, "ROOT", tmp_path)
    r = lr._surveiller_conversation_log(dry=False)
    assert "skipped" not in r, "base non lue (verrou ?) : %r" % r
    assert r["purgees"] == 0 and r["lignes"] == 5
    assert _compte(db) == 5, "une ligne jamais distillee a ete supprimee"


def test_au_dela_du_seuil_elle_signale_sans_toucher(tmp_path, monkeypatch):
    db = _base(tmp_path, n=3, taille=600_000)
    monkeypatch.setattr(lr, "ROOT", tmp_path)
    monkeypatch.setattr(lr, "CONV_LOG_SIGNAL_MO", 1.0)
    r = lr._surveiller_conversation_log(dry=False)
    assert "skipped" not in r, "base non lue (verrou ?) : %r" % r
    assert r["sur_seuil"] is True and r["mo"] > 1.0
    assert _compte(db) == 3


def test_elle_est_cablee_dans_le_passage_quotidien():
    src = (RACINE / "tools" / "forge_log_retention.py").read_text(encoding="utf-8")
    i = src.index("def run_retention(")
    assert '"conversation_log": _surveiller_conversation_log(dry)' in src[i:i + 800]
