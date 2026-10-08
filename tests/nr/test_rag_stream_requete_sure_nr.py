"""NR -- /api/rag/stream ne passe jamais la question brute a FTS5 (2026-10-07).

Mesure au test d'installation sur runners GitHub : « How do I install Nokido with pip? » rendait
« fts5: syntax error near "?" » -- toute question avec `?`, `"`, `-` faisait planter la recherche lexicale du hub.
La route reutilise forge_knowledge_overlap.requete_fts (mots cites, relies par OR). Ce NR garde : la source de la
route MATCH la requete echappee (jamais `q`), et de vraies questions s'executent sur un FTS5 sans erreur.
"""
from __future__ import annotations

import importlib.util
import re
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(30)

RACINE = Path(__file__).resolve().parents[2]


def _requete_fts():
    spec = importlib.util.spec_from_file_location("overlap_nr", RACINE / "tools" / "forge_knowledge_overlap.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.requete_fts


def test_la_route_match_la_requete_echappee_jamais_la_question_brute():
    src = (RACINE / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    corps = src[src.index("async def rag_stream("):]
    corps = corps[:corps.index("return StreamingResponse(")]
    assert "requete_fts" in corps
    assert re.search(r"params = \(fts, domain, limit\) if domain else \(fts, limit\)", corps), (
        "la question brute `q` repartirait dans MATCH")
    assert not re.search(r"params = \(q,", corps)


@pytest.mark.parametrize("question", [
    "How do I install Nokido with pip?",
    'Que fait "governed_edit" -- et pourquoi ?',
    "secret-scan AND NOT vault OR NEAR(x)",
])
def test_une_vraie_question_s_execute_sans_erreur_fts5(question):
    requete = _requete_fts()(question)
    assert requete, question
    con = sqlite3.connect(":memory:")
    con.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED)")
    con.execute("INSERT INTO rag_fts VALUES ('c1', 'install Nokido with pip governed_edit vault', 'docs/x.md', 'd')")
    lignes = con.execute("SELECT chunk_id FROM rag_fts WHERE rag_fts MATCH ? ORDER BY bm25(rag_fts)", (requete,)).fetchall()
    assert lignes == [("c1",)], (question, requete)


def test_une_question_sans_mot_exploitable_ne_part_pas_a_fts5():
    assert _requete_fts()("?? -- !!") == ""
