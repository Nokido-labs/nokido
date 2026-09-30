# -*- coding: utf-8 -*-
"""NR - le DELETE rag_fts par chunk n'est plus inconditionnel (2026-09-05).

`rag_fts` est un FTS5 AUTONOME : `chunk_id` y est UNINDEXED, donc
`DELETE FROM rag_fts WHERE chunk_id=?` balaie toute la table (2 M lignes). Avant
ce jour, `forge_watch_agent._step_ingest` l'emettait pour CHAQUE chunk insere,
y compris les ids NEUFS ou il n'y a rien a effacer : un papier de 34 chunks =
34 balayages, le disque a 100 % pendant les backfills (mesure sur le rattrapage
des veilles). Meme famille que 8bcb4f6e (ingesteur GitHub, 04/08).

Le contrat verrouille ici, par lecture de la SOURCE (aucune base touchee) :
  1. dans `_step_ingest`, chaque purge FTS du chunk est sous un `if` dont le test
     nomme `_existait` ;
  2. `_existait` est calcule par un SELECT sur la clef primaire de rag_chunks
     AVANT l'INSERT OR REPLACE (sinon l'id existe toujours apres l'insert et le
     test perd son sens) ;

Forme du 28/09 : la purge n'est plus un `DELETE ... WHERE chunk_id=?` (chunk_id
UNINDEXED = balayage complet, cliquet test_fts_jamais_purge_par_colonne_unindexed_nr)
mais `_purger_fts(conn, cid, ancien)` -> forge_db_path.purger_fts, par MATCH sur
l'ANCIEN texte. Ce texte est donc lu (`_ancien`, PK) avant l'insert, et
`_existait = _ancien is not None`. Le contrat ne change pas, sa forme si.
  3. l'INSERT FTS, lui, reste INCONDITIONNEL : le lexical prime, un chunk ecrit
     dans rag_chunks doit etre trouvable en BM25.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app" / "forge_watch_agent.py"


def _corps_step_ingest() -> tuple[ast.FunctionDef, str]:
    if not SRC.exists():
        pytest.skip("forge_watch_agent absent : test non applicable ici")
    texte = SRC.read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(texte)
    for node in ast.walk(arbre):
        if isinstance(node, ast.FunctionDef) and node.name == "_step_ingest":
            return node, ast.get_source_segment(texte, node) or ""
    pytest.fail("_step_ingest introuvable dans forge_watch_agent")


def _appels_sql(fn: ast.FunctionDef, motif: str) -> list[ast.Call]:
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "execute" and node.args:
            a0 = node.args[0]
            sql = ""
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                sql = a0.value
            elif isinstance(a0, ast.JoinedStr):
                sql = "".join(v.value for v in a0.values if isinstance(v, ast.Constant))
            if re.search(motif, sql, re.I):
                out.append(node)
    return out


def _parents(fn: ast.FunctionDef) -> dict[ast.AST, ast.AST]:
    p = {}
    for node in ast.walk(fn):
        for enfant in ast.iter_child_nodes(node):
            p[enfant] = node
    return p


def _sous_un_if_existait(node: ast.AST, parents: dict) -> bool:
    cur = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, ast.If) and any(
            isinstance(n, ast.Name) and n.id == "_existait" for n in ast.walk(cur.test)
        ):
            return True
    return False


def _appels_purge(fn: ast.FunctionDef) -> list[ast.AST]:
    """Toute purge FTS : DELETE litteral (s'il revenait) OU appel du helper par MATCH."""
    helpers = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
               and (getattr(n.func, "id", "") or getattr(n.func, "attr", "")) in ("_purger_fts", "purger_fts")]
    return _appels_sql(fn, r"DELETE\s+FROM\s+rag_fts") + helpers


def test_delete_fts_par_chunk_est_conditionne_par_existait():
    fn, _ = _corps_step_ingest()
    deletes = _appels_purge(fn)
    assert deletes, "aucune purge rag_fts dans _step_ingest : le contrat a change, relire"
    parents = _parents(fn)
    nus = [d.lineno for d in deletes if not _sous_un_if_existait(d, parents)]
    assert not nus, (
        f"DELETE FROM rag_fts WHERE chunk_id inconditionnel aux lignes {nus} : "
        "un balayage FTS5 complet par chunk, meme pour un id neuf"
    )


def test_existait_est_mesure_sur_la_pk_avant_l_insert():
    _, src = _corps_step_ingest()
    m_sel = re.search(r"_ancien\s*=\s*conn\.execute\(\s*\n?\s*\"SELECT text FROM rag_chunks WHERE id=\?", src)
    assert m_sel, "_ancien n'est pas lu par SELECT text FROM rag_chunks WHERE id=? (clef primaire)"
    assert re.search(r"_existait\s*=\s*_ancien is not None", src), \
        "_existait n'est plus derive de la lecture PK de l'ancien texte"
    m_ins = re.search(r"INSERT OR REPLACE INTO rag_chunks\(id,", src)
    assert m_ins, "INSERT OR REPLACE INTO rag_chunks introuvable"
    assert m_sel.start() < m_ins.start(), (
        "_existait est calcule APRES l'INSERT OR REPLACE : l'id existe alors toujours, "
        "le test ne decide plus rien"
    )


def test_insert_fts_reste_inconditionnel():
    fn, _ = _corps_step_ingest()
    inserts = _appels_sql(fn, r"INSERT\s+INTO\s+rag_fts")
    assert inserts, "l'INSERT rag_fts a disparu : le lexical ne serait plus alimente"
    parents = _parents(fn)
    assert not any(_sous_un_if_existait(i, parents) for i in inserts), (
        "l'INSERT rag_fts est conditionne par _existait : un chunk neuf ne serait plus "
        "trouvable en lexical"
    )
