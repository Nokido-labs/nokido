"""Tests evaluate_symbolic - juge deterministe zero LLM."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus pylint (code appele); parcours du
#   depot : lecture+ast de tous les app/forge_*.py (code appele) (l.43)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from forge_scorecard import (  # noqa
    ExecutionState, QualityGrade, evaluate_symbolic,
)


def _tmp(code: str) -> str:
    with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        return f.name


def test_symbolic_ast_fail_returns_crashed():
    p = _tmp("def broken(:\n    return\n")
    try:
        sc = evaluate_symbolic(p)
        assert sc.state == ExecutionState.CRASHED
        assert sc.grade == QualityGrade.REJECTED
    finally:
        Path(p).unlink(missing_ok=True)


def test_symbolic_clean_code_high_confidence():
    """Code minimal valide + imports standards -> grade >= PARTIAL."""
    code = (
        '"""docstring"""\n'
        "import json\n"
        "def add(a, b):\n"
        "    return a + b\n"
    )
    p = _tmp(code)
    try:
        sc = evaluate_symbolic(p)
        # ast.25 + loc.20 + dep.15 + tokens.15 = 0.75 min (pylint variable)
        assert sc.confidence_score >= 0.70
        assert sc.grade in (QualityGrade.PARTIAL, QualityGrade.OPTIMAL)
        assert "ast=OK" in sc.critique
        assert "dep=OK" in sc.critique
    finally:
        Path(p).unlink(missing_ok=True)


def test_symbolic_broken_import_drops_dep_score():
    code = (
        "from definitely_inexistent_pkg_zzz import foo\n"
        "x = foo()\n"
    )
    p = _tmp(code)
    try:
        sc = evaluate_symbolic(p)
        assert "broken=" in sc.critique
        # ast.25 + loc.20 + dep.00 + tokens.15 = 0.60 max
        assert sc.confidence_score < 0.70
    finally:
        Path(p).unlink(missing_ok=True)


def test_symbolic_huge_file_penalized():
    """500 LOC -> loc_score = 0."""
    code = "\n".join(f"x_{i} = {i}" for i in range(600))
    p = _tmp(code)
    try:
        sc = evaluate_symbolic(p, token_budget=500)
        assert "500" in sc.critique or "600" in sc.critique
        # loc = 0.0, tok > 500 -> tok = 0.0
        # ast.20 + pylint up to .20 + dep.15 + mccabe.15 = 0.70 max
        assert sc.confidence_score <= 0.75
    finally:
        Path(p).unlink(missing_ok=True)


def test_symbolic_token_budget_enforced():
    code = "x = " + "1" + "+1" * 2000 + "\n"  # ~4000 chars / 4 = 1000 tok
    p = _tmp(code)
    try:
        sc = evaluate_symbolic(p, token_budget=100)
        assert "tok" in sc.critique
        # tokens > budget -> tok_score = 0
    finally:
        Path(p).unlink(missing_ok=True)


def test_symbolic_no_llm_invocation():
    """Verifie qu evaluate_symbolic n importe PAS urllib pour Ollama.
    Garantie de l independance vs juge neuronal (gouvernance Marcus)."""
    import forge_scorecard
    import inspect
    src = inspect.getsource(forge_scorecard.evaluate_symbolic)
    # Ne doit pas contenir d appel _llm_judge ni urlopen vers 11434
    assert "_llm_judge" not in src
    assert "11434" not in src
    assert "ollama" not in src.lower()


def test_critical_nodes_dynamic_via_graph():
    """_critical_nodes() doit retourner un set non vide superset du fallback."""
    import forge_scorecard
    # Reset cache pour forcer re-build
    forge_scorecard._critical_cache = None
    crit = forge_scorecard._critical_nodes(top_n=20)
    assert isinstance(crit, frozenset)
    assert len(crit) >= len(forge_scorecard._CRITICAL_NODES_FALLBACK)
    # Fallback nodes doivent rester presents (union garantie)
    for fb in forge_scorecard._CRITICAL_NODES_FALLBACK:
        assert fb in crit
