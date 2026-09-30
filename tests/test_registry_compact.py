# -*- coding: utf-8 -*-
"""Tests Sprint 1 anti context-bomb : mode compact du catalogue tools/list.

Le mode compact est une VUE negociee par client (env LAFORGE_TOOLS_COMPACT =
"*" ou CSV d'agents, ou marqueur sandbox/tools_compact.txt) — les descriptions
CANONIQUES du registry ne sont jamais modifiees.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from forge_mcp_registry import ToolRegistry  # noqa: E402


def _reg():
    # Pas d'__init__ : on teste la vue catalogue, pas la DB/l'etat.
    return ToolRegistry.__new__(ToolRegistry)


def _synth():
    return [{
        "name": "demo",
        "description": ("Fait une chose precise. Deuxieme phrase tres verbeuse qui "
                        "detaille l'implementation interne sur des lignes entieres. "
                        "action=alpha|beta|gamma requis."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["alpha", "beta", "gamma"],
                           "description": "x" * 200},
                "explanation": {"type": "string", "description": "y" * 150},
            },
            "required": ["action"],
        },
    }]


def test_compact_transform_telegraphique():
    out = _reg()._compact_tools(_synth())
    t = out[0]
    assert t["description"].startswith("Fait une chose precise.")
    assert "action=alpha|beta|gamma" in t["description"]
    assert "implementation" not in t["description"]
    assert len(t["description"]) <= 200
    props = t["inputSchema"]["properties"]
    assert props["action"]["enum"] == ["alpha", "beta", "gamma"]
    assert t["inputSchema"]["required"] == ["action"]
    assert len(props["action"]["description"]) <= 81
    assert len(props["explanation"]["description"]) < 100


def test_compact_ne_mute_pas_le_canonique():
    synth = _synth()
    before_prop = synth[0]["inputSchema"]["properties"]["action"]["description"]
    _reg()._compact_tools(synth)
    assert synth[0]["inputSchema"]["properties"]["action"]["description"] == before_prop
    assert "Deuxieme phrase" in synth[0]["description"]


def test_negociation_par_agent(monkeypatch):
    reg = _reg()
    monkeypatch.delenv("LAFORGE_TOOLS_COMPACT", raising=False)
    full = reg.get_tool_list(ring=1, agent="CLAUDE")
    assert any(len(t.get("description") or "") > 200 for t in full)

    monkeypatch.setenv("LAFORGE_TOOLS_COMPACT", "claude")
    compact = reg.get_tool_list(ring=1, agent="CLAUDE")
    # La visibilite (quels tools) ne change pas — seule la verbosite change.
    assert {t["name"] for t in compact} == {t["name"] for t in full}
    assert all(len(t.get("description") or "") <= 200 for t in compact)

    # Agent non listee -> vue canonique intacte.
    other = reg.get_tool_list(ring=1, agent="GEMINI")
    assert any(len(t.get("description") or "") > 200 for t in other)


def test_negociation_wildcard(monkeypatch):
    reg = _reg()
    monkeypatch.setenv("LAFORGE_TOOLS_COMPACT", "*")
    compact = reg.get_tool_list(ring=1, agent="N_IMPORTE_QUI")
    assert compact and all(len(t.get("description") or "") <= 200 for t in compact)
