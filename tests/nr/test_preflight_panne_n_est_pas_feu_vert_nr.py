# -*- coding: utf-8 -*-
"""NR (audit pair 19/10, affirmation 2 verifiee par AGY 1f2afef04) : une panne de la recherche de lecons n'est pas un
feu vert.

Mesure : `preflight_check` rend None (« aucune lecon ») et l'appelant AGIT. Ses trois niveaux (_ragengine_search,
_fts5_search, _like_fallback) avalaient leurs exceptions en []. Base verrouillee, corrompue ou absente -> None -> feu vert
silencieux sur une action critique. Desormais chaque niveau note sa panne ; si les deux niveaux SQLite « toujours
disponibles » (FTS5 et LIKE) sont en panne sans resultat, preflight le DIT ([PREFLIGHT ILLISIBLE]). Un RAGEngine non
charge n'est pas une panne ; une recherche qui a TOURNE et ne trouve rien reste None (absence reelle).
"""
import sqlite3

from nokido_agent.app import forge_self_correction as S


def test_les_niveaux_sqlite_notent_leur_panne(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_DB", tmp_path)              # un dossier : sqlite ne peut pas l'ouvrir
    pannes = []
    assert S._fts5_search("erreur hub", 5, pannes=pannes) == []
    assert S._like_fallback("erreur hub", 5, pannes=pannes) == []
    assert any(p.startswith("fts5") for p in pannes) and any(p.startswith("like") for p in pannes)


def test_tout_le_sqlite_en_panne_n_est_pas_un_feu_vert(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_DB", tmp_path)
    monkeypatch.setattr(S, "_ragengine_search", lambda q, limit=10, pannes=None: [])
    r = S.preflight_check("subprocess", "ecriture critique")
    assert r is not None and r.startswith("[PREFLIGHT ILLISIBLE]")


def test_une_recherche_qui_tourne_et_ne_trouve_rien_reste_none(tmp_path, monkeypatch):
    db = tmp_path / "e.db"
    c = sqlite3.connect(db)
    c.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED)")
    c.execute("CREATE TABLE rag_chunks (id TEXT, text TEXT, source TEXT, role_hint TEXT)")
    c.commit()
    c.close()
    monkeypatch.setattr(S, "_DB", db)
    monkeypatch.setattr(S, "_ragengine_search", lambda q, limit=10, pannes=None: [])
    assert S.preflight_check("subprocess", "ecriture critique") is None
