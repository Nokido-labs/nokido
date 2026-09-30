"""Tests evaluate_patch helper (scorecard fragments mode)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_scorecard import (  # noqa
    ExecutionState, QualityGrade, evaluate_patch,
)


def _write_tmp(code: str) -> str:
    with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        return f.name


def test_evaluate_patch_ast_fail_returns_crashed():
    p = _write_tmp("def broken(:\n  return\n")  # syntax error
    try:
        sc = evaluate_patch(p, task_desc="dummy")
        assert sc.state == ExecutionState.CRASHED
        assert sc.grade == QualityGrade.REJECTED
        assert "AST error" in sc.critique
    finally:
        Path(p).unlink(missing_ok=True)


def test_evaluate_patch_no_pylint_check():
    """Patch sans imports / module -> evaluate_code donnerait pylint 0/10.
    evaluate_patch ne dependent que de AST + sem judge."""
    p = _write_tmp("def f(x):\n    return x + 1\n")
    try:
        with patch("forge_scorecard._llm_judge",
                   return_value=(0.95, "perfect for the task")):
            sc = evaluate_patch(p, task_desc="add 1 to x")
        assert sc.grade == QualityGrade.OPTIMAL
        assert sc.confidence_score == 0.95
        assert "patch_ast: OK" in sc.critique
        assert "perfect" in sc.critique
    finally:
        Path(p).unlink(missing_ok=True)


def test_evaluate_patch_sem_score_drives_grade():
    p = _write_tmp("def f():\n    pass\n")
    try:
        with patch("forge_scorecard._llm_judge",
                   return_value=(0.5, "needs return value")):
            sc = evaluate_patch(p, task_desc="x")
        assert sc.grade == QualityGrade.PARTIAL
        assert sc.confidence_score == 0.5
    finally:
        Path(p).unlink(missing_ok=True)


def test_evaluate_patch_no_task_desc_skips_judge():
    p = _write_tmp("x = 1\n")
    try:
        sc = evaluate_patch(p, task_desc="")
        assert sc.confidence_score == 1.0
        assert sc.grade == QualityGrade.OPTIMAL
        assert "judge skipped" in sc.critique
    finally:
        Path(p).unlink(missing_ok=True)
