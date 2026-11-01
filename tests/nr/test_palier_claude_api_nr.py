# -*- coding: utf-8 -*-
"""NR : palier effort et modele pour la surface claude_api (owner 30/10)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_palier_effort as P  # noqa: E402

ABSENT = Path("absent.json")


def test_palier_claude_api_S():
    res = P.resoudre("claude_api", "S", census=ABSENT)
    assert res["modele"] == "claude-haiku-5-5"
    assert res["effort"] == "low"


def test_palier_claude_api_L():
    res = P.resoudre("claude_api", "L", census=ABSENT)
    assert res["effort"] == "medium"


def test_palier_claude_api_high_sans_escalade_leve_value_error():
    with pytest.raises(ValueError):
        P.resoudre("claude_api", "S", effort="high", census=ABSENT)
