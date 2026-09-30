"""Tests forge_active_inference_agent - wrap pymdp Friston."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


def test_pymdp_available():
    import forge_active_inference_agent as fa
    if not fa.available():
        pytest.skip("pymdp non installe")


def test_build_cyber_agent_basic():
    import forge_active_inference_agent as fa
    if not fa.available():
        pytest.skip("pymdp non installe")
    ag = fa.build_cyber_agent(n_states=4, n_obs=3, n_actions=3, seed=42)
    assert ag.n_states == 4
    assert ag.n_obs == 3
    assert ag.n_actions == 3
    assert ag.pymdp_agent is not None


def test_observe_returns_posterior():
    import forge_active_inference_agent as fa
    if not fa.available():
        pytest.skip("pymdp non installe")
    ag = fa.build_cyber_agent(n_states=4, n_obs=3, n_actions=3, seed=42)
    post = ag.observe(0)
    assert post is not None


def test_choose_action_returns_int():
    import forge_active_inference_agent as fa
    if not fa.available():
        pytest.skip("pymdp non installe")
    ag = fa.build_cyber_agent(n_states=4, n_obs=3, n_actions=3, seed=42)
    ag.observe(0)
    action = ag.choose_action()
    assert isinstance(action, int)
    assert 0 <= action < ag.n_actions


def test_observe_out_of_range_raises():
    import forge_active_inference_agent as fa
    if not fa.available():
        pytest.skip("pymdp non installe")
    ag = fa.build_cyber_agent(n_states=4, n_obs=3, n_actions=3, seed=42)
    with pytest.raises(ValueError):
        ag.observe(99)


def test_surprise_returns_float():
    import forge_active_inference_agent as fa
    if not fa.available():
        pytest.skip("pymdp non installe")
    ag = fa.build_cyber_agent(n_states=4, n_obs=3, n_actions=3, seed=42)
    s = ag.surprise(1)
    assert isinstance(s, float)
