"""SessionSink — reveil des 4 chemins d'indexation morts (2026-07-14).

Contexte : `ForgeRAGEngine` n'a jamais existe. 4 modules l'importaient dans un
`try/except Exception: pass` -> ImportError avale -> clawhub (skills), silo_engine
(syntheses), silo_fragmenter (pentests), n'ont JAMAIS rien indexe.

Piege sous-jacent : meme avec le bon nom, RAGEngine.add_session_message n'ecrit
QU'EN RAM. Le sink, lui, persiste dans rag_chunks. Ces tests le prouvent sur une
base TEMPORAIRE (jamais la prod).
"""

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_ingest_pipeline import get_session_sink  # noqa: E402

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_chunks (
    id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT, role_hint TEXT,
    author TEXT, ingested_at TEXT, meta TEXT, embedding BLOB
)
"""

# Les 4 sites reveilles : plus aucun ne doit importer le nom mort.
_REVIVED = [
    "forge_clawhub_bridge.py",
    "forge_silo_engine.py",
    "forge_silo_fragmenter.py",
    "forge_handler_evolve.py",
]


@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "embeddings.db"
    conn = sqlite3.connect(db)
    conn.execute(_SCHEMA)
    conn.commit()
    conn.close()
    return db


def test_sink_persists_durably(tmp_db):
    """Le coeur du bug : ce qui n'etait qu'en RAM doit finir en base."""
    sink = get_session_sink(db_path=tmp_db)
    written = asyncio.run(sink.add_session_message("clawhub:demo", "clawhub_skill", "contenu de skill " * 20))
    assert written >= 1, "le sink doit persister au moins un chunk"

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute("SELECT source, text, embedding FROM rag_chunks").fetchall()
    conn.close()

    assert rows, "rag_chunks doit contenir le message"
    assert all(r[0] == "session:clawhub:demo" for r in rows)
    assert any("contenu de skill" in r[1] for r in rows)
    # embedding NULL = attendu : le daemon forge_embed_auto_trigger le remplira
    assert all(r[2] is None for r in rows)


def test_sink_keeps_ragengine_signature():
    """Les 4 sites appellent `await rag.add_session_message(name, role, text)` :
    le sink doit rester substituable sans toucher aux appelants."""
    sink = get_session_sink()
    assert asyncio.iscoroutinefunction(sink.add_session_message)


def test_no_module_imports_dead_forge_rag_engine_name():
    """Anti-regression : `ForgeRAGEngine` n'existe pas -> tout import de ce nom
    recree une zone morte silencieuse (avalee par `except Exception: pass`)."""
    offenders = []
    for name in _REVIVED:
        text = (ROOT / "app" / name).read_text(encoding="utf-8", errors="ignore")
        if "ForgeRAGEngine" in text:
            offenders.append(name)
    assert not offenders, f"nom mort ForgeRAGEngine encore importe dans : {offenders}"
