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


def test_doublure_moteur_bras_lisent_env_differents_et_restaurent():
    import os

    valeurs_env_vues = []

    class DoublureMoteur:
        def search(self, query, k=10):
            valeurs_env_vues.append((query, os.environ.get("LAFORGE_RAG_PLACES_MEMOIRE")))
            return [{"id": "c1", "source": "c1"}]

    anc = os.environ.get("LAFORGE_RAG_PLACES_MEMOIRE")
    os.environ["LAFORGE_RAG_PLACES_MEMOIRE"] = "valeur_initiale_temoin"
    try:
        qs = [{"id": "q1", "question": "test q1 ?", "sources_attendues": ["c1"]}]
        moteur = DoublureMoteur()
        res = GR.comparer_canal_memoire(qs, engine=moteur, verifier_gardes=False)
        assert res["ok"] is True
        # Deux passes : d'abord bras off ("0"), puis bras on ("40")
        assert len(valeurs_env_vues) == 2
        assert valeurs_env_vues[0] == ("test q1 ?", "0")
        assert valeurs_env_vues[1] == ("test q1 ?", "40")
        # Restauration apres execution normale
        assert os.environ.get("LAFORGE_RAG_PLACES_MEMOIRE") == "valeur_initiale_temoin"
    finally:
        if anc is not None:
            os.environ["LAFORGE_RAG_PLACES_MEMOIRE"] = anc
        else:
            os.environ.pop("LAFORGE_RAG_PLACES_MEMOIRE", None)


def test_doublure_moteur_restauration_env_sur_exception():
    import os
    import pytest

    class MoteurCrashSurArmOn:
        def search(self, query, k=10):
            if os.environ.get("LAFORGE_RAG_PLACES_MEMOIRE") == "40":
                raise KeyboardInterrupt("Crash simule sur bras on")
            return [{"id": "c1", "source": "c1"}]

    anc = os.environ.get("LAFORGE_RAG_PLACES_MEMOIRE")
    os.environ["LAFORGE_RAG_PLACES_MEMOIRE"] = "temoin_exception"
    try:
        qs = [{"id": "q1", "question": "test q1 ?", "sources_attendues": ["c1"]}]
        with pytest.raises(KeyboardInterrupt, match="Crash simule"):
            GR.comparer_canal_memoire(qs, engine=MoteurCrashSurArmOn(), verifier_gardes=False)
        # Restauration garantie y compris sur exception non interceptee
        assert os.environ.get("LAFORGE_RAG_PLACES_MEMOIRE") == "temoin_exception"
    finally:
        if anc is not None:
            os.environ["LAFORGE_RAG_PLACES_MEMOIRE"] = anc
        else:
            os.environ.pop("LAFORGE_RAG_PLACES_MEMOIRE", None)


def test_question_perdue_nommee_dans_bilan():
    import os

    class MoteurBascule:
        def search(self, query, k=10):
            places = os.environ.get("LAFORGE_RAG_PLACES_MEMOIRE")
            if places == "0":
                if query == "q_gagne ?":
                    return [{"id": "autre", "source": "autre"}]
                return [{"id": "cible", "source": "source_attendue"}]
            if query == "q_perd ?":
                return [{"id": "mem", "source": "memory:parasite"}]
            return [{"id": "cible", "source": "source_attendue"}]

    qs = [
        {"id": "q_stable", "question": "q_stable ?", "sources_attendues": ["source_attendue"]},
        {"id": "q_gagne", "question": "q_gagne ?", "sources_attendues": ["source_attendue"]},
        {"id": "q_perdu", "question": "q_perd ?", "sources_attendues": ["source_attendue"]},
    ]
    res = GR.comparer_canal_memoire(qs, engine=MoteurBascule(), verifier_gardes=False)
    assert res["questions_gagnees"] == ["q_gagne"]
    assert res["questions_perdues"] == ["q_perdu"]
    assert res["bras_on"]["gagnees"] == ["q_gagne"]
    assert res["bras_on"]["perdues"] == ["q_perdu"]


def test_dense_muet_refus_no_verdict_sans_chiffre(monkeypatch):
    monkeypatch.setattr(GR, "_dense_vivant", lambda: (False, "canal dense simule indisponible"))
    monkeypatch.setattr(GR, "_ram_libre_go", lambda: 16.0)

    res = GR.comparer_canal_memoire(QUESTIONS, verifier_gardes=True)
    assert res["ok"] is False
    assert res["verdict"] == "NO_VERDICT"
    assert "canal dense muet" in res["refus"]
    # Pas de chiffre
    assert "rappel_source" not in res
    assert "mrr" not in res
    assert "bras_off" not in res


def test_recherche_qui_leve_est_inconnue_jamais_ratee():
    class MoteurAvecException:
        def search(self, query, k=10):
            if "leve" in query:
                raise RuntimeError("Erreur FTS/Qdrant sur requete")
            return [{"id": "c1", "source": "s1"}]

    qs = [
        {"id": "q_ok", "question": "normale ?", "sources_attendues": ["s1"]},
        {"id": "q_err", "question": "recherche qui leve ?", "sources_attendues": ["s1"]},
    ]
    res = GR.comparer_canal_memoire(qs, engine=MoteurAvecException(), verifier_gardes=False)
    for bras_nom in ("bras_off", "bras_on"):
        bras = res[bras_nom]
        assert bras["mesurees"] == 1
        assert bras["inconnues"] == 1
        assert bras["inconnues_ids"] == ["q_err"]
        assert "q_err" not in bras["ratees"]
        assert "q_err" not in res["questions_perdues"]
