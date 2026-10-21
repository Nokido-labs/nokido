# -*- coding: utf-8 -*-
"""NR (audit pair 19/10, affirmation 5 verifiee par AGY 1f2afef04) : une baseline absente ou illisible n'est pas
« aucune regression ».

Mesure : pat_eval_fitness laissait prev = {} quand eval_fitness_state.json manquait ou etait illisible ;
detect_regression({}, cur) rendait [] (« aucune regression ») et la fonction ECRASAIT la baseline avec les scores
courants -- une regression survenue pendant l'illisibilite devenait la reference. Desormais : regressions = None
(INCONNU) faute de comparaison ; une baseline illisible est GELEE (renommee), jamais ecrasee ; un benchmark disparu
est NOMME ; une baseline de plus de 14 jours est dite perimee.
"""
import json
import time

from nokido_agent.app import forge_autonomous_loops as L
from nokido_agent.app import forge_benchmark_adapter as B


def _prep(tmp_path, monkeypatch, cur):
    monkeypatch.setattr(L, "EVAL_SANDBOX", tmp_path)
    monkeypatch.setattr(B, "latest_scores", lambda: dict(cur))
    monkeypatch.setattr(L, "record_evolution_experience", lambda *a, **k: "exp", raising=False)
    return tmp_path / "eval_fitness_state.json"


def test_baseline_absente_n_est_pas_aucune_regression(tmp_path, monkeypatch):
    sf = _prep(tmp_path, monkeypatch, {"swe": 40.0})
    r = L.pat_eval_fitness()
    assert r["regressions"] is None and r["baseline"] == "ABSENTE"
    assert json.loads(sf.read_text(encoding="utf-8"))["scores"] == {"swe": 40.0}   # 1re baseline posee


def test_baseline_illisible_est_gelee_jamais_ecrasee(tmp_path, monkeypatch):
    sf = _prep(tmp_path, monkeypatch, {"swe": 10.0})
    sf.write_text("{corrompu", encoding="utf-8")
    r = L.pat_eval_fitness()
    assert r["regressions"] is None and r["baseline"] == "ILLISIBLE"
    geles = list(tmp_path.glob("eval_fitness_state.illisible-*.json"))
    assert len(geles) == 1 and geles[0].read_text(encoding="utf-8") == "{corrompu"


def test_baseline_lue_compare_et_nomme_les_disparus(tmp_path, monkeypatch):
    sf = _prep(tmp_path, monkeypatch, {"swe": 30.0})
    sf.write_text(json.dumps({"scores": {"swe": 40.0, "tb": 50.0}, "ts": time.time()}), encoding="utf-8")
    r = L.pat_eval_fitness()
    assert r["baseline"] == "LUE" and r["regressions"] and "swe" in r["regressions"][0]
    assert r["disparus"] == ["tb"] and r["baseline_perimee"] is False


def test_baseline_perimee_est_dite(tmp_path, monkeypatch):
    sf = _prep(tmp_path, monkeypatch, {"swe": 40.0})
    sf.write_text(json.dumps({"scores": {"swe": 40.0}, "ts": time.time() - 20 * 86400}), encoding="utf-8")
    assert L.pat_eval_fitness()["baseline_perimee"] is True
