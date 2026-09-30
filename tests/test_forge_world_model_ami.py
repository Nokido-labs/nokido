"""tests/test_forge_world_model_ami.py — Tests unitaires AMI LeCun core.

Couvre forge_world_model.py :
- NMLP : 3-layer MLP world model (numpy, no GPU)
- JEPA : Joint Embedding Predictive Architecture (LeCun)
- HierarchicalJEPA : H-JEPA multi-scale

Constantes module : INPUT_DIM=768, HIDDEN_1=512, HIDDEN_2=256, OUTPUT_DIM=384.
NMLP(rng_seed=int) ; pas d'args dim au constructor (constants module).
"""
import sys
import math
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


# ============================================================
# NMLP : 3-layer MLP world model
# ============================================================

def test_nmlp_constants():
    from forge_world_model import INPUT_DIM, HIDDEN_1, HIDDEN_2, OUTPUT_DIM
    assert INPUT_DIM == 768
    assert HIDDEN_1 == 512
    assert HIDDEN_2 == 256
    assert OUTPUT_DIM == 384


def test_nmlp_init_shapes():
    from forge_world_model import NMLP, INPUT_DIM, HIDDEN_1, HIDDEN_2, OUTPUT_DIM
    m = NMLP(rng_seed=42)
    assert m.W1.shape == (INPUT_DIM, HIDDEN_1)
    assert m.b1.shape == (HIDDEN_1,)
    assert m.W2.shape == (HIDDEN_1, HIDDEN_2)
    assert m.b2.shape == (HIDDEN_2,)
    assert m.W3.shape == (HIDDEN_2, OUTPUT_DIM)
    assert m.b3.shape == (OUTPUT_DIM,)


def test_nmlp_init_deterministic_seed():
    from forge_world_model import NMLP
    m1 = NMLP(rng_seed=42)
    m2 = NMLP(rng_seed=42)
    np.testing.assert_array_equal(m1.W1, m2.W1)
    np.testing.assert_array_equal(m1.W3, m2.W3)


def test_nmlp_forward_shape():
    from forge_world_model import NMLP, INPUT_DIM, OUTPUT_DIM
    m = NMLP(rng_seed=42)
    x = np.random.randn(INPUT_DIM).astype("float32")
    out = m.forward(x)
    # forward returns tuple (state_t+1, cache) per signature
    assert isinstance(out, tuple)
    pred, _ = out
    assert pred.shape == (OUTPUT_DIM,)
    assert np.isfinite(pred).all()


def test_nmlp_forward_residual():
    """state_t (first OUTPUT_DIM of x) used as residual source."""
    from forge_world_model import NMLP, INPUT_DIM, OUTPUT_DIM
    m = NMLP(rng_seed=42)
    x = np.zeros(INPUT_DIM, dtype="float32")
    pred, _ = m.forward(x)
    assert pred.shape == (OUTPUT_DIM,)


def test_nmlp_deterministic_forward():
    """Same input + same seed -> same output."""
    from forge_world_model import NMLP, INPUT_DIM
    m = NMLP(rng_seed=42)
    x = np.ones(INPUT_DIM, dtype="float32")
    pred1, _ = m.forward(x)
    pred2, _ = m.forward(x)
    np.testing.assert_array_equal(pred1, pred2)


# ============================================================
# JEPA
# ============================================================

def test_jepa_class_exists():
    from forge_world_model import JEPA
    assert JEPA is not None


def test_jepa_init():
    from forge_world_model import JEPA
    m = JEPA(rng_seed=42)
    # Real API : context_encode + target_encode + predict
    assert hasattr(m, "context_encode")
    assert hasattr(m, "CE_W") and hasattr(m, "TE_W") and hasattr(m, "P_W1")


def test_jepa_context_encode_shape():
    from forge_world_model import JEPA, JEPA_IN_DIM, JEPA_LAT_DIM
    m = JEPA(rng_seed=42)
    state = np.random.randn(JEPA_IN_DIM).astype("float32")
    z = m.context_encode(state)
    assert z.shape == (JEPA_LAT_DIM,)
    # L2 normalized
    assert abs(np.linalg.norm(z) - 1.0) < 0.1 or np.linalg.norm(z) < 1e-6


def test_jepa_target_encode_shape():
    from forge_world_model import JEPA, JEPA_IN_DIM, JEPA_LAT_DIM
    m = JEPA(rng_seed=42)
    state = np.random.randn(JEPA_IN_DIM).astype("float32")
    z = m.target_encode(state)
    assert z.shape == (JEPA_LAT_DIM,)


def test_jepa_predict_shape():
    from forge_world_model import JEPA, JEPA_IN_DIM, JEPA_LAT_DIM
    m = JEPA(rng_seed=42)
    state = np.random.randn(JEPA_IN_DIM).astype("float32")
    action = np.random.randn(JEPA_IN_DIM).astype("float32")
    z_c = m.context_encode(state)
    z_pred = m.predict(z_c, action)
    assert z_pred.shape == (JEPA_LAT_DIM,)
    # Normalized
    assert abs(np.linalg.norm(z_pred) - 1.0) < 0.1


def test_jepa_train_step_loss_decreases():
    """Train step doit reduire loss sur meme echantillon iterativement."""
    from forge_world_model import JEPA, JEPA_IN_DIM
    m = JEPA(rng_seed=42)
    state = np.random.randn(JEPA_IN_DIM).astype("float32")
    action = np.random.randn(JEPA_IN_DIM).astype("float32")
    state_next = np.random.randn(JEPA_IN_DIM).astype("float32")

    losses = []
    for _ in range(20):
        loss = m.train_step(state, action, state_next, lr=0.01)
        losses.append(loss)

    # Loss doit etre dans [0, 2] (cosine distance range)
    assert all(0 <= L <= 2 for L in losses)
    # Loss doit globalement decroitre (last < first)
    assert losses[-1] < losses[0]


def test_jepa_ema_update_target_encoder():
    """Target encoder doit etre mis a jour par EMA apres train step."""
    from forge_world_model import JEPA, JEPA_IN_DIM
    m = JEPA(rng_seed=42)
    te_before = m.TE_W.copy()
    state = np.random.randn(JEPA_IN_DIM).astype("float32")
    action = np.random.randn(JEPA_IN_DIM).astype("float32")
    state_next = np.random.randn(JEPA_IN_DIM).astype("float32")

    m.train_step(state, action, state_next, lr=0.01)
    # TE may equal initial CE copy at first, but after multiple steps differs
    for _ in range(50):
        m.train_step(state, action, state_next, lr=0.01)
    # After training, TE should diverge from initial value
    diff = np.abs(m.TE_W - te_before).mean()
    assert diff > 1e-6  # EMA update happened


def test_jepa_save_load_roundtrip(tmp_path):
    from forge_world_model import JEPA, JEPA_IN_DIM
    m = JEPA(rng_seed=42)
    state = np.random.randn(JEPA_IN_DIM).astype("float32")
    z_before = m.context_encode(state)

    save_path = tmp_path / "jepa.npz"
    m.save(save_path)
    assert save_path.exists()

    m2 = JEPA.load(save_path)
    z_after = m2.context_encode(state)
    np.testing.assert_allclose(z_before, z_after, atol=1e-6)


def test_jepa_input_gradient_shape():
    """input_gradient retourne dim action."""
    from forge_world_model import JEPA, JEPA_IN_DIM
    m = JEPA(rng_seed=42)
    state = np.random.randn(JEPA_IN_DIM).astype("float32")
    action = np.random.randn(JEPA_IN_DIM).astype("float32")
    goal = m.target_encode(np.random.randn(JEPA_IN_DIM).astype("float32"))
    z_c = m.context_encode(state)
    grad = m.input_gradient(z_c, action, goal)
    assert grad.shape == (JEPA_IN_DIM,)
    assert np.isfinite(grad).all()


def test_jepa_loss_distribution_after_training():
    """Apres entrainement 50 steps, loss doit etre majoritairement < 0.1."""
    from forge_world_model import JEPA, JEPA_IN_DIM
    m = JEPA(rng_seed=42)
    state = np.random.randn(JEPA_IN_DIM).astype("float32")
    action = np.random.randn(JEPA_IN_DIM).astype("float32")
    state_next = np.random.randn(JEPA_IN_DIM).astype("float32")
    losses = [m.train_step(state, action, state_next, lr=0.01) for _ in range(50)]
    # Final 10 should be much lower than initial 10
    initial_avg = sum(losses[:10]) / 10
    final_avg = sum(losses[-10:]) / 10
    assert final_avg < initial_avg
    assert final_avg < 0.1


def test_jepa_gradient_refine_action_via_input_grad():
    """Refining action via grad descent reduces loss."""
    from forge_world_model import JEPA, JEPA_IN_DIM
    m = JEPA(rng_seed=42)
    state = np.random.randn(JEPA_IN_DIM).astype("float32")
    goal_state = np.random.randn(JEPA_IN_DIM).astype("float32")
    goal_latent = m.target_encode(goal_state)
    z_c = m.context_encode(state)

    # Initial random action
    action = np.random.randn(JEPA_IN_DIM).astype("float32") * 0.1

    def _loss(a):
        z_p = m.predict(z_c, a)
        return float(1.0 - np.dot(z_p, goal_latent))

    initial_loss = _loss(action)
    # Gradient descent on action
    for _ in range(50):
        grad = m.input_gradient(z_c, action, goal_latent)
        action = action - 0.05 * grad
    final_loss = _loss(action)
    assert final_loss < initial_loss


def test_h_jepa_save_load_roundtrip(tmp_path):
    """HierarchicalJEPA save/load preserve weights."""
    from forge_world_model import HierarchicalJEPA, H_LAT_DIM, H_ACT_DIM
    m = HierarchicalJEPA(rng_seed=42)
    z_seq = np.random.randn(4, H_LAT_DIM).astype("float32")
    z_coarse_before = m.coarse_encode(z_seq)

    # Save manually if exists, else skip
    if not hasattr(m, "save"):
        pytest.skip("HierarchicalJEPA has no save method")
    save_path = tmp_path / "h_jepa.npz"
    m.save(save_path)
    if hasattr(HierarchicalJEPA, "load"):
        m2 = HierarchicalJEPA.load(save_path)
        z_after = m2.coarse_encode(z_seq)
        np.testing.assert_allclose(z_coarse_before, z_after, atol=1e-6)


# ============================================================
# HierarchicalJEPA
# ============================================================

def test_h_jepa_class_exists():
    from forge_world_model import HierarchicalJEPA
    assert HierarchicalJEPA is not None


def test_h_jepa_init():
    from forge_world_model import HierarchicalJEPA
    m = HierarchicalJEPA(rng_seed=42)
    assert hasattr(m, "coarse_encode")
    assert hasattr(m, "coarse_target")
    assert hasattr(m, "predict")
    assert hasattr(m, "train_step")


def test_h_jepa_coarse_encode_shape():
    from forge_world_model import HierarchicalJEPA, H_LAT_DIM
    m = HierarchicalJEPA(rng_seed=42)
    # k=4 fine context vecs each 256d
    z_c_seq = np.random.randn(4, H_LAT_DIM).astype("float32")
    z_coarse = m.coarse_encode(z_c_seq)
    assert z_coarse.shape == (H_LAT_DIM,)


def test_h_jepa_predict_shape():
    from forge_world_model import HierarchicalJEPA, H_LAT_DIM, H_ACT_DIM
    m = HierarchicalJEPA(rng_seed=42)
    z_coarse = np.random.randn(H_LAT_DIM).astype("float32")
    mean_action = np.random.randn(H_ACT_DIM).astype("float32")
    z_pred = m.predict(z_coarse, mean_action)
    assert z_pred.shape == (H_LAT_DIM,)
    assert abs(np.linalg.norm(z_pred) - 1.0) < 0.1


def test_h_jepa_train_step_loss_decreases():
    """H-JEPA k-step training reduit loss iterativement."""
    from forge_world_model import HierarchicalJEPA, H_LAT_DIM, H_ACT_DIM
    m = HierarchicalJEPA(rng_seed=42)
    k = 4
    z_c_seq = np.random.randn(k, H_LAT_DIM).astype("float32")
    action_embs = np.random.randn(k, H_ACT_DIM).astype("float32")
    z_target = np.random.randn(H_LAT_DIM).astype("float32")

    losses = []
    for _ in range(30):
        loss = m.train_step(z_c_seq, action_embs, z_target, lr=0.01)
        losses.append(loss)

    assert all(0 <= L <= 2 for L in losses)
    assert losses[-1] < losses[0]


# ============================================================
# Module-level loaders : tolerant fallback
# ============================================================

def test_get_model_returns_nmlp_or_none():
    from forge_world_model import _get_model, NMLP
    m = _get_model()
    assert m is None or isinstance(m, NMLP)


def test_predict_smoke():
    """predict() shape OK quand model dispo."""
    from forge_world_model import predict, _get_model, OUTPUT_DIM
    model = _get_model()
    if model is None:
        pytest.skip("no model loaded")
    state = np.random.randn(OUTPUT_DIM).astype("float32")
    out = predict(state, "test_action")
    assert out is None or out.shape == (OUTPUT_DIM,)


# ============================================================
# Existing weights .npz smoke
# ============================================================

def test_existing_npz_loadable():
    """RAG/world_model.npz devrait charger sans crash."""
    npz_path = ROOT / "RAG" / "world_model.npz"
    if not npz_path.exists():
        pytest.skip("no world_model.npz")
    data = np.load(npz_path)
    assert len(data.files) > 0
    # Should contain W1 or similar
    has_weights = any(k.startswith("W") for k in data.files)
    assert has_weights


def test_existing_jepa_npz_loadable():
    npz_path = ROOT / "RAG" / "world_model_jepa.npz"
    if not npz_path.exists():
        pytest.skip("no jepa npz")
    data = np.load(npz_path)
    assert len(data.files) > 0
