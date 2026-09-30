"""NR d'effet — le tri de la veille avant vectorisation (forge_veille_triage_vectorisation).

Ce qu'on protège :
1. `selection` ne retient QUE les chunks de valeur : code/doc réel, longueur
   suffisante, dépôt NON offensif — et écarte tests/fixtures et offensif.
2. `retag` déplace le `domain` des seuls chunks retenus.
3. Le chunk offensif (`exploitgym`) n'est JAMAIS retenu — cohérence avec la purge.

Hermétique : base SQLite temporaire, aucune connexion à la vraie base RAG.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "app"))
import forge_veille_triage_vectorisation as tri


def _db(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, "
                 "text TEXT, domain TEXT, embedding BLOB, embedding_model TEXT)")
    rows = [
        # (id, source, texte, domain) — embedding NULL, embedding_model NULL
        ("v1", "gemini_cli/src/core/agent.rs", "x" * 400, "sdk_gitingest"),   # VALEUR code
        ("v2", "codex/docs/architecture.md", "y" * 300, "sdk_gitingest"),     # VALEUR doc
        ("t1", "codex/core/tests/suite/foo.rs", "z" * 400, "sdk_gitingest"),  # TEST -> exclu
        ("o1", "exploitgym/attacks/rce.py", "w" * 400, "sdk_gitingest"),      # OFFENSIF -> exclu
        ("s1", "gemini_cli/x.rs", "court", "sdk_gitingest"),                  # trop court -> exclu
        ("a1", "gemini_cli/data/blob.json", "j" * 400, "sdk_gitingest"),      # DATA -> exclu
    ]
    conn.executemany(
        "INSERT INTO rag_chunks (id, source, text, domain) VALUES (?,?,?,?)", rows)
    conn.commit()
    return conn


def test_selection_ne_garde_que_la_valeur(tmp_path):
    conn = _db(tmp_path)
    ids = set(tri.selection(conn, "sdk_gitingest"))
    assert ids == {"v1", "v2"}, f"selection incorrecte : {ids}"


def test_le_chunk_offensif_n_est_jamais_retenu(tmp_path):
    conn = _db(tmp_path)
    ids = set(tri.selection(conn, "sdk_gitingest"))
    assert "o1" not in ids, "un chunk exploitgym a été retenu — contraire à la purge"
    # et la garde d'offensivité est bien branchée sur le prédicat partagé
    assert tri._offensif("x/exploitgym/y.py") is True
    assert tri._offensif("gemini_cli/agent.rs") is False


def test_retag_deplace_le_domain_des_seuls_retenus(tmp_path):
    conn = _db(tmp_path)
    ids = tri.selection(conn, "sdk_gitingest")
    n = tri.retag(conn, ids, "veille_code", sec=True)
    assert n == 2
    domaines = dict(conn.execute("SELECT id, domain FROM rag_chunks").fetchall())
    assert domaines["v1"] == "veille_code"
    assert domaines["v2"] == "veille_code"
    # les exclus gardent leur domain d'origine
    assert domaines["t1"] == "sdk_gitingest"
    assert domaines["o1"] == "sdk_gitingest"


def test_dry_run_n_ecrit_rien(tmp_path):
    conn = _db(tmp_path)
    ids = tri.selection(conn, "sdk_gitingest")
    n = tri.retag(conn, ids, "veille_code", sec=False)
    assert n == 0
    restants = conn.execute(
        "SELECT COUNT(*) FROM rag_chunks WHERE domain='sdk_gitingest'").fetchone()[0]
    assert restants == 6, "le dry-run a modifié la base"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
