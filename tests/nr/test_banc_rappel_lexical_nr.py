"""NR du juge `rappel_lexical` (tools/bancs/banc_rappel_lexical.py), sur un mini-index FABRIQUE (aucune donnee RAG) :
(1) rappel@k exact et questions hors index ecartees ; (2) une requete que FTS5 refuse compte RATEE, jamais INCONNUE
(sinon un candidat ecarterait les questions dures en levant) ; (3) un index modifie apres son manifeste est REFUSE.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "bancs"))
import banc_rappel_lexical as B  # noqa: E402

BASE = 'def requete_fts(question):\n    import re\n    return " OR ".join([w for w in re.split(r"\\W+", question or "") if len(w) > 3][:15])\n'
CASSEE = 'def requete_fts(question):\n    return "AND ("\n'


def _monde(tmp_path, source_requete):
    racine = tmp_path / "copie"
    (racine / "app").mkdir(parents=True)
    (racine / "app" / "forge_rag_engine.py").write_text(source_requete, encoding="utf-8")
    index = tmp_path / "mini.sqlite"
    con = sqlite3.connect(index)
    con.execute("CREATE VIRTUAL TABLE mini USING fts5(id UNINDEXED, source UNINDEXED, domain UNINDEXED, text)")
    con.executemany("INSERT INTO mini VALUES (?,?,?,?)", [
        ("a", "doc:a", "d", "port http du hub souverain 8766"),
        ("b", "doc:b", "d", "interpreteur python canonique miniforge"),
        ("c", "doc:c", "d", "bruit sans aucun rapport avec la question")])
    con.commit()
    con.close()
    index.with_suffix(".json").write_text(json.dumps({"sha256": hashlib.sha256(index.read_bytes()).hexdigest()}),
                                          encoding="utf-8")
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"questions": [
        {"id": "q1", "question": "Quel est le port du hub souverain ?", "sources_attendues": ["a"]},
        {"id": "q2", "question": "Quel interpreteur python canonique ?", "sources_attendues": ["b"]},
        {"id": "q3", "question": "Question sans fragment indexe", "sources_attendues": ["zz"]}]}), encoding="utf-8")
    return racine, index, golden


def test_rappel_exact_et_hors_index_ecarte(tmp_path):
    racine, index, golden = _monde(tmp_path, BASE)
    r = B.mesurer(racine, index, golden, k=1)
    assert r["metrique"] == 1.0
    # la source d'un id hache se lit dans l'index, jamais dans la forme de l'id (0,0 trompeur mesure le 29/10)
    assert r["rappel_source"] == 1.0
    assert r["mesurees"] == 2 and r["hors_index"] == 1 and r["erreurs_fts"] == 0


def test_requete_refusee_par_fts_compte_ratee(tmp_path):
    racine, index, golden = _monde(tmp_path, CASSEE)
    r = B.mesurer(racine, index, golden, k=1)
    assert r["metrique"] == 0.0
    assert r["mesurees"] == 2 and r["erreurs_fts"] == 2
    assert sorted(r["ratees"]) == ["q1", "q2"]


def test_index_modifie_refuse(tmp_path):
    racine, index, golden = _monde(tmp_path, BASE)
    con = sqlite3.connect(index)
    con.execute("INSERT INTO mini VALUES ('d', 'doc:d', 'd', 'ajout tardif')")
    con.commit()
    con.close()
    with pytest.raises(SystemExit):
        B.mesurer(racine, index, golden, k=1)
