"""tests/test_goap_intuition.py — heuristique d'intuition GOAP : blend, porte signal/bruit,
dégradation, et garde-fou correctness (System 1 élague → System 2 ré-élargit). 0 LLM/réseau."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from forge_goap_intuition import (  # noqa: E402
    _confidence, intuition_rank, keyword_affinity, make_default_providers,
)
from forge_goap_hub_bridge import Action, Goal, GOAPPlanner  # noqa: E402


def _act(name, hub_tool="run", args=None, cost=1, pre=None, eff=None):
    return Action(name, cost, pre or {}, eff or {}, hub_tool, args or {})


# ── porte signal/bruit (le cœur Damasio) ────────────────────────────────────
def test_confidence_sharp_is_high():
    assert _confidence([5.0, 1.0, 0.5]) > 0.7  # top détaché = intuition NETTE


def test_confidence_flat_is_low():
    assert _confidence([1.0, 0.99, 0.98]) < 0.05  # plat = rumination/bruit


def test_confidence_single_and_empty():
    assert _confidence([2.0]) == 1.0
    assert _confidence([0.0, 0.0]) == 0.0


# ── signal associatif lexical ────────────────────────────────────────────────
def test_keyword_affinity_relevant_higher():
    a_rel = _act("oracle", "oracle_python_repl", {"code": "test regex hypothesis"})
    a_irr = _act("ingest_url", "crawl", {"url": "http://x"})
    s = "je doute du comportement exact de ce regex, tester l'hypothesis"
    assert keyword_affinity(s, a_rel) > keyword_affinity(s, a_irr)


# ── blend + dégradation ──────────────────────────────────────────────────────
def test_rank_blends_and_orders():
    acts = [_act("A"), _act("B")]
    prov = {"vec": lambda s, a: 1.0 if a.name == "A" else 0.0,
            "value": lambda s, a: 2.0 if a.name == "B" else 0.0}
    scored, conf = intuition_rank("x", acts, providers=prov)
    # B = 1.2*2.0=2.4 ; A = 1.0*1.0=1.0 → B premier
    assert scored[0][0].name == "B" and conf > 0.4


def test_rank_ignores_broken_provider():
    acts = [_act("A"), _act("B")]
    def boom(s, a):
        raise RuntimeError("provider KO")
    scored, _ = intuition_rank("A relevant", acts, providers={"vec": keyword_affinity, "graph": boom})
    assert len(scored) == 2  # le provider KO est ignoré, pas de crash


def test_default_providers_always_has_vec():
    assert "vec" in make_default_providers()  # signal lexical = invariant garanti


def test_default_providers_wires_value_with_embed_fn():
    import numpy as np
    fake_embed = lambda t: np.zeros(384, dtype="float32")  # noqa: E731  (dim alignée value_net)
    p = make_default_providers(embed_fn=fake_embed)
    assert "value" in p, "embed_fn fourni + forge_value_net loadable → provider value câblé"
    score = p["value"]("state get_y", _act("A"))
    assert isinstance(score, float) and 0.0 <= score <= 1.0  # predict_value ∈ [0,1] tourne


# ── garde-fou correctness : intuition étroite échoue → System 2 ré-élargit ────
def test_plan_fallback_preserves_correctness():
    pl = GOAPPlanner()
    pl.add_action(_act("A", eff={"x": True}))
    pl.add_action(_act("B", pre={"x": True}, eff={"y": True}))
    goal = Goal("get_y", 1, {}, {"y": True})
    # intuition NETTE mais FAUSSE : ne garde que B (qui a besoin de x via A) → voie étroite KO
    bad = {"vec": lambda s, a: 1.0 if a.name == "B" else 0.0}
    plan = pl.plan({}, goal, providers=bad, top_k=1, conf_threshold=0.25)
    names = [a.name for a in plan]
    assert names == ["A", "B"], names  # fallback System 2 retrouve la solution complète


def test_plan_intuition_solves_directly():
    pl = GOAPPlanner()
    pl.add_action(_act("A", eff={"x": True}))
    pl.add_action(_act("B", pre={"x": True}, eff={"y": True}))
    pl.add_action(_act("noise", eff={"z": True}))
    goal = Goal("get_y", 1, {}, {"y": True})
    plan = pl.plan({}, goal)  # intuition défaut (lexical) ne doit pas casser
    assert [a.name for a in plan] == ["A", "B"]


# ── réflexe doute→oracle ─────────────────────────────────────────────────────
def _planner_with_oracle():
    pl = GOAPPlanner()
    pl.add_action(_act("oracle", "oracle_python_repl", eff={"hypothesis_tested": True}))
    pl.add_action(_act("write_file", "write", eff={"file_written": True}))  # effet RISQUÉ
    pl.add_action(_act("noise", eff={"z": True}))
    return pl, Goal("make_file", 1, {}, {"file_written": True})


def test_doubt_reflex_inserts_oracle_before_risky():
    pl, goal = _planner_with_oracle()
    flat = {"vec": lambda s, a: 1.0}  # tous égaux → conf plate (doute) → réflexe
    names = [a.name for a in pl.plan({}, goal, providers=flat, conf_threshold=0.25)]
    assert names == ["oracle", "write_file"], names  # teste AVANT d'agir


def test_no_reflex_when_confident():
    pl, goal = _planner_with_oracle()
    sharp = {"vec": lambda s, a: 5.0 if a.name == "write_file" else 0.0}  # net → pas de doute
    names = [a.name for a in pl.plan({}, goal, providers=sharp, conf_threshold=0.25)]
    assert "oracle" not in names and "write_file" in names  # certain → agit direct


def test_reflex_disabled():
    pl, goal = _planner_with_oracle()
    flat = {"vec": lambda s, a: 1.0}
    names = [a.name for a in pl.plan({}, goal, providers=flat, doubt_reflex=False)]
    assert "oracle" not in names  # réflexe off → pas d'oracle force


# ── keystone self-play : persistance des trajectoires ────────────────────────
def test_record_trajectory_step_persists_with_embed():
    import numpy as np
    from forge_goap_intuition import record_trajectory_step
    cap = {}

    def fake_record(se, action, st1, cb, ca, task_type, success):
        cap.update(se_len=len(se), st1_len=len(st1), action=action, success=success,
                   cb=cb, ca=ca, task=task_type)
        return "rowid123"

    rid = record_trajectory_step("goap: start", {"name": "oracle", "cost": 1},
                                 "goap: start -> oracle", True,
                                 embed_fn=lambda t: np.ones(384, dtype="float32"),
                                 record_fn=fake_record)
    assert rid == "rowid123"
    assert cap["se_len"] == 384 and cap["st1_len"] == 384
    assert cap["action"]["name"] == "oracle" and cap["success"] is True
    assert cap["cb"] == 1.0 and cap["ca"] == 0.0  # succès → cost_after 0 (value target = 1.0)


def test_record_trajectory_step_failure_cost():
    from forge_goap_intuition import record_trajectory_step
    cap = {}
    record_trajectory_step("s", {"name": "a", "cost": 2}, "s2", False,
                           embed_fn=None, record_fn=lambda se, *a, **k: cap.update(se=se, args=a) or "r")
    assert cap["se"] is None  # pas d'embedder (mode absent) → trace sans emb, mais persistée
    # a = (action, st1, cost_before, cost_after, task_type, success) → cb=a[2], ca=a[3]
    assert cap["args"][2] == 2.0 and cap["args"][3] == 2.0  # échec → cost_after = cost_before (target 0)


# ── online embedder (structure, 0 réseau) ────────────────────────────────────
def test_online_embed_fn_returns_callable_or_none():
    from forge_goap_intuition import online_embed_fn
    ef = online_embed_fn()  # ne touche PAS le réseau (l'appel HTTP est dans le closure)
    assert ef is None or callable(ef)


if __name__ == "__main__":
    for n in sorted(dict(globals())):
        if n.startswith("test_"):
            globals()[n]()
            print("PASS", n)
    print("ALL GREEN")
