"""tests/test_forge_scorecard.py - tests de forge_scorecard module."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_scorecard import (  # noqa: E402
    ExecutionState, QualityGrade, Scorecard, ScoreMetrics,
    evaluate_code, grade_from_score, next_action_for,
)


# === grade_from_score =========================================================

def test_grade_optimal():
    assert grade_from_score(0.95) == QualityGrade.OPTIMAL
    assert grade_from_score(0.9) == QualityGrade.OPTIMAL


def test_grade_partial():
    assert grade_from_score(0.5) == QualityGrade.PARTIAL
    assert grade_from_score(0.4) == QualityGrade.PARTIAL
    assert grade_from_score(0.89) == QualityGrade.PARTIAL


def test_grade_rejected():
    assert grade_from_score(0.3) == QualityGrade.REJECTED
    assert grade_from_score(0.0) == QualityGrade.REJECTED


# === Scorecard dataclass ======================================================

def test_scorecard_default():
    sc = Scorecard()
    assert sc.state == ExecutionState.COMPLETED
    assert sc.grade == QualityGrade.UNRATED
    assert sc.confidence_score == 0.0
    assert sc.payload is None


def test_scorecard_crashed_factory():
    sc = Scorecard.crashed("OOM", payload={"step": 3})
    assert sc.state == ExecutionState.CRASHED
    assert sc.grade == QualityGrade.REJECTED
    assert sc.payload == {"step": 3}
    assert "OOM" in sc.critique


def test_scorecard_timeout_factory():
    sc = Scorecard.timeout(30.0)
    assert sc.state == ExecutionState.TIMEOUT
    assert sc.grade == QualityGrade.REJECTED
    assert "30" in sc.critique


def test_scorecard_to_json_roundtrip():
    import json
    sc = Scorecard(grade=QualityGrade.PARTIAL, confidence_score=0.75)
    parsed = json.loads(sc.to_json())
    assert parsed["grade"] == "PARTIAL"
    assert parsed["confidence_score"] == 0.75


# === evaluate_code combine min ================================================

def test_evaluate_combine_and_min():
    """det=1.0 + sem=0.6 -> min=0.6 -> PARTIAL."""
    with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("def f():\n    return 1\n")
        path = f.name
    try:
        with patch("forge_scorecard._run_quality_gate",
                   return_value=(1.0, "all pass")), \
             patch("forge_scorecard._llm_judge",
                   return_value=(0.6, "incomplete")):
            sc = evaluate_code(path, task_desc="dummy")
        assert sc.grade == QualityGrade.PARTIAL
        assert sc.confidence_score == 0.6
        assert "det:" in sc.critique
        assert "sem:" in sc.critique
    finally:
        Path(path).unlink(missing_ok=True)


def test_evaluate_no_task_desc_skips_judge():
    """task_desc='' -> sem=1.0 -> grade depends on det alone."""
    with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("x = 1\n")
        path = f.name
    try:
        with patch("forge_scorecard._run_quality_gate",
                   return_value=(0.5, "1 error")):
            sc = evaluate_code(path, task_desc="")
        assert sc.confidence_score == 0.5
        assert sc.grade == QualityGrade.PARTIAL
        assert "judge skipped" in sc.critique
    finally:
        Path(path).unlink(missing_ok=True)


def test_evaluate_gate_crash_returns_crashed():
    with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("\n")
        path = f.name
    try:
        with patch("forge_scorecard._run_quality_gate",
                   return_value=(-1.0, "pylint not found")):
            sc = evaluate_code(path, task_desc="x")
        assert sc.state == ExecutionState.CRASHED
        assert sc.grade == QualityGrade.REJECTED
    finally:
        Path(path).unlink(missing_ok=True)


# === GOAP routing =============================================================

def test_next_action_optimal():
    sc = Scorecard(grade=QualityGrade.OPTIMAL)
    assert next_action_for(sc) == "close"


def test_next_action_partial_refine():
    sc = Scorecard(grade=QualityGrade.PARTIAL)
    assert next_action_for(sc) == "refine"


def test_next_action_rejected_ban():
    sc = Scorecard(grade=QualityGrade.REJECTED)
    assert next_action_for(sc) == "ban_and_retry"


def test_next_action_unrated_judges():
    sc = Scorecard()  # default UNRATED
    assert next_action_for(sc) == "judge"


# === ScoreMetrics =============================================================

def test_score_metrics_default():
    m = ScoreMetrics()
    assert m.duration_ms == 0.0
    assert m.tokens_used == 0
    assert m.memory_peak_mb == 0.0
