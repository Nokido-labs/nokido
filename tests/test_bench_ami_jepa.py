"""tests/test_bench_ami_jepa.py - pytest-benchmark sur ops AMI/JEPA critiques.

Per Gemini Web 2026-05-29 plan ordonne #3 (Quick Win) :
Bench ops CPU-bound pures (numpy + scipy ops, zero IO) sur :
- NMLP forward pass
- JEPA encode (context + target)
- JEPA train_step (forward + backward + EMA update)
- HJEPA coarse encode

Reuse forge_world_model code path -- pas de mock, vraies operations production.
Run cross-env :
    LAFORGE_PYTHON -m pytest tests/test_bench_ami_jepa.py --benchmark-only \
        --benchmark-json=sandbox/perf_history/ami_py312_baseline.json

    %USERPROFILE%/miniforge3/envs/laforge_py314/python.exe -m pytest \
        tests/test_bench_ami_jepa.py --benchmark-only \
        --benchmark-json=sandbox/perf_history/ami_py314_gil.json
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def nmlp():
    """NMLP instance with fixed seed for reproducibility."""
    from forge_world_model import NMLP

    return NMLP(rng_seed=42)


@pytest.fixture(scope="module")
def jepa():
    from forge_world_model import JEPA

    return JEPA(rng_seed=42)


@pytest.fixture(scope="module")
def hjepa():
    from forge_world_model import HierarchicalJEPA

    return HierarchicalJEPA(rng_seed=42)


@pytest.fixture(scope="module")
def random_input_nmlp():
    """768-D input vector (NMLP INPUT_DIM = state[384] + action[384])."""
    rng = np.random.default_rng(42)
    return rng.standard_normal(768).astype(np.float32)


@pytest.fixture(scope="module")
def random_input_jepa():
    """384-D state embedding (JEPA_IN_DIM)."""
    rng = np.random.default_rng(42)
    return rng.standard_normal(384).astype(np.float32)


@pytest.fixture(scope="module")
def batch_input_nmlp():
    """Batch of 32 NMLP input vectors (768-D)."""
    rng = np.random.default_rng(42)
    return rng.standard_normal((32, 768)).astype(np.float32)


@pytest.fixture(scope="module")
def jepa_train_triplet():
    """Triplet (state_t, action_emb, state_t1) for JEPA train_step."""
    rng = np.random.default_rng(42)
    return (
        rng.standard_normal(384).astype(np.float32),
        rng.standard_normal(384).astype(np.float32),
        rng.standard_normal(384).astype(np.float32),
    )


@pytest.fixture(scope="module")
def hjepa_seq():
    """Sequence of latent embeddings for HJEPA coarse_encode (shape T x JEPA_LAT_DIM)."""
    rng = np.random.default_rng(42)
    return rng.standard_normal((4, 256)).astype(np.float32)


# ── Benchmarks NMLP ────────────────────────────────────────────────────────────


@pytest.mark.benchmark(group="nmlp_forward")
def test_bench_nmlp_forward_single(benchmark, nmlp, random_input_nmlp):
    """Single 768-D vector forward through NMLP (returns tuple out_norm, cache)."""
    benchmark(nmlp.forward, random_input_nmlp)


@pytest.mark.benchmark(group="nmlp_forward")
def test_bench_nmlp_forward_batch32(benchmark, nmlp, batch_input_nmlp):
    """Batch of 32 vectors through NMLP -- collect out_norm only."""

    def run():
        return [nmlp.forward(x)[0] for x in batch_input_nmlp]

    benchmark(run)


# ── Benchmarks JEPA ────────────────────────────────────────────────────────────


@pytest.mark.benchmark(group="jepa_encode")
def test_bench_jepa_context_encode(benchmark, jepa, random_input_jepa):
    benchmark(jepa.context_encode, random_input_jepa)


@pytest.mark.benchmark(group="jepa_encode")
def test_bench_jepa_target_encode(benchmark, jepa, random_input_jepa):
    benchmark(jepa.target_encode, random_input_jepa)


@pytest.mark.benchmark(group="jepa_predict")
def test_bench_jepa_predict(benchmark, jepa, random_input_jepa):
    """predict(z_c, action_emb) -- both must be JEPA_LAT_DIM=256."""
    z_c = jepa.context_encode(random_input_jepa)
    rng = np.random.default_rng(42)
    action_emb = rng.standard_normal(384).astype(np.float32)  # P expects JEPA_IN_DIM action
    benchmark(jepa.predict, z_c, action_emb)


@pytest.mark.benchmark(group="jepa_train")
def test_bench_jepa_train_step(benchmark, jepa, jepa_train_triplet):
    """Forward + backward + EMA update -- coeur loop entrainement (3-arg signature)."""
    state_t, action_emb, state_t1 = jepa_train_triplet

    def step():
        return jepa.train_step(state_t, action_emb, state_t1, lr=1e-3)

    benchmark(step)


# ── Benchmarks HJEPA ───────────────────────────────────────────────────────────


@pytest.mark.benchmark(group="hjepa")
def test_bench_hjepa_coarse_encode(benchmark, hjepa, hjepa_seq):
    """coarse_encode prend seq de latents -- pas un vecteur seul."""
    benchmark(hjepa.coarse_encode, hjepa_seq)


# ── Bench numpy ops (control) ──────────────────────────────────────────────────


@pytest.mark.benchmark(group="numpy_control")
def test_bench_numpy_matmul_768x512(benchmark, random_input_nmlp):
    """Pure numpy matmul -- control bench. Should be nearly identical cross-env."""
    rng = np.random.default_rng(0)
    W = rng.standard_normal((768, 512)).astype(np.float32)
    benchmark(np.matmul, random_input_nmlp, W)
