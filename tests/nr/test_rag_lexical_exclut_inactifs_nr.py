"""NR — le chemin lexical du `rag` n'exhume pas les chunks RETIRES (active=0).

Ecrit ROUGE avant correctif (decision de la fiche de veille « hybride », 2026-09-23).

LE DEFAUT. Le raffinage du 2026-09-23 a passe 655 216 chunks a `active=0` : ils sont
RETIRES, pas supprimes (consigne owner : rien n'est supprime en base, on marque).
Or `forge_mcp_registry._rag_bm25_search` — le repli lexical qui sert la majorite
des recherches reelles quand les embedders sont eteints — joignait `rag_fts` et
`rag_chunks` sur le seul `MATCH`, sans regarder `active`. Marquer un chunk comme
retire n'avait donc AUCUN effet sur ce que le corps relisait : le retrait etait
declare, pas applique.

POURQUOI UN TEST DE COMPORTEMENT, PAS D'AST. La lecon du 2026-09-10 : une mention
dans un commentaire ne prouve rien. On extrait la fonction REELLE du fichier et on
l'execute sur une base temporaire ; c'est son resultat qu'on juge, pas son texte.

LA SYMETRIE. `active` NULL n'est pas `active=0` : un chunk ancien sans valeur ne doit
pas disparaitre en silence (UNKNOWN != NO). Seul un retrait EXPLICITE l'exclut.
"""

from __future__ import annotations

import ast
import os
import sqlite3
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CIBLE = ROOT / "app" / "forge_mcp_registry.py"
MOT = "zorglubtemoin"


def _fonction_reelle():
    """Extrait `_rag_bm25_search` du fichier REEL et la compile hors de la classe."""
    if not CIBLE.exists():
        pytest.skip(f"{CIBLE} illisible depuis ce compte — INDETERMINE, pas absent")
    src = CIBLE.read_text(encoding="utf-8", errors="replace")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.FunctionDef) and n.name == "_rag_bm25_search":
            code = textwrap.dedent(ast.get_source_segment(src, n))
            ns: dict = {"os": os}
            exec(compile(code, str(CIBLE), "exec"), ns)  # noqa: S102 - fonction du depot, pas une entree
            return ns["_rag_bm25_search"]
    pytest.fail("_rag_bm25_search introuvable — la cible a bouge, le NR doit etre reancre")
    raise AssertionError  # pragma: no cover


class _Registre:
    """Le strict necessaire de `self` : le chemin de la base et un journal muet."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.requetes = []

    def _log_query(self, topic, meta, ids, ms):
        self.requetes.append((topic, ids))


def _base(tmp_path) -> Path:
    db = tmp_path / "rag.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, domain TEXT, text TEXT,"
        " embedding BLOB, active INTEGER, access_count INTEGER);"
        "CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text);"
    )
    lignes = [("c_actif", "src/actif", 1), ("c_retire", "src/retire", 0), ("c_ancien", "src/ancien", None)]
    for cid, source, actif in lignes:
        texte = f"{MOT} contenu de {source}"
        con.execute("INSERT INTO rag_chunks VALUES (?,?,?,?,NULL,?,0)", (cid, source, "test", texte, actif))
        con.execute("INSERT INTO rag_fts(chunk_id, text) VALUES (?,?)", (cid, texte))
    con.commit()
    con.close()
    return db


def test_le_temoin_est_bien_indexe(tmp_path):
    """Contre-epreuve : sans elle, un resultat vide passerait pour un filtre qui marche."""
    con = sqlite3.connect(_base(tmp_path))
    n = con.execute("SELECT count(*) FROM rag_fts WHERE rag_fts MATCH ?", (f'"{MOT}"',)).fetchone()[0]
    con.close()
    assert n == 3


def test_un_chunk_retire_ne_remonte_pas(tmp_path):
    rendu = _fonction_reelle()(_Registre(_base(tmp_path)), MOT, 10)
    assert "[src/retire]" not in rendu, (
        "un chunk active=0 remonte en recherche lexicale : le retrait est declare, pas applique"
    )


def test_un_chunk_actif_remonte(tmp_path):
    rendu = _fonction_reelle()(_Registre(_base(tmp_path)), MOT, 10)
    assert "[src/actif]" in rendu, "le filtre a jete aussi les chunks actifs"


def test_active_null_n_est_pas_un_retrait(tmp_path):
    """UNKNOWN != NO : un chunk sans valeur d'`active` n'a jamais ete retire."""
    rendu = _fonction_reelle()(_Registre(_base(tmp_path)), MOT, 10)
    assert "[src/ancien]" in rendu, "un chunk active=NULL a disparu en silence"


def test_le_journal_ne_compte_pas_les_retires(tmp_path):
    """La soif epistemique lit `query_log` : elle ne doit pas se nourrir de retires."""
    reg = _Registre(_base(tmp_path))
    _fonction_reelle()(reg, MOT, 10)
    ids = [i for _, lot in reg.requetes for i in lot]
    assert "c_retire" not in ids
