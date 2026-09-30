"""Tests forge_dspy_router - signatures + parsing JSON strict."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


def test_dspy_module_loadable():
    import forge_dspy_router as r
    assert r._DSPY_OK is True


def test_signatures_defined():
    import forge_dspy_router as r
    assert hasattr(r, "CodePatchProposal")
    assert hasattr(r, "StrategyHypothesis")


def test_signature_call_unknown_signature():
    import forge_dspy_router as r
    out = r.signature_call("Bogus", {}, "groq", "tok")
    assert out["ok"] is False
    assert "inconnue" in out["error"]


def test_signature_call_parses_json_response():
    import forge_dspy_router as r
    fake_text = json.dumps({"text": json.dumps({
        "code": "def f(): pass",
        "rationale": "minimal stub",
        "risk_level": "low",
        "affected_symbols": "def f",
    })})
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps({
        "result": {"content": [{"text": fake_text}]}
    }).encode()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        out = r.signature_call(
            "CodePatchProposal",
            {"goal": "test", "file_context": "x", "constraints": "none"},
            "groq", "tok")
    assert out["ok"] is True
    assert out["fields"]["risk_level"] == "low"


def test_signature_call_rejects_non_json():
    import forge_dspy_router as r
    fake_text = json.dumps({"text": "no json here just prose"})
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps({
        "result": {"content": [{"text": fake_text}]}
    }).encode()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        out = r.signature_call(
            "CodePatchProposal", {"goal": "x", "file_context": "y", "constraints": "z"},
            "groq", "tok")
    assert out["ok"] is False
    assert "no JSON" in out["error"]
