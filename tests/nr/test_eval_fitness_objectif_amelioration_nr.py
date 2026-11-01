"""NR : pat_eval_fitness propose sur score SOUS CIBLE (dedup N jours), refuse sur score perime."""
import json
import time

import pytest
import nokido_agent.app.forge_benchmark_adapter as ad
from app import forge_autonomous_loops as fal


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(fal, "EVAL_SANDBOX", tmp_path)
    monkeypatch.setattr(fal, "CIBLES_EVAL", {"humaneval": 50.0, "bfcl": None})
    monkeypatch.setattr(ad, "latest_scores", lambda *a, **k: {"humaneval": 7.3, "bfcl": 94.0})
    # 26/10 : la proposition exige une MESURE valide (fraiche, pas dominee par les pannes) ; ces cas portent sur la
    # cible et la peremption de l'etat, la validite du fichier a son propre NR (test_eval_fitness_mesure_valide_nr).
    monkeypatch.setattr(ad, "validite_mesure", lambda banc, **k: {"valide": True, "raison": "doublure"})
    return tmp_path


def _etat(d, ts_mesure, scores=None):
    (d / "eval_fitness_state.json").write_text(json.dumps(
        {"scores": scores or {"humaneval": 7.3, "bfcl": 94.0}, "ts": time.time(), "ts_mesure": ts_mesure}))


def _cibles(d):
    return list(d.glob("evolution_proposal_cible_humaneval_*.md"))


def test_sous_cible_une_proposition(env):
    _etat(env, time.time())
    r = fal.pat_eval_fitness()
    p = _cibles(env)
    assert len(p) == 1 and not list(env.glob("evolution_proposal_cible_bfcl_*"))
    t = p[0].read_text(encoding="utf-8")
    assert "7.3" in t and "50.0" in t
    assert r["bancs_a_relancer"] == []


def test_deja_proposee_zero(env):
    _etat(env, time.time())
    fal.pat_eval_fitness()
    fal.pat_eval_fitness()
    assert len(_cibles(env)) == 1


def test_score_perime_zero_et_relance(env):
    _etat(env, time.time() - fal._EVAL_PEREMPTION_S - 10)
    r = fal.pat_eval_fitness()
    assert _cibles(env) == []
    assert "humaneval" in r["bancs_a_relancer"]
    assert "PERIME" in json.dumps(r)


def test_regression_inchangee(env):
    _etat(env, time.time(), {"humaneval": 60.0, "bfcl": 94.0})
    r = fal.pat_eval_fitness()
    assert r["regressions"]
    assert list(env.glob("evolution_proposal_eval_*.md"))
