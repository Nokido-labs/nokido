"""NR 2026-10-01 : la regle golden `laforge-insert-or-ignore-rag-chunks` (cliquet decide par l'owner).

Le trigger `rag_chunks_fts_bi` (BEFORE INSERT) retire l'entree lexicale de l'id existant AVANT qu'un
INSERT OR IGNORE soit ignore : un chunk inchange re-vu sort de `rag_chunks_fts` (15 213 chunks actifs
de claude_docs mesures absents, 40/40 sources sdk_gitingest echantillonnees re-ingerees). Le cliquet
interdit tout NOUVEAU site ; l'exception est explicite et locale (marqueur `existence-verifiee`).
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGLE = "laforge-insert-or-ignore-rag-chunks"


def _module():
    spec = importlib.util.spec_from_file_location(
        "forge_golden_rules_ast_ior_nr", ROOT / "tools" / "forge_golden_rules_ast.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _regle(src):
    return [f for f in _module().scan_source("tools/exemple.py", src, []) if f["rule"] == REGLE]


def test_un_insert_or_ignore_dans_rag_chunks_est_une_erreur():
    src = ('def f(conn, cid, t):\n'
           '    conn.execute("INSERT OR IGNORE INTO rag_chunks (id, text) VALUES (?, ?)", (cid, t))\n')
    trouve = _regle(src)
    assert len(trouve) == 1 and trouve[0]["severity"] == "ERROR", trouve
    assert trouve[0]["line"] == 2


def test_les_tables_voisines_ne_sont_pas_visees():
    src = ('def f(conn):\n'
           '    conn.execute("INSERT OR IGNORE INTO rag_chunks_fts (rowid) VALUES (1)")\n'
           '    conn.execute("INSERT OR REPLACE INTO rag_chunks (id, text) VALUES (?, ?)", ("a", "b"))\n')
    assert _regle(src) == []


def test_le_marqueur_d_existence_verifiee_exempte_le_site():
    src = ('def f(conn, cid, t):\n'
           '    # existence-verifiee : on n ecrit pas si l id existe\n'
           '    if conn.execute("SELECT 1 FROM rag_chunks WHERE id = ?", (cid,)).fetchone():\n'
           '        return\n'
           '    conn.execute("INSERT OR IGNORE INTO rag_chunks (id, text) VALUES (?, ?)", (cid, t))\n')
    assert _regle(src) == []


def test_la_forme_where_not_exists_sur_l_id_est_sure():
    src = ('def f(conn, cid, t):\n'
           '    conn.execute(\n'
           '        "INSERT OR IGNORE INTO rag_chunks (id, text) SELECT ?, ? "\n'
           '        "WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)", (cid, t, cid))\n')
    assert _regle(src) == []


def test_un_where_not_exists_sur_une_autre_table_ne_suffit_pas():
    src = ('def f(conn, cid, t):\n'
           '    conn.execute("INSERT OR IGNORE INTO rag_chunks (id, text) SELECT ?, ? "\n'
           '                 "WHERE NOT EXISTS (SELECT 1 FROM rag_meta WHERE id = ?)", (cid, t, cid))\n')
    assert len(_regle(src)) == 1


def test_la_forme_where_not_exists_n_arme_pas_le_trigger():
    """Preuve sur sqlite (triggers de prod) : la forme sure laisse l'entree lexicale intacte."""
    import sqlite3
    c = sqlite3.connect(":memory:")
    c.executescript("""
    CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT);
    CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, source, domain, content='rag_chunks', content_rowid='rowid');
    CREATE TRIGGER rag_chunks_fts_bi BEFORE INSERT ON rag_chunks BEGIN
      INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, source, domain)
      SELECT 'delete', rowid, text, source, domain FROM rag_chunks WHERE id = new.id;
    END;
    CREATE TRIGGER rag_chunks_fts_ai AFTER INSERT ON rag_chunks BEGIN
      INSERT INTO rag_chunks_fts(rowid, text, source, domain) VALUES (new.rowid, new.text, new.source, new.domain);
    END;
    """)
    sql = ("INSERT OR IGNORE INTO rag_chunks (id, text, source, domain) SELECT ?, ?, ?, ? "
           "WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)")
    for _ in range(2):
        cur = c.execute(sql, ("a", "alpha bravo", "s", "d", "a"))
    assert cur.rowcount == 0, "la seconde passe ne doit rien inserer (compteurs inchanges)"
    assert c.execute("SELECT COUNT(*) FROM rag_chunks_fts WHERE rag_chunks_fts MATCH 'alpha'").fetchone()[0] == 1


def test_la_regle_ne_se_denonce_pas_elle_meme():
    """Un instrument ne lit jamais son propre vocabulaire : le message de la regle et
    ses commentaires ne doivent pas contenir le motif qu'elle cherche."""
    src = (ROOT / "tools" / "forge_golden_rules_ast.py").read_text(encoding="utf-8", errors="replace")
    assert _module().scan_source("tools/forge_golden_rules_ast.py", src, []) is not None
    assert [f for f in _module().scan_source("tools/forge_golden_rules_ast.py", src, [])
            if f["rule"] == REGLE] == []


def test_l_ingesteur_de_doc_corrige_est_exempte_par_son_marqueur():
    src = (ROOT / "tools" / "forge_ingest_llms_txt.py").read_text(encoding="utf-8", errors="replace")
    assert [f for f in _module().scan_source("tools/forge_ingest_llms_txt.py", src, [])
            if f["rule"] == REGLE] == []
