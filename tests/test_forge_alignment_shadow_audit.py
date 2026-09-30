# -*- coding: utf-8 -*-
"""
test_forge_alignment_shadow_audit.py — Tests unitaires pour le harness d'audit shadow.
"""
from __future__ import annotations

import pytest
import sys
from pathlib import Path

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus opa (code appele) (l.19)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.forge_alignment_shadow_audit import run_audit

def test_shadow_audit_runs_and_returns_report():
    report = run_audit()
    assert report is not None
    assert "total_scenarios" in report
    assert report["total_scenarios"] > 0
    assert "rates" in report
    assert "results" in report
    
    # Assert all layers are calculated
    assert "authz" in report["rates"]
    assert "injection" in report["rates"]
    assert "rsp" in report["rates"]

    # Assert results list matches scenarios length
    assert len(report["results"]) == report["total_scenarios"]
    for r in report["results"]:
        assert "name" in r
        assert "layer" in r
        assert "diverged" in r
        assert "details" in r
