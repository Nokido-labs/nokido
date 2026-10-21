"""NR -- instrument rappel@10 du jeu de reference RAG (couche 3, roadmap_p1_methode_dev_par_couches_20261016).

Jeu docs/rapports/golden_dataset_retrieval_20261019.json (54 questions : sources_attendues = ids de chunks) et verdicts
sandbox/golden_relecture_owner.json (54/54 VALIDE au 19/10, b228d986f). Aucun instrument de RAPPEL n'existait :
tools/bench_rag.py mesure la latence, tools/forge_bench_beir.py est BEIR. Contrat de tools/forge_golden_rappel.py :
  * mesurer_rappel(questions, verdicts, chercher, k=10) -> dict ; seules les questions VALIDE sont mesurees ;
  * rappel par ID de chunk (une source attendue dans les k premiers ids) ET par SOURCE (prefixe avant « # » ou « : ») ;
  * une recherche qui LEVE = INCONNU, comptee a part, jamais un echec ni un succes (UNKNOWN != NO) ;
  * aucune question mesurable -> taux None, jamais 0.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_golden_rappel as GR  # noqa: E402

QUESTIONS = [
    {"id": "q1", "question": "a ?", "sources_attendues": ["c1"]},
    {"id": "q2", "question": "b ?", "sources_attendues": ["c2", "c3"]},
    {"id": "q3", "question": "c ?", "sources_attendues": ["c4"]},
    {"id": "q4", "question": "d ?", "sources_attendues": ["c5"]},
    {"id": "q5", "question": "e ?", "sources_attendues": ["c6"]},
]
VERDICTS = {"q1": {"verdict": "VALIDE"}, "q2": {"verdict": "VALIDE"}, "q3": {"verdict": "VALIDE"},
            "q4": {"verdict": "VALIDE"}, "q5": {"verdict": "A_REVOIR"}}


def _chercher(question):
    return {
        "a ?": [{"id": "x"}, {"id": "c1"}],             # trouvee
        "b ?": [{"id": "c3"}],                            # trouvee (2e source attendue)
        "c ?": [{"id": "z%d" % i} for i in range(12)],    # ratee
    }.get(question) or (_ for _ in ()).throw(RuntimeError("RAG indisponible"))


def test_rappel_par_id_sur_les_seules_valides_et_inconnu_a_part():
    r = GR.mesurer_rappel(QUESTIONS, VERDICTS, _chercher, k=10)
    assert r["k"] == 10
    assert r["mesurees"] == 3 and r["inconnues"] == 1 and r["ecartees_non_valides"] == 1
    assert abs(r["rappel_id"] - 2 / 3) < 1e-9
    assert sorted(r["ratees"]) == ["q3"] and sorted(r["inconnues_ids"]) == ["q4"]


def test_rappel_par_source_compte_le_document_pas_le_fragment():
    qs = [{"id": "s1", "question": "s ?", "sources_attendues": ["README.md#chunk3"]}]
    r = GR.mesurer_rappel(qs, {"s1": {"verdict": "VALIDE"}}, lambda q: [{"id": "README.md#chunk7"}], k=10)
    assert r["rappel_id"] == 0.0 and r["rappel_source"] == 1.0


def test_le_top_k_est_borne():
    qs = [{"id": "t1", "question": "t ?", "sources_attendues": ["cible"]}]
    rang_11 = [{"id": "z%d" % i} for i in range(10)] + [{"id": "cible"}]
    r = GR.mesurer_rappel(qs, {"t1": {"verdict": "VALIDE"}}, lambda q: rang_11, k=10)
    assert r["rappel_id"] == 0.0


def test_rien_de_mesurable_rend_none_jamais_zero():
    r = GR.mesurer_rappel(QUESTIONS[:1], {"q1": {"verdict": "A_REVOIR"}}, _chercher, k=10)
    assert r["mesurees"] == 0 and r["rappel_id"] is None and r["rappel_source"] is None
