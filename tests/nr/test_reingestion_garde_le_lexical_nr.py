"""NR 2026-10-01 : re-ingerer un depot ne sort plus ses chunks INCHANGES du lexical.

Mecanisme mesure sur une base jetable aux triggers de prod : `rag_chunks_fts_bi` (BEFORE INSERT)
retire l'entree `rag_chunks_fts` de l'id existant AVANT qu'un INSERT OR IGNORE soit ignore. En base,
un echantillon 1/500 de sdk_gitingest donnait 38 % des chunks de septembre absents du lexical, et
40/40 sources touchees avaient ete re-ingerees. Ce test passe par le chemin REEL de l'ingesteur
(`ingest_file` sur un dump au format gitingest), deux fois, sur le schema de prod.
"""
import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = """
CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, text TEXT, domain TEXT,
                         created_at, ingested_at TEXT, active INTEGER DEFAULT 1, superseded_by TEXT);
CREATE TABLE rag_fts (chunk_id TEXT, text TEXT, source TEXT, domain TEXT);
CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, source, domain,
                         content='rag_chunks', content_rowid='rowid');
CREATE TRIGGER rag_chunks_fts_bi BEFORE INSERT ON rag_chunks BEGIN
  INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, source, domain)
  SELECT 'delete', rowid, text, source, domain FROM rag_chunks WHERE id = new.id;
END;
CREATE TRIGGER rag_chunks_fts_ai AFTER INSERT ON rag_chunks BEGIN
  INSERT INTO rag_chunks_fts(rowid, text, source, domain)
  VALUES (new.rowid, new.text, new.source, new.domain);
END;
"""

DUMP = ("=" * 48 + "\nFILE: src/serveur.py\n" + "=" * 48 + "\n"
        + "\n".join("def handler_%d(requete):\n    return traiter_quokka(requete, %d)\n" % (i, i)
                    for i in range(40))
        + "\n" + "=" * 48 + "\nFILE: src/outil.py\n" + "=" * 48 + "\n"
        + "\n".join("def outil_%d():\n    return 'wombat %d'\n" % (i, i) for i in range(40)) + "\n")


def _module(nom, rel):
    spec = importlib.util.spec_from_file_location(nom, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _lexical(conn, mot):
    return conn.execute("SELECT COUNT(*) FROM rag_chunks_fts WHERE rag_chunks_fts MATCH ?",
                        (mot,)).fetchone()[0]


def test_reingerer_un_dump_sdk_garde_le_lexical(tmp_path):
    m = _module("forge_gitingest_sdk_ingest_lexical_nr", "tools/forge_gitingest_sdk_ingest.py")
    dump = tmp_path / "gitingest_exemple.txt"
    dump.write_text(DUMP, encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)

    ins1, _sk1 = m.ingest_file(dump, conn)
    assert ins1 > 0, "le dump de test n'a produit aucun chunk : format non reconnu"
    avant = (_lexical(conn, "quokka"), _lexical(conn, "wombat"))
    assert avant[0] > 0 and avant[1] > 0

    ins2, sk2 = m.ingest_file(dump, conn)
    assert ins2 == 0 and sk2 == ins1, (ins2, sk2, ins1)
    assert (_lexical(conn, "quokka"), _lexical(conn, "wombat")) == avant, (
        "la re-ingestion a sorti des chunks inchanges du lexical")
