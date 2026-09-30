"""Tests forge_lats - tree search + sandbox deterministe.

On evite l infra docker/git reelle : mock test_fn pour controler les scores.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_lats import (  # noqa
    LATSNode, PatchProposal, SandboxResult, lats_search,
)


def test_score_no_apply():
    sb = SandboxResult(apply_ok=False)
    assert sb.score == 0.0


def test_score_partial():
    sb = SandboxResult(apply_ok=True, passed=3, total=5)
    assert sb.score == 0.6


def test_score_perfect():
    sb = SandboxResult(apply_ok=True, passed=5, total=5)
    assert sb.score == 1.0


def test_lats_search_returns_perfect_at_depth1():
    """Une proposal score 1.0 d entree -> stop early, best = elle."""
    def propose(problem, last_result):
        return [
            PatchProposal(diff="d1", provider="cerebras"),
            PatchProposal(diff="d2", provider="groq"),
            PatchProposal(diff="d3", provider="github"),
        ]

    def test(workdir, diff):
        if diff == "d2":
            return SandboxResult(apply_ok=True, passed=10, total=10)  # perfect
        return SandboxResult(apply_ok=True, passed=5, total=10)

    r = lats_search("p", "/tmp/dummy", propose, test_fn=test,
                    n_initial=3, max_depth=2)
    assert r["best"].patch.diff == "d2"
    assert r["best"].result.score == 1.0
    # Pas de depth 2 declenchee
    assert all(n.depth <= 1 for n in r["all_nodes"])


def test_lats_search_refines_when_no_perfect():
    """Pas de perfect en depth 1, beam refine en depth 2."""
    call_count = {"n": 0}

    def propose(problem, last_result):
        call_count["n"] += 1
        if last_result is None:
            # Initial : 3 proposals partial
            return [
                PatchProposal(diff="init1", provider="cerebras"),
                PatchProposal(diff="init2", provider="groq"),
                PatchProposal(diff="init3", provider="github"),
            ]
        # Refine : 2 proposals base sur error_log
        return [
            PatchProposal(diff=f"refine_from_{last_result.score}_a",
                          provider="cerebras"),
            PatchProposal(diff=f"refine_from_{last_result.score}_b",
                          provider="groq"),
        ]

    def test(workdir, diff):
        if diff.startswith("refine_from_0.7"):
            return SandboxResult(apply_ok=True, passed=10, total=10)  # found perfect
        if diff == "init1":
            return SandboxResult(apply_ok=True, passed=7, total=10)  # 0.7
        if diff == "init2":
            return SandboxResult(apply_ok=True, passed=5, total=10)  # 0.5
        return SandboxResult(apply_ok=True, passed=3, total=10)

    r = lats_search("p", "/tmp/dummy", propose, test_fn=test,
                    n_initial=3, max_depth=2, beam_width=2)
    # Le best = refine perfect
    assert r["best"].result.score == 1.0
    assert "refine_from_0.7" in r["best"].patch.diff
    # Confirmer arbre profondeur 2
    assert any(n.depth == 2 for n in r["all_nodes"])


def test_lats_search_apply_fail_no_descendants():
    """Aucun apply ok -> pas de refine descendre."""
    def propose(problem, last_result):
        return [PatchProposal(diff=f"d{i}", provider="cerebras") for i in range(3)]

    def test(workdir, diff):
        return SandboxResult(apply_ok=False, error_log="git apply fail")

    r = lats_search("p", "/tmp/dummy", propose, test_fn=test,
                    n_initial=3, max_depth=3)
    # 3 nodes depth 1 + root, aucun depth 2 (pas de survivor)
    assert len([n for n in r["all_nodes"] if n.depth >= 2]) == 0
    assert r["best"].result.score == 0.0


def test_lats_search_tracks_elapsed():
    def propose(problem, last_result):
        return [PatchProposal(diff="d", provider="x")]

    def test(workdir, diff):
        return SandboxResult(apply_ok=True, passed=1, total=1)

    r = lats_search("p", "/tmp/dummy", propose, test_fn=test,
                    n_initial=1, max_depth=1)
    assert "elapsed_s" in r
    assert r["n_evaluated"] >= 1
