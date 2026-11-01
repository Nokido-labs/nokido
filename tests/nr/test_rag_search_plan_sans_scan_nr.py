"""NR — le chemin `rag action=search` ne balaie JAMAIS rag_chunks (cliquet sur le plan).

Mesure 24/10 : 81 Go lus en 40 min, 2 recherches expirees a 120 s. Base FACTICE au meme
schema (index PK, index partiel idx_embedding_null, colonnes virtuelles, FTS) ; aucune
ecriture sur %NOKIDO_DATA%\embeddings.db. Un SCAN de rag_chunks n'est admis que s'il est COUVRANT
(index seul, aucune page de texte).
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_rag_sql as S  # noqa: E402

SCHEMA = """
CREATE TABLE rag_chunks (
  id TEXT PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL, domain TEXT DEFAULT 'general',
  embedding BLOB, active INTEGER DEFAULT 1, origin TEXT,
  ext TEXT GENERATED ALWAYS AS (CASE WHEN source LIKE '%.py' THEN 'py' ELSE '' END) VIRTUAL,
  folder TEXT GENERATED ALWAYS AS (CASE WHEN instr(source,'/')>0 THEN substr(source,1,instr(source,'/')-1) ELSE '' END) VIRTUAL);
CREATE INDEX idx_ext ON rag_chunks(ext);
CREATE INDEX idx_rag_chunks_active ON rag_chunks(active);
CREATE INDEX idx_embedding_null ON rag_chunks(id) WHERE embedding IS NULL;
CREATE INDEX idx_emb_null_origin ON rag_chunks(origin) WHERE embedding IS NULL;
CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, source, content='rag_chunks', content_rowid='rowid');
"""


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    c.executemany("INSERT INTO rag_chunks(id,text,source,embedding) VALUES(?,?,?,?)",
                  [("a", "alpha beta", "app/x.py", b"1"), ("b", "gamma", "doc/y.md", None),
                   ("c", "alpha", "app/z.py", b"1")])
    c.execute("INSERT INTO rag_chunks_fts(rowid,text,source) SELECT rowid,text,source FROM rag_chunks")
    yield c
    c.close()


def _plan(c, sql, n_params):
    return [r[3] for r in c.execute("EXPLAIN QUERY PLAN " + sql, ("x",) * n_params)]


def _scan_nu(plan):
    """Lignes SCAN de la table (ou alias c) qui ne sont PAS un index couvrant.

    24/10 : la base vivante porte AUSSI `idx_emb_null_origin` (partiel, sur origin), que
    le planificateur choisit pour `embedding IS NULL` -- NON couvrant, donc une relecture
    de ligne par id manquant (pid 16232, disque sature). Seul un index COUVRANT passe."""
    return [d for d in plan if re.search(r"\bSCAN (rag_chunks|c)\b", d)
            and "COVERING INDEX" not in d and d != "SCAN rag_chunks USING INDEX idx_embedding_null"]


def test_ids_sans_embedding_ne_lit_aucune_colonne_de_la_table(con):
    """`idx_embedding_null` n'est pas affiche COVERING (curseur table ouvert, lecture
    differee) : la preuve est dans le bytecode -- aucun `Column` sur le curseur table."""
    racine = con.execute("SELECT rootpage FROM sqlite_master WHERE name='rag_chunks'").fetchone()[0]
    prog = list(con.execute("EXPLAIN " + S.SQL_IDS_SANS_EMBEDDING))
    curseurs_table = {r[2] for r in prog if r[1] == "OpenRead" and r[3] == racine}
    lus = [r for r in prog if r[1] == "Column" and r[2] in curseurs_table]
    assert curseurs_table and not lus, lus


@pytest.mark.parametrize("sql,n", [
    (S.SQL_IDS_TOUS, 0), (S.SQL_IDS_SANS_EMBEDDING, 0), (S.SQL_FTS_CANDIDATS, 1),
    (S.SQL_META_PAR_IDS % "?,?", 2), (S.SQL_EXT_PAR_IDS % "?,?", 2)])
def test_plan_sans_scan_complet(con, sql, n):
    assert not _scan_nu(_plan(con, sql, n)), _plan(con, sql, n)


def test_cliquet_detecte_l_ancienne_requete(con):
    """Garde-fou du garde-fou : l'ancienne requete DOIT etre vue comme un balayage."""
    ancien = "SELECT id, ext, folder FROM rag_chunks WHERE embedding IS NOT NULL"
    assert _scan_nu(_plan(con, ancien, 0))


def test_ids_equivalents_a_l_ancienne_selection(con):
    ancien = [r[0] for r in con.execute("SELECT id FROM rag_chunks WHERE embedding IS NOT NULL")]
    assert sorted(S.ids_avec_embedding(con)) == sorted(ancien) == ["a", "c"]


def test_registre_utilise_le_module_borne():
    src = (ROOT / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    assert "SELECT id, ext, folder FROM rag_chunks" not in src
    assert "ids_avec_embedding" in src
