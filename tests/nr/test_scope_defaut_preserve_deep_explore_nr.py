"""NR -- le scope par defaut ne doit pas masquer forge_deep_explore (regression e9707fb40).

Chemin reel : ToolRegistry.get_tool_list, role sans usage releve (ex. GEMINI).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_tool_scope as ts  # noqa: E402
from nokido_agent.app.forge_mcp_registry import ToolRegistry  # noqa: E402

RETABLIS = {"forge_deep_explore"}


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "_STATE", tmp_path / "tool_scope.json")
    monkeypatch.setattr(ts, "_USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(ts, "_specialites_for", lambda a: "architecture,adr")
    monkeypatch.delenv("LAFORGE_TOOLS_LIST_ROLESCOPE", raising=False)
    ts._USAGE_FILE.write_text(json.dumps({"min_calls": 3, "usage": {"X": {}}}), encoding="utf-8")
    ts._reset()
    yield ToolRegistry()
    ts._reset()


def test_deep_explore_visible_sans_usage(reg):
    noms = {t["name"] for t in reg.get_tool_list(ring=1, agent="GEMINI")}
    assert RETABLIS <= noms


def test_deep_explore_dans_core():
    assert RETABLIS <= ts.CORE_TOOLS
