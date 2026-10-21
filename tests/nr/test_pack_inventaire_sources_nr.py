"""NR -- inventaire PAR FAMILLE DE SOURCE avant de decouper le Knowledge Pack par licence (decision owner 2026-10-20).

Le pack public sera decoupe par source = par licence. Le domaine `reference` (927 761 chunks) ne contient pas que des
RFC et des docsets : une sonde du 20/10 y a vu `session:` (ancres de session internes), `https:` (articles de blogs
tiers), `docset:Docker`, `rfc:`, `watch:sqlite`. Livrer « le domaine reference » aurait ete une faute de licence ET de
confidentialite. On mesure donc d'abord, famille par famille, combien de chunks, d'octets de texte, de vecteurs --
sans COUNT sur rag_chunks et sans lire les vecteurs (la base fait 46 Go et l'owner a refuse l'usure disque).

Ce qui est garde :
  * `famille_source` rend une cle stable par famille (rfc, docset:<nom>, watch:<projet>, https:<hote>, session) ;
  * `inventaire` compte par domaine et famille (chunks, octets_texte, avec_vecteur, 3 exemples au plus), ignore les
    chunks inactifs, et passe par l'index `domain` sans toucher a l'index `active` ni lire la colonne embedding.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("pack_inventaire_nr", RACINE / "tools" / "forge_knowledge_pack_export.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("source, famille", [
    ("rfc:rfc1349", "rfc"),
    ("docset:Docker#Install interactively - MSI installer", "docset:Docker"),
    ("docset:Django", "docset:Django"),
    ("watch:sqlite:wal.html", "watch:sqlite"),
    ("https://www.eesel.ai/fr/blog/agentic-coding-cli", "https:www.eesel.ai"),
    ("http://example.org/a", "http:example.org"),
    ("session:2026-06-12:solution", "session"),
    ("app/forge_rag_engine.py", "app"),
    ("", "?"),
])
def test_famille_source(source, famille):
    assert _module().famille_source(source) == famille


def test_inventaire_par_famille_sans_lire_les_vecteurs(tmp_path):
    m = _module()
    base = tmp_path / "rag.db"
    con = sqlite3.connect(base)
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, domain TEXT, text TEXT, "
                "embedding BLOB, active INTEGER)")
    con.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?,?,?)", [
        ("a", "rfc:rfc1", "reference", "abcd", b"\x00" * 8, 1),
        ("b", "rfc:rfc2", "reference", "ef", None, 1),
        ("c", "docset:Flask#x", "reference", "ghi", b"\x00" * 8, 1),
        ("d", "rfc:rfc3", "reference", "inactif", b"\x00" * 8, 0),
        ("e", "app/x.py", "code", "zz", b"\x00" * 8, 1),
    ])
    con.commit()
    con.close()
    vu = []
    reel = m.sqlite3.connect

    def espion(*a, **kw):
        c = reel(*a, **kw)
        c.set_trace_callback(vu.append)
        return c
    m.sqlite3.connect = espion
    try:
        inv = m.inventaire(base, ["reference"])
    finally:
        m.sqlite3.connect = reel
    assert set(inv) == {"reference"}
    assert inv["reference"]["rfc"] == {"chunks": 2, "octets_texte": 6, "avec_vecteur": 1,
                                       "exemples": ["rfc:rfc1", "rfc:rfc2"]}
    assert inv["reference"]["docset:Flask"]["chunks"] == 1
    sql = " ".join(vu)
    assert "domain=" in sql.replace(" ", "") and "+active" in sql, sql
    assert "embedding IS NOT NULL" in sql and "embedding," not in sql.replace(" ,", ","), "la colonne vecteur n'est jamais lue"
    assert "COUNT(" not in sql.upper()
