"""NR : RAGEngine hors hub ne balaie pas rag_chunks sans autorisation explicite.

Aucune connexion reelle : _db_connect est monkeypatche, %NOKIDO_DATA%\embeddings.db jamais ouvert.
"""
import threading

import pytest

from app import forge_rag_engine as rag

_VARS = ("LAFORGE_RAG_FULL_LOAD", "LAFORGE_VEC_SIDECAR_PORT", "LAFORGE_SERVICE_SELF")


def _bare(monkeypatch, tmp_path):
    for v in _VARS:
        monkeypatch.delenv(v, raising=False)
    calls = []

    def _fake():
        calls.append(1)
        raise AssertionError("connexion interdite")

    monkeypatch.setattr(rag, "_db_connect", _fake)
    eng = rag.RAGEngine.__new__(rag.RAGEngine)
    eng._chunks_lock = threading.RLock()
    eng.chunks = []
    eng.rag_dir = tmp_path
    eng.emb_file = tmp_path / "embeddings.json"
    eng.expected_dim = None
    return eng, calls


def test_sans_autorisation_mode_degrade(monkeypatch, tmp_path, caplog):
    import logging
    eng, calls = _bare(monkeypatch, tmp_path)
    with caplog.at_level(logging.WARNING):
        eng._load_embeddings()  # ne leve pas
    assert calls == []
    assert eng.chunks == []
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "8098" in msg and "rag" in msg and "LAFORGE_RAG_FULL_LOAD=1" in msg


def test_search_degrade_erreur_explicite(monkeypatch, tmp_path):
    import asyncio
    eng, calls = _bare(monkeypatch, tmp_path)
    eng._load_embeddings()
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(eng.search("x", k=3))
    assert "8098" in str(ei.value)
    assert calls == []


@pytest.mark.parametrize("var,val", [("LAFORGE_RAG_FULL_LOAD", "1"),
                                     ("LAFORGE_VEC_SIDECAR_PORT", "8098")])
def test_autorise_tente_la_connexion(monkeypatch, tmp_path, var, val):
    eng, calls = _bare(monkeypatch, tmp_path)
    monkeypatch.setenv(var, val)
    eng._load_embeddings()
    assert calls == [1]


def test_service_self_ne_autorise_plus(monkeypatch, tmp_path):
    eng, calls = _bare(monkeypatch, tmp_path)
    monkeypatch.setenv("LAFORGE_SERVICE_SELF", "NokidoX")
    eng._load_embeddings()
    assert calls == []
