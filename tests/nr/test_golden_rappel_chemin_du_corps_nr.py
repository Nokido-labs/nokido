"""NR -- rappel@k du golden mesure sur le chemin REEL du corps (forge_self_correction.preflight_check_verbose).

Ce chemin (10 appelants : veille, dsl, grounder, nokido_hub...) rend des SOURCES, pas des ids de chunks : le rappel par
id n'y est PAS mesurable -> None et dit, jamais 0 ; le rappel par source compare la source des ids attendus (lue par
CLE PRIMAIRE dans rag_chunks, jamais un LIKE : 45 Go) a celles rendues. Un tier « illisible » (tous les niveaux en
panne) est une recherche INCONNUE ; « none » est une recherche faite qui n'a rien trouve (ratee).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_golden_rappel as GR  # noqa: E402

QS = [{"id": "q1", "question": "a ?", "sources_attendues": ["c1"]},
      {"id": "q2", "question": "b ?", "sources_attendues": ["c2"]}]
VALIDES = {"q1": {"verdict": "VALIDE"}, "q2": {"verdict": "VALIDE"}}


def test_resultats_sans_id_rappel_id_non_mesurable_et_source_par_correspondance():
    sources = {"c1": "docs/A.md", "c2": "memory:B"}
    rendus = {"a ?": [{"source": "docs/A.md"}], "b ?": [{"source": "docs/Z.md"}]}
    r = GR.mesurer_rappel(QS, VALIDES, lambda q: rendus[q], k=10, source_attendue=sources.get)
    assert r["rappel_id"] is None and r["rappel_id_mesurable"] is False
    assert r["rappel_source"] == 0.5


def test_chercher_corps_rend_les_sources_borne_et_illisible_leve():
    def faux_preflight(question, context="", limit=5):
        if question == "panne":
            return {"tier": "illisible", "results": [], "pannes": ["fts5: x", "like: y"]}
        return {"tier": "fts5", "results": [{"source": "s%d" % i, "score": 1.0} for i in range(limit + 3)]}

    chercher = GR.chercher_corps(faux_preflight, k=4)
    assert chercher("ok") == [{"source": "s0"}, {"source": "s1"}, {"source": "s2"}, {"source": "s3"}]
    with pytest.raises(RuntimeError):
        chercher("panne")


def test_sources_des_ids_par_cle_primaire(tmp_path):
    db = tmp_path / "rag.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, text TEXT)")
    con.executemany("INSERT INTO rag_chunks VALUES (?, ?, ?)", [("c1", "docs/A.md", "t"), ("c2", "memory:B", "t")])
    con.commit()
    con.close()
    assert GR.sources_des_ids(["c1", "c2", "absent"], db) == {"c1": "docs/A.md", "c2": "memory:B"}
