"""NR -- les chunks d'un fichier de Nokido DISPARU se desactivent par la primitive existante, jamais supprimes (20/10).

Mesure du 20/10 (par plage sur idx_rag_source, sans LIKE) : 204 fichiers .py de Nokido indexes n'existent plus
(app/LaForge.py renomme, app/backups/*, anciens agents, tools/ctf...) ; leurs 1 886 chunks etaient ACTIFS et nourrissaient
le contexte d'une architecture morte. Decision owner (AskUserQuestion) : les desactiver par
`forge_rag_truth.retirer_versions_anterieures` (active=0, superseded_by, retrait de rag_chunks_fts) -- rien n'est supprime.

Contrat (app/forge_rag_truth.py) :
  * `sources_fantomes(conn, racine, prefixes)` -> {chemin_disparu: [sources exactes]}, par PLAGE sur la colonne source
    (jamais de LIKE), un chemin = la source sans son suffixe `#...` ou `::...` ;
  * `retirer_sources_fantomes(conn, fantomes, appliquer=False)` -> nombre de chunks retires (a blanc : compte, n'ecrit
    rien) ; un fichier qui existe n'est jamais touche ;
CLI `tools/rag_sources_fantomes.py --base B --racine R [--appliquer]` : a blanc par defaut.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _charger(rel, nom):
    spec = importlib.util.spec_from_file_location(nom, RACINE / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[nom] = m        # forge_rag_truth porte des dataclasses : elles exigent leur module inscrit
    spec.loader.exec_module(m)
    return m


def _monde(tmp_path):
    racine = tmp_path / "depot"
    (racine / "app").mkdir(parents=True)
    (racine / "app" / "existe.py").write_text("x = 1\n", encoding="utf-8")
    db = tmp_path / "rag.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT, "
                "active INTEGER DEFAULT 1, superseded_by TEXT)")
    con.execute("CREATE INDEX idx_rag_source ON rag_chunks(source)")
    con.execute("CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, source, domain, content='rag_chunks', "
                "content_rowid='rowid')")
    con.execute("CREATE TRIGGER rag_chunks_fts_ai AFTER INSERT ON rag_chunks BEGIN INSERT INTO rag_chunks_fts(rowid, "
                "text, source, domain) VALUES (new.rowid, new.text, new.source, new.domain); END")
    for cid, src in [("e1", "app/existe.py#f"), ("d1", "app/disparu.py#g"), ("d2", "app/disparu.py"),
                     ("x1", "docset:Flask#Intro"), ("t1", "tools/parti.py::h")]:
        con.execute("INSERT INTO rag_chunks (id, text, source, domain) VALUES (?, ?, ?, 'code')",
                    (cid, "texte du chunk %s sur la respiration" % cid, src))
    con.commit()
    con.close()
    return racine, db


def _actifs(db):
    con = sqlite3.connect(db)
    try:
        return {r[0] for r in con.execute("SELECT id FROM rag_chunks WHERE active = 1")}
    finally:
        con.close()


def test_les_fantomes_sont_trouves_par_plage(tmp_path):
    rt = _charger("app/forge_rag_truth.py", "rag_truth_fantomes_nr")
    racine, db = _monde(tmp_path)
    con = sqlite3.connect(db)
    f = rt.sources_fantomes(con, racine, ("app/", "tools/"))
    con.close()
    assert f == {"app/disparu.py": sorted(["app/disparu.py", "app/disparu.py#g"]), "tools/parti.py": ["tools/parti.py::h"]}, f


def test_a_blanc_rien_n_est_ecrit(tmp_path):
    rt = _charger("app/forge_rag_truth.py", "rag_truth_fantomes_blanc_nr")
    racine, db = _monde(tmp_path)
    con = sqlite3.connect(db)
    n = rt.retirer_sources_fantomes(con, rt.sources_fantomes(con, racine, ("app/", "tools/")))
    con.close()
    assert n == 3 and _actifs(db) == {"e1", "d1", "d2", "x1", "t1"}


def test_applique_desactive_les_seuls_fantomes(tmp_path):
    rt = _charger("app/forge_rag_truth.py", "rag_truth_fantomes_applique_nr")
    racine, db = _monde(tmp_path)
    con = sqlite3.connect(db)
    n = rt.retirer_sources_fantomes(con, rt.sources_fantomes(con, racine, ("app/", "tools/")), appliquer=True)
    con.commit()
    con.close()
    assert n == 3 and _actifs(db) == {"e1", "x1"}, _actifs(db)
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM rag_chunks").fetchone()[0] == 5, "rien n'est supprime"
    con.close()


def test_le_point_d_entree_est_a_blanc_par_defaut(tmp_path, monkeypatch):
    cli = _charger("tools/rag_sources_fantomes.py", "rag_sources_fantomes_cli_nr")
    racine, db = _monde(tmp_path)
    monkeypatch.setattr(sys, "argv", ["rag_sources_fantomes.py", "--base", str(db), "--racine", str(racine)])
    assert cli.main() == 0 and _actifs(db) == {"e1", "d1", "d2", "x1", "t1"}
    monkeypatch.setattr(sys, "argv", ["rag_sources_fantomes.py", "--base", str(db), "--racine", str(racine),
                                      "--appliquer"])
    assert cli.main() == 0 and _actifs(db) == {"e1", "x1"}
