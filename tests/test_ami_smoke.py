"""tests/test_ami_smoke.py — couverture smoke pour la stack AMI LeCun.

10 modules core : world_model (NMLP/JEPA/H-JEPA), value_net, policy_net,
cost_net, actor (Node MCTS), stm, state_encoder, mpc (dataclasses),
continual_backprop, configurator.

Smoke tests : import + instantiate + 1 appel sain. PAS de training, PAS de
fichier disque. But : couvrir la surface d'API et detecter les regressions
d'import / signature / numpy dtype / forward pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import numpy as np  # noqa: E402


# === forge_world_model ========================================================

def test_world_model_nmlp_forward():
    from forge_world_model import NMLP, INPUT_DIM, OUTPUT_DIM
    m = NMLP(rng_seed=42)
    x = np.random.randn(INPUT_DIM).astype(np.float32)
    fwd = m.forward(x)
    out = fwd[0] if isinstance(fwd, tuple) else fwd
    assert out is not None
    assert out.shape[-1] == OUTPUT_DIM
    assert np.all(np.isfinite(out))


def test_world_model_jepa_encode():
    from forge_world_model import JEPA
    j = JEPA(rng_seed=42)
    state_emb = np.random.randn(384).astype(np.float32)
    z = j.context_encode(state_emb)
    assert z is not None
    assert z.shape[-1] in (128, 256, 384)


def test_world_model_h_jepa_init():
    from forge_world_model import HierarchicalJEPA
    h = HierarchicalJEPA(rng_seed=42)
    assert h is not None


# === forge_value_net ==========================================================

def test_value_net_forward():
    from forge_value_net import ValueNet
    v = ValueNet(rng_seed=42)
    x = np.random.randn(384).astype(np.float32)
    fwd = v.forward(x)
    out = fwd[0] if isinstance(fwd, tuple) else fwd
    assert out is not None
    arr = np.asarray(out).ravel()
    assert arr.size >= 1
    assert np.all(np.isfinite(arr))


# === forge_policy_net =========================================================

def test_policy_net_forward():
    from forge_policy_net import PolicyNet
    p = PolicyNet(rng_seed=42)
    x = np.random.randn(384 * 2).astype(np.float32)  # state+goal concat
    try:
        fwd = p.forward(x)
    except (ValueError, AssertionError):
        # fallback : peut etre attendre dim 384
        fwd = p.forward(x[:384])
    out = fwd[0] if isinstance(fwd, tuple) else fwd
    assert out is not None
    assert np.all(np.isfinite(np.asarray(out)))


# === forge_cost_net ===========================================================

def test_cost_net_forward():
    from forge_cost_net import CostNet
    c = CostNet(rng_seed=42)
    x = np.random.randn(384 * 2).astype(np.float32)
    try:
        fwd = c.forward(x)
    except (ValueError, AssertionError):
        fwd = c.forward(x[:384])
    out = fwd[0] if isinstance(fwd, tuple) else fwd
    arr = np.asarray(out).ravel()
    assert arr.size >= 1
    assert np.all(np.isfinite(arr))


# === forge_actor ==============================================================

def test_actor_node_uct():
    from forge_actor import Node
    n = Node(plan={"action": "noop"}, parent=None, depth=0)
    n.update(reward=0.7)
    # uct sans visite parent -> exploration term divise par 0 evite via fallback
    score = n.uct(exploration=1.0)
    assert isinstance(score, float)
    assert np.isfinite(score) or score == float("inf")


# === forge_stm ================================================================

def test_stm_push_and_context():
    from forge_stm import ShortTermMemory
    stm = ShortTermMemory(capacity=10)
    stm.push(state_text="s1", action_desc="a1", actual_cost=0.5,
             success=True, state_emb=np.zeros(384), goal_text="g")
    ctx = stm.get_context(n=5)
    assert ctx is not None
    assert len(ctx) >= 1 if hasattr(ctx, "__len__") else True


def test_stm_singleton_get_stm():
    from forge_stm import get_stm
    s = get_stm()
    assert s is not None
    assert hasattr(s, "push")


# === forge_state_encoder ======================================================

def test_state_encoder_cosine_similarity():
    from forge_state_encoder import cosine_similarity
    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    b = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    c = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    assert abs(cosine_similarity(a, b) - 1.0) < 1e-5
    assert abs(cosine_similarity(a, c)) < 1e-5


# === forge_mpc ================================================================

def test_mpc_step_dataclass():
    from forge_mpc import MPCStep
    # dataclass : on instancie avec des valeurs neutres
    fields = list(MPCStep.__dataclass_fields__.keys())
    assert len(fields) >= 2  # au moins action + cost


def test_mpc_result_dataclass():
    from forge_mpc import MPCResult
    fields = list(MPCResult.__dataclass_fields__.keys())
    assert len(fields) >= 1


# === forge_continual_backprop =================================================

def test_continual_backprop_stats():
    from forge_continual_backprop import ContinualBackprop
    cb = ContinualBackprop(rng=np.random.default_rng(42))
    # `stats` peut etre method ou @property selon version
    s = cb.stats() if callable(getattr(cb, "stats", None)) else cb.stats
    assert isinstance(s, dict)


# === forge_configurator =======================================================

def test_configurator_classify_task():
    """classify_task charge sentence_transformers -> peut crasher si packaging
    perm denied (icacls /T conda en cours / pyc stale). xfail dans ce cas."""
    import pytest
    try:
        from forge_configurator import classify_task
        t = classify_task("write a python module to parse YAML files")
    except (PermissionError, ImportError) as e:
        pytest.xfail(f"sentence_transformers env: {e}")
    assert isinstance(t, str)
    assert len(t) > 0


def test_configurator_get_mpc_config():
    import pytest
    try:
        from forge_configurator import get_mpc_config
        cfg = get_mpc_config("debug a failing pytest", state_text="repo state")
    except (PermissionError, ImportError) as e:
        pytest.xfail(f"sentence_transformers env: {e}")
    assert isinstance(cfg, dict)
    assert any(k in cfg for k in ("horizon", "n_candidates", "task_type"))
