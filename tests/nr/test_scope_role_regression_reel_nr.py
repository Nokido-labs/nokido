"""NR -- regression 2026-10-24 : le scope de role masquait des outils utilises.

Passe par le VRAI `ToolRegistry.get_tool_list` (agent CLAUDE), pas seulement par
les fonctions pures de forge_tool_scope.
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

UTILISES = {"nokido_ensure_service", "manage_forge_lifecycle", "web_search"}


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "_STATE", tmp_path / "tool_scope.json")
    monkeypatch.setattr(ts, "_USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(ts, "_specialites_for",
                        lambda a: "architecture,adr" if str(a).upper() == "CLAUDE" else None)
    monkeypatch.delenv("LAFORGE_TOOLS_LIST_ROLESCOPE", raising=False)
    ts._reset()
    yield ToolRegistry()
    ts._reset()


def _noms(reg):
    return {t["name"] for t in reg.get_tool_list(ring=1, agent="CLAUDE")}


def _snapshot(usage):
    ts._USAGE_FILE.write_text(json.dumps({"min_calls": 3, "usage": usage}), encoding="utf-8")
    ts._reset()


def test_sans_snapshot_d_usage_defaut_desarme_liste_pleine(reg):
    assert not ts.rolescope_enabled()
    assert UTILISES <= _noms(reg)


def test_avec_audit_les_outils_utilises_restent_visibles(reg):
    _snapshot({"CLAUDE": {"nokido_ensure_service": 89, "manage_forge_lifecycle": 76,
                          "web_search": 16, "memory": 1}})
    noms = _noms(reg)
    assert UTILISES <= noms
    assert "forge_deep_explore" in noms
    assert "memory" not in noms


def test_echappatoire_rend_vraiment_la_liste_pleine(reg):
    _snapshot({"CLAUDE": {}})
    assert "web_search" not in _noms(reg)
    ts.set_scope("CLAUDE", "all")
    noms = _noms(reg)
    assert UTILISES <= noms and {"memory", "github", "crawl"} <= noms


def test_desarmement_explicite_liste_pleine(reg, monkeypatch):
    _snapshot({"CLAUDE": {}})
    monkeypatch.setenv("LAFORGE_TOOLS_LIST_ROLESCOPE", "0")
    assert UTILISES <= _noms(reg)
