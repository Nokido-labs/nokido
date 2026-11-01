"""NR : un score de banc n'est une MESURE que s'il est frais et pas domine par des pannes (owner 26/10).

Mesure 26/10 : HumanEval « 7,3 % » = 152 llm_error (pannes Groq) sur 164, les 12 cas executes ont TOUS reussi ;
BFCL date du 31/05, cognitif du 14/08. eval_fitness ecrivait pourtant « humaneval sous cible » : le self-patcher
courait apres une non-mesure. Une mesure invalide -> aucune proposition, banc a relancer, raison DITE.
"""
import json
import os
import time

import pytest
import nokido_agent.app.forge_benchmark_adapter as ad
from app import forge_autonomous_loops as fal


def _fichier(base, rel, doc, age_j=0.0):
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")
    t = time.time() - age_j * 86400
    os.utime(p, (t, t))
    return p


@pytest.fixture
def rag(tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "RAG", tmp_path)
    return tmp_path


def test_domine_par_les_pannes_n_est_pas_une_mesure(rag):
    res = [{"pass": False, "reason": "llm_error"}] * 152 + [{"pass": True, "reason": "ok"}] * 12
    _fichier(rag, "humaneval/humaneval_groq_164_x.json",
             {"n_total": 164, "passed": 12, "pass_rate": 7.3, "fail_reasons": {"llm_error": 152}, "results": res})
    v = ad.validite_mesure("humaneval")
    assert v["valide"] is False and "NON_MESURE" in v["raison"] and "152" in v["raison"]


def test_perime_n_est_pas_une_mesure(rag):
    _fichier(rag, "bfcl/bfcl_router_parallel_50_r2.json",
             {"n_total": 50, "passed": 47, "pass_rate": 94.0, "fail_reasons": {"missing_call": 3}}, age_j=148)
    v = ad.validite_mesure("bfcl")
    assert v["valide"] is False and "PERIME" in v["raison"]


def test_frais_et_sain_est_une_mesure(rag):
    _fichier(rag, "cognitive/cognitive_20261026.json", {"pass_rate": 74.07, "trajectoires": 40})
    assert ad.validite_mesure("cognitif")["valide"] is True


def test_absent_est_inconnu(rag):
    v = ad.validite_mesure("humaneval")
    assert v["valide"] is False and "ABSENT" in v["raison"]


def test_pas_de_regression_sur_une_non_mesure(tmp_path, monkeypatch):
    """26/10 13:18 : bfcl 94 -> 0 (0/50 en erreurs LiteLLM) a ouvert une fausse regression. Seul un banc dont la
    mesure COURANTE est valide entre dans la comparaison ; les autres sont dits, pas compares."""
    monkeypatch.setattr(fal, "EVAL_SANDBOX", tmp_path)
    monkeypatch.setattr(fal, "CIBLES_EVAL", {})
    monkeypatch.setattr(ad, "latest_scores", lambda *a, **k: {"bfcl": 0.0, "cognitif": 54.0})
    monkeypatch.setattr(ad, "validite_mesure", lambda banc, **k: (
        {"valide": False, "raison": "NON_MESURE : 50/50 pannes"} if banc == "bfcl" else {"valide": True, "raison": "ok"}))
    (tmp_path / "eval_fitness_state.json").write_text(json.dumps(
        {"scores": {"bfcl": 94.0, "cognitif": 74.07}, "ts": time.time(), "ts_mesure": time.time()}))
    r = fal.pat_eval_fitness()
    regr = " ".join(r["regressions"] or [])
    assert "bfcl" not in regr and "cognitif" in regr
    assert "NON_MESURE" in json.dumps(r, ensure_ascii=False)


def test_eval_fitness_ne_propose_pas_sur_une_non_mesure(tmp_path, monkeypatch):
    monkeypatch.setattr(fal, "EVAL_SANDBOX", tmp_path)
    monkeypatch.setattr(fal, "CIBLES_EVAL", {"humaneval": 15.0})
    monkeypatch.setattr(ad, "latest_scores", lambda *a, **k: {"humaneval": 7.3})
    monkeypatch.setattr(ad, "validite_mesure",
                        lambda banc, **k: {"valide": False, "raison": "NON_MESURE : 152/164 pannes de fournisseur"})
    (tmp_path / "eval_fitness_state.json").write_text(json.dumps(
        {"scores": {"humaneval": 7.3}, "ts": time.time(), "ts_mesure": time.time()}))
    r = fal.pat_eval_fitness()
    assert list(tmp_path.glob("evolution_proposal_cible_*.md")) == []
    assert "humaneval" in r["bancs_a_relancer"] and "NON_MESURE" in json.dumps(r, ensure_ascii=False)
