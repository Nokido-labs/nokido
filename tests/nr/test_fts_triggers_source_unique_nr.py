"""Non-regression : l'index lexical du moteur SUIT sa source, sans rebuild ni rattrapage.

Defaut mesure le 2026-09-01. `rag_chunks` portait CINQ triggers -- deux snapshots, un
garde de palier, et DEUX pour la file de synchronisation Qdrant -- mais AUCUN pour
`rag_chunks_fts`. Le canal vectoriel etait donc tenu a jour automatiquement, le canal
lexical laisse a des ecritures manuelles dispersees. Or une FTS5 a contenu externe sans
declencheur DERIVE par construction : 702 180 chunks manquants sur 2 030 594, soit toute
la veille recemment ingeree, invisible a `forge_rag_engine._lexical()`.

Ces tests portent sur l'EFFET, pas sur la presence du DDL :

  1. un chunk insere est trouvable TOUT DE SUITE (c'est la definition de « source
     unique » : plus de fenetre pendant laquelle la memoire ignore ce qu'elle contient) ;
  2. une reecriture remplace vraiment l'ancien texte -- un index lexical qui sert un
     texte perime est pire qu'un index vide, il ment ;
  3. une suppression ne laisse pas d'orphelin (`fts5: missing row N from content table`
     faisait echouer toute recherche qui le touchait) ;
  4. un UPDATE d'embedding ne casse pas l'index -- c'est l'ecriture LA PLUS FREQUENTE
     de la base, et le declencheur ne doit pas s'y reveiller ;
  5. poser est idempotent, retirer rend l'etat d'avant (un geste de schema sur une base
     de 21 Go doit etre annulable).

Zero service externe : base SQLite jetable en tmp_path, `open_writer`/`db_path` detournes.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (doublure) (l.54)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import forge_db_path  # noqa: E402
import forge_fts_repair as repair  # noqa: E402


@pytest.fixture()
def base(tmp_path, monkeypatch):
    chemin = tmp_path / "embeddings.db"
    conn = sqlite3.connect(chemin)
    conn.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, "
                 "source TEXT, domain TEXT, embedding BLOB)")
    conn.execute("CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, source, domain, "
                 "content='rag_chunks', content_rowid='rowid')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(forge_db_path, "open_writer",
                        lambda timeout=30.0: sqlite3.connect(chemin, timeout=timeout,
                                                             isolation_level=None))
    monkeypatch.setattr(forge_db_path, "db_path", lambda: str(chemin))
    repair.poser_triggers()
    return chemin


def _match(chemin: Path, terme: str) -> int:
    conn = sqlite3.connect(chemin)
    try:
        return conn.execute("SELECT count(*) FROM rag_chunks_fts "
                            "WHERE rag_chunks_fts MATCH ?", (terme,)).fetchone()[0]
    finally:
        conn.close()


def _ecrire(chemin: Path, sql: str, args: tuple = ()):
    conn = sqlite3.connect(chemin, isolation_level=None)
    try:
        conn.execute(sql, args)
    finally:
        conn.close()


def test_un_chunk_insere_est_trouvable_immediatement(base):
    """Plus de fenetre pendant laquelle la memoire ignore ce qu'elle contient."""
    _ecrire(base, "INSERT INTO rag_chunks(id, text, source, domain) VALUES (?,?,?,?)",
            ("c1", "AUTH_FAILED OpenVPN certificat", "logs/vpn.txt", "veille_code"))
    assert _match(base, "AUTH_FAILED") == 1
    assert _match(base, "OpenVPN") == 1


def test_une_reecriture_ne_laisse_pas_l_ancien_texte(base):
    """Un index qui sert un texte perime ment ; c'est pire qu'un index vide."""
    _ecrire(base, "INSERT INTO rag_chunks(id, text, source, domain) VALUES (?,?,?,?)",
            ("c1", "ancien terme obsolete", "s.py", "d"))
    assert _match(base, "obsolete") == 1

    _ecrire(base, "UPDATE rag_chunks SET text = ? WHERE id = ?", ("nouveau contenu", "c1"))

    assert _match(base, "obsolete") == 0, "l'index sert encore l'ancien texte"
    assert _match(base, "nouveau") == 1


def test_une_suppression_ne_laisse_pas_d_orphelin(base):
    """`fts5: missing row N from content table` faisait echouer toute recherche."""
    _ecrire(base, "INSERT INTO rag_chunks(id, text, source, domain) VALUES (?,?,?,?)",
            ("c1", "chunk ephemere unique", "s.py", "d"))
    assert _match(base, "ephemere") == 1

    _ecrire(base, "DELETE FROM rag_chunks WHERE id = ?", ("c1",))

    assert _match(base, "ephemere") == 0
    conn = sqlite3.connect(base)
    try:
        # L'index ne doit contenir AUCUN document de plus que la source.
        assert (conn.execute("SELECT count(*) FROM rag_chunks_fts_docsize").fetchone()[0]
                == conn.execute("SELECT count(*) FROM rag_chunks").fetchone()[0])
    finally:
        conn.close()


def test_update_embedding_ne_casse_pas_l_index(base):
    """L'ecriture LA PLUS FREQUENTE de la base ne doit pas reveiller le declencheur."""
    _ecrire(base, "INSERT INTO rag_chunks(id, text, source, domain) VALUES (?,?,?,?)",
            ("c1", "vectorisation differee lexical", "s.py", "d"))
    _ecrire(base, "UPDATE rag_chunks SET embedding = ? WHERE id = ?", (b"\x00" * 16, "c1"))

    assert _match(base, "lexical") == 1
    ddl = sqlite3.connect(base).execute(
        "SELECT sql FROM sqlite_master WHERE name='rag_chunks_fts_au'").fetchone()[0]
    assert "UPDATE OF text, source, domain" in ddl, \
        "un UPDATE nu reindexerait a chaque ecriture d'embedding"


def test_insert_or_replace_ne_laisse_pas_de_fantome(base):
    """PIEGE SQLITE PAYE EN PRODUCTION le 2026-09-01, 20 minutes apres la pose.

    Le DELETE implicite d'un `INSERT OR REPLACE` NE DECLENCHE PAS les triggers DELETE,
    sauf `PRAGMA recursive_triggers = ON` -- qui est OFF par defaut et se regle PAR
    CONNEXION, donc ingarantissable : `INSERT OR REPLACE INTO rag_chunks` est ecrit sur
    17 sites actifs (forge_conversation_logger, forge_mcp_registry, forge_ingest_pipeline...).

    Sans garde, chaque remplacement laissait l'ancienne version indexee : un FANTOME.
    Et les fantomes sont PIRES que les manquants -- ils faussent les frequences
    documentaires de BM25, donc le classement de TOUTES les recherches (501 255 entrees
    mortes mesurees en juillet, 27 % de l'index).

    Constate en prod par un ecart NEGATIF (index 2 030 596 > source 2 030 595), sur un
    snapshot COHERENT -- deux COUNT en autocommit auraient pu n'etre qu'un artefact.
    """
    _ecrire(base, "INSERT INTO rag_chunks(id, text, source, domain) VALUES (?,?,?,?)",
            ("c1", "version initiale alphaunique", "s.py", "d"))
    assert _match(base, "alphaunique") == 1

    _ecrire(base, "INSERT OR REPLACE INTO rag_chunks(id, text, source, domain) "
                  "VALUES (?,?,?,?)", ("c1", "version remplacee betaunique", "s.py", "d"))

    assert _match(base, "alphaunique") == 0, "FANTOME : l'ancienne version reste indexee"
    assert _match(base, "betaunique") == 1
    conn = sqlite3.connect(base)
    try:
        assert (conn.execute("SELECT count(*) FROM rag_chunks_fts_docsize").fetchone()[0]
                == conn.execute("SELECT count(*) FROM rag_chunks").fetchone()[0]), \
            "l'index compte plus de documents que la source"
    finally:
        conn.close()


def test_poser_est_idempotent_et_retirer_rend_l_etat_d_avant(base):
    assert repair.triggers_etat()["synchronise"] is True
    rejoue = repair.poser_triggers()
    assert rejoue["faits"] == [], "poser deux fois a recree des declencheurs"

    retrait = repair.poser_triggers(retirer=True)
    assert retrait["apres"]["synchronise"] is False
    assert retrait["apres"]["poses"] == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
