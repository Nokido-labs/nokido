"""NR — l'audit du corps ne purge JAMAIS `rag_fts` par balayage.

DEFAUT MESURE le 2026-09-27. Le hub gelait chaque soir des 22 h. Le detenteur du
verrou d'ecriture de la base RAG etait l'audit NREM1 (`forge_body_regulation_audit`),
dans `ingest_rag` : pour chacune de ses 17 cartes, `_index_fts` faisait

    DELETE FROM rag_fts WHERE chunk_id=?

Or `rag_fts` est `fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED)` :
le plan SQLite est `SCAN rag_fts VIRTUAL TABLE INDEX 0:`, un balayage COMPLET de
l'index lexical, verrou d'ecriture tenu du debut a la fin. Mesures : l'audit lisait
347 Mo en 15 s pour 0 octet ecrit ; episode de verrou 22:53 -> 23:43 le 26/09,
termine 2 s avant la fin du job ; hub fige 2 614 s sur l'heure le 27/09.

Le motif avait DEJA ete corrige ailleurs (`forge_module_cards`, `forge_post_commit`,
2026-09-23) sans atteindre l'audit. La forme sans balayage vit desormais a UN
endroit : `forge_db_path.purger_fts`.

⚠️ Base FABRIQUEE, jamais la vraie : `write_retry` est detourne vers elle.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
_SCAN_COMPLET = re.compile(r"SCAN rag_fts VIRTUAL TABLE INDEX 0:$")


def _modules():
    if str(RACINE) not in sys.path:
        sys.path.insert(0, str(RACINE))
    dbp = pytest.importorskip("nokido_agent.app.forge_db_path")
    aud = pytest.importorskip("nokido_agent.tools.forge_body_regulation_audit")
    return dbp, aud


def _base(tmp_path):
    con = sqlite3.connect(str(tmp_path / "rag.db"), isolation_level=None)
    con.execute("CREATE TABLE rag_chunks(id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT,"
                " role_hint TEXT, author TEXT, ingested_at TEXT, created_at TEXT)")
    con.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text,"
                " source UNINDEXED, domain UNINDEXED)")
    return con


def _verdict(n):
    rows = [{"module": "forge_m%d.py" % i, "organe": "SNC", "role": "lib", "statut": "CABLE",
             "raison": "importe par %d" % i} for i in range(n)]
    return rows, {"SNC": rows}, {"CABLE": n}


def _deux_passes(tmp_path, monkeypatch):
    """Premiere passe = cartes neuves ; seconde = REMPLACEMENT (la purge travaille)."""
    dbp, aud = _modules()
    con = _base(tmp_path)
    monkeypatch.setattr(dbp, "write_retry", lambda op, **_k: op(con))
    aud.ingest_rag(*_verdict(3))
    traces = []
    con.set_trace_callback(traces.append)
    aud.ingest_rag(*_verdict(5))
    con.set_trace_callback(None)
    return con, traces


def test_le_remplacement_laisse_une_seule_ligne_fts_par_carte(tmp_path, monkeypatch):
    """L'EFFET : la seconde passe remplace, elle n'empile pas d'anciennes versions."""
    con, _traces = _deux_passes(tmp_path, monkeypatch)
    cartes = dict(con.execute("SELECT id, text FROM rag_chunks"))
    assert cartes, "aucune carte ecrite : test non concluant"
    for cid, texte in cartes.items():
        lignes = [t for (t,) in con.execute("SELECT text FROM rag_fts WHERE chunk_id=?", (cid,))]
        assert lignes == [texte], (
            "%s : %d ligne(s) FTS au lieu d'une seule a jour -- la purge a rate "
            "l'ancienne version" % (cid, len(lignes)))


def test_aucune_purge_fts_ne_balaie_la_table(tmp_path, monkeypatch):
    """Le contrat qui MORD : le plan de chaque DELETE sur rag_fts est lu par SQLite."""
    con, traces = _deux_passes(tmp_path, monkeypatch)
    purges = [s for s in traces if re.match(r"\s*DELETE\s+FROM\s+rag_fts\b", s, re.I)]
    assert purges, "la seconde passe n'a rien purge : le test ne discrimine pas"
    for sql in purges:
        plan = [r[-1] for r in con.execute("EXPLAIN QUERY PLAN " + sql, ("x",) * sql.count("?"))]
        balayages = [p for p in plan if _SCAN_COMPLET.search(p)]
        assert not balayages, (
            "purge FTS par BALAYAGE COMPLET (chunk_id est UNINDEXED) : %s -> %s. "
            "Sous verrou d'ecriture, c'est ce qui figeait le hub chaque soir a 22 h "
            "(2026-09-27) ; passer par forge_db_path.purger_fts" % (sql[:120], plan))


def test_purger_fts_rend_ce_qu_elle_laisse(tmp_path):
    """Sans mot exploitable, la ligne n'est pas effacee EN SILENCE : elle est rendue."""
    dbp, _aud = _modules()
    con = _base(tmp_path)
    con.execute("INSERT INTO rag_fts(chunk_id, text, source, domain) VALUES('a', 'mot utile', 's', 'd')")
    con.execute("INSERT INTO rag_fts(chunk_id, text, source, domain) VALUES('b', '', 's', 'd')")
    n, laissees = dbp.purger_fts(con, [("a", "mot utile"), ("b", "")])
    assert n == 1 and laissees == ["b"], (n, laissees)
    restants = [c for (c,) in con.execute("SELECT chunk_id FROM rag_fts")]
    assert restants == ["b"], restants
