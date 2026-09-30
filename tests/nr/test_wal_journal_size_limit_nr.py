# -*- coding: utf-8 -*-
"""NR 2026-09-23 — le WAL se RETRECIT de lui-meme (veille SQLite prioritaire owner).

sqlite.org/wal.html (ingere ce jour, `watch:sqlite:wal.html`) : a chaque remise a
zero, SQLite REECRIT le WAL depuis le debut SANS reduire le fichier, SAUF si
`journal_size_limit` est pose. Aucune des deux portes d'ecriture ne le posait :
le WAL de %NOKIDO_DATA%\\embeddings.db est reste a 23 puis 48 Go, V: a 3 Go libres.
"""
import sqlite3

LIMITE_ATTENDUE = 64 * 1024 * 1024


def test_open_writer_pose_journal_size_limit(tmp_path):
    from nokido_agent.app.forge_db_path import JOURNAL_SIZE_LIMIT_OCTETS, open_writer
    c = open_writer(path=str(tmp_path / "t.db"))
    try:
        assert c.execute("PRAGMA journal_size_limit").fetchone()[0] == JOURNAL_SIZE_LIMIT_OCTETS
    finally:
        c.close()
    assert JOURNAL_SIZE_LIMIT_OCTETS == LIMITE_ATTENDUE


def test_la_seconde_porte_d_ecriture_est_alignee():
    from nokido_agent.app import forge_db
    assert any("journal_size_limit=%d" % LIMITE_ATTENDUE in p for p in forge_db._PRAGMAS_RW)


def test_priorite_memoire_basse_posee_et_dite():
    """Veille RAM (doc Microsoft ingeree) : le job de fond cede aussi la RAM."""
    import os
    from nokido_agent.tools import forge_veille_clone_ingest as ci
    issue = ci.priorite_memoire(ci.MEMORY_PRIORITY_LOW)
    try:
        if os.name == "nt":
            assert issue == "ok niveau %d" % ci.MEMORY_PRIORITY_LOW, issue
        else:
            assert issue == "sans objet hors Windows"
    finally:
        ci.priorite_memoire(ci.MEMORY_PRIORITY_NORMAL)   # rendre la main a pytest


def test_le_wal_retrecit_apres_checkpoint(tmp_path):
    """Chemin reel : un WAL gonfle par des ecritures redescend sous la limite."""
    from nokido_agent.app.forge_db_path import open_writer
    db = str(tmp_path / "w.db")
    c = open_writer(path=db)
    c.execute("PRAGMA journal_size_limit=65536")      # petite limite pour le test
    c.execute("CREATE TABLE t (x BLOB)")
    for _ in range(300):
        c.execute("INSERT INTO t VALUES (randomblob(4096))")
    wal = tmp_path / "w.db-wal"
    assert wal.stat().st_size > 65536
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.execute("INSERT INTO t VALUES (1)")             # remise a zero effective
    c.execute("PRAGMA wal_checkpoint(PASSIVE)")
    assert wal.stat().st_size <= 65536 + 64 * 1024
    c.close()
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM t").fetchone()[0] == 301
