"""NR 05/11 -- Places reservees aux fiches memoire dans le rappel lexical FTS5 (Chantier 1/4).

Contrat :
- 300 fragments tiers tres pertinents pour query ('python cache') + 3 fiches memory:x moins bien classees.
- Sans canal reserve (LAFORGE_RAG_PLACES_MEMOIRE=0) : les fiches memory sont hors top 200 et absentes des hits.
- Avec canal reserve (defaut ou > 0) : les 3 fiches memory sont remontees dans les hits.
- Panne du second canal FTS (syntaxe fts / exception) : les hits du premier canal sont conserves intacts.
- Fusion des scores : max(existant, score_memoire_normalise).
"""
import os
import sqlite3
import pytest
from nokido_agent.app import forge_rag_engine as fre


@pytest.fixture
def fake_rag_db(tmp_path):
    db_path = tmp_path / "test_embeddings.db"
    conn = sqlite3.connect(str(db_path))
    # Creation des tables rag_chunks et rag_chunks_fts conformes
    conn.execute("""
        CREATE TABLE rag_chunks (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT UNIQUE,
            text TEXT,
            source TEXT,
            domain TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(
            text,
            source,
            domain,
            content='rag_chunks',
            content_rowid='rowid'
        )
    """)

    # Ingestion de 300 chunks tiers tres pertinents
    for i in range(300):
        cid = f"repo_chunk_{i}"
        txt = f"python cache optimization performance repetition python cache {i}"
        src = f"github:repo_{i % 5}"
        dom = "code"
        cur = conn.execute(
            "INSERT INTO rag_chunks (id, text, source, domain) VALUES (?, ?, ?, ?)",
            (cid, txt, src, dom),
        )
        rid = cur.lastrowid
        conn.execute(
            "INSERT INTO rag_chunks_fts (rowid, text, source, domain) VALUES (?, ?, ?, ?)",
            (rid, txt, src, dom),
        )

    # Ingestion de 3 fiches memoire moins denses en repetition (moins bien classees globalement)
    for j in range(3):
        cid = f"memory:fiche_{j}"
        txt = f"note memoire python cache configuration regle {j}"
        src = f"memory:fiche_{j}"
        dom = "memory"
        cur = conn.execute(
            "INSERT INTO rag_chunks (id, text, source, domain) VALUES (?, ?, ?, ?)",
            (cid, txt, src, dom),
        )
        rid = cur.lastrowid
        conn.execute(
            "INSERT INTO rag_chunks_fts (rowid, text, source, domain) VALUES (?, ?, ?, ?)",
            (rid, txt, src, dom),
        )

    conn.commit()
    conn.close()
    return db_path


def test_places_reservees_memoire_activees(fake_rag_db, monkeypatch):
    monkeypatch.setattr(fre, "_EMBEDDINGS_DB", fake_rag_db)
    monkeypatch.setenv("LAFORGE_RAG_PLACES_MEMOIRE", "40")

    engine = fre.RAGEngine.__new__(fre.RAGEngine)
    # 303 chunks au total
    chunks = [{"id": f"repo_chunk_{i}"} for i in range(300)]
    for j in range(3):
        chunks.append({"id": f"memory:fiche_{j}"})
    engine.chunks = chunks
    engine.bm25_index = None

    scores = engine._scores_lexicaux("python cache")

    # Verifier que les 3 fiches memoire ont un score non nul grace au canal reserve
    for j in range(3):
        idx = engine._lex_map[f"memory:fiche_{j}"]
        assert scores[idx] > 0.0, f"memory:fiche_{j} doit etre presente dans les hits"


def test_places_reservees_memoire_desactivees_env_zero(fake_rag_db, monkeypatch):
    monkeypatch.setattr(fre, "_EMBEDDINGS_DB", fake_rag_db)
    monkeypatch.setenv("LAFORGE_RAG_PLACES_MEMOIRE", "0")

    engine = fre.RAGEngine.__new__(fre.RAGEngine)
    chunks = [{"id": f"repo_chunk_{i}"} for i in range(300)]
    for j in range(3):
        chunks.append({"id": f"memory:fiche_{j}"})
    engine.chunks = chunks
    engine.bm25_index = None

    scores = engine._scores_lexicaux("python cache")

    # Avec canal coupe (0), les 200 premiers etant des fragments tiers, les fiches sont evincees
    for j in range(3):
        idx = engine._lex_map[f"memory:fiche_{j}"]
        assert scores[idx] == 0.0, f"memory:fiche_{j} ne doit pas etre remontee si env=0"


def _moteur(ids_en_plus=()):
    engine = fre.RAGEngine.__new__(fre.RAGEngine)
    engine.chunks = (
        [{"id": f"repo_chunk_{i}"} for i in range(300)]
        + [{"id": f"memory:fiche_{j}"} for j in range(3)]
        + [{"id": i} for i in ids_en_plus]
    )
    engine.bm25_index = None
    return engine


def test_le_canal_est_coupe_par_defaut(fake_rag_db, monkeypatch):
    """Mandat owner du 1/9 : pas de changement du classement effectif sans baseline battue."""
    monkeypatch.setattr(fre, "_EMBEDDINGS_DB", fake_rag_db)
    monkeypatch.delenv("LAFORGE_RAG_PLACES_MEMOIRE", raising=False)
    engine = _moteur()
    scores = engine._scores_lexicaux("python cache")
    for j in range(3):
        assert scores[engine._lex_map[f"memory:fiche_{j}"]] == 0.0


def test_un_depot_nomme_memory_ne_prend_pas_les_places(fake_rag_db, monkeypatch):
    """`source:memory` vise le MOT : `github:x/mcp-memory-service` le contient (mesure 5/11)."""
    conn = sqlite3.connect(str(fake_rag_db))
    ids = []
    for k in range(5):
        cid = f"faux_{k}"
        ids.append(cid)
        # Hors des 200 du premier canal : seul le canal reserve pourrait leur donner un score.
        txt = "python cache " + "remplissage " * 40 + f"faux {k}"
        src = f"github:x/mcp-memory-service/doc_{k}.md"
        rid = conn.execute("INSERT INTO rag_chunks (id, text, source, domain) VALUES (?, ?, ?, 'code')",
                           (cid, txt, src)).lastrowid
        conn.execute("INSERT INTO rag_chunks_fts (rowid, text, source, domain) VALUES (?, ?, ?, 'code')",
                     (rid, txt, src))
    conn.commit()
    conn.close()
    monkeypatch.setattr(fre, "_EMBEDDINGS_DB", fake_rag_db)
    monkeypatch.setenv("LAFORGE_RAG_PLACES_MEMOIRE", "40")
    engine = _moteur(ids)
    scores = engine._scores_lexicaux("python cache")
    for j in range(3):
        assert scores[engine._lex_map[f"memory:fiche_{j}"]] > 0.0
    for cid in ids:
        assert scores[engine._lex_map[cid]] == 0.0, cid


def test_une_panne_du_second_canal_preserve_le_premier(fake_rag_db, monkeypatch):
    vrai = sqlite3.connect

    class _Panne:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, params=()):
            if params and "memory" in str(params[0]):
                raise sqlite3.OperationalError("panne simulee")
            return self.conn.execute(sql, params)

        def close(self):
            self.conn.close()

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: _Panne(vrai(*a, **k)))
    monkeypatch.setattr(fre, "_EMBEDDINGS_DB", fake_rag_db)
    monkeypatch.setenv("LAFORGE_RAG_PLACES_MEMOIRE", "40")
    scores = _moteur()._scores_lexicaux("python cache")
    assert sum(1 for s in scores if s > 0.0) == 200


def test_une_valeur_illisible_coupe_le_canal(fake_rag_db, monkeypatch):
    monkeypatch.setattr(fre, "_EMBEDDINGS_DB", fake_rag_db)
    monkeypatch.setenv("LAFORGE_RAG_PLACES_MEMOIRE", "invalid_number")

    engine = fre.RAGEngine.__new__(fre.RAGEngine)
    chunks = [{"id": f"repo_chunk_{i}"} for i in range(300)]
    for j in range(3):
        chunks.append({"id": f"memory:fiche_{j}"})
    engine.chunks = chunks
    engine.bm25_index = None

    scores = engine._scores_lexicaux("python cache")

    # Le premier canal a remonte des chunks repo
    non_zero = sum(1 for s in scores if s > 0.0)
    assert non_zero == 200, "Le premier canal doit renvoyer ses 200 hits malgre l'erreur du second canal"
