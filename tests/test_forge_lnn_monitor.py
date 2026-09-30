"""Tests forge_lnn_monitor - wrap ncps CfC."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


def test_ncps_available():
    import forge_lnn_monitor as lnn
    if not lnn.available():
        pytest.skip("ncps non installe")


def test_build_monitor():
    import forge_lnn_monitor as lnn
    if not lnn.available():
        pytest.skip("ncps non installe")
    m = lnn.build_monitor(input_dim=4, hidden=16)
    assert m.input_dim == 4
    assert m.hidden == 16
    assert m.n_params() > 0


def test_predict_next_shape():
    import forge_lnn_monitor as lnn
    if not lnn.available():
        pytest.skip("ncps non installe")
    import torch
    m = lnn.build_monitor(input_dim=4, hidden=16)
    x = torch.randn(2, 10, 4)  # batch=2, T=10, dim=4
    y = m.predict_next(x)
    assert y.shape == (2, 16)


def test_train_step_decreases_loss():
    import forge_lnn_monitor as lnn
    if not lnn.available():
        pytest.skip("ncps non installe")
    import torch
    torch.manual_seed(42)
    m = lnn.build_monitor(input_dim=4, hidden=4)
    x = torch.randn(8, 5, 4)
    target = x[:, -1, :4]
    losses = [m.train_step(x, target, lr=1e-2) for _ in range(20)]
    assert losses[-1] < losses[0]
