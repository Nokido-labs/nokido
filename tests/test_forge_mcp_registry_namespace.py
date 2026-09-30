"""Tests for the v3.1 namespace + explanation refactor of forge_mcp_registry.

Pattern inspire de Cursor / Augment / Devin / Claude Code 2.0 (ai_prompts_landscape).

Couvre :
  - resolve_tool_name : alias canonique / legacy prefixe / identite / inconnu
  - enforce_explanation : warn vs error, presence/absence du champ
  - dispatch : un appel `forge_read` arrive bien au handler `handle_read`
  - _all_tools : le champ `explanation` est present dans tous les inputSchema
"""
from __future__ import annotations

import asyncio
import logging
import os

import pytest

# `conftest.py` ajoute deja LaForge/app dans sys.path.
from forge_mcp_registry import (  # type: ignore[import-not-found]
    ToolRegistry,
    _NAMESPACE_ALIASES,
    enforce_explanation,
    resolve_tool_name,
)


# ────────────────────────────── resolve_tool_name ─────────────────────────────


def test_resolve_alias_legacy_prefix():
    """Forme historique `forge_<x>` est resolue vers le nom court."""
    assert resolve_tool_name("forge_read") == "read"
    assert resolve_tool_name("forge_rag") == "rag"
    assert resolve_tool_name("forge_run") == "run"


def test_resolve_alias_canonical_namespace():
    """Forme canonique `forge.{cat}.{tool}` est resolue vers le nom court."""
    assert resolve_tool_name("forge.code.read") == "read"
    assert resolve_tool_name("forge.rag.rag") == "rag"
    assert resolve_tool_name("forge.graph.ppr") == "graph_ppr"
    assert resolve_tool_name("forge.net.netcfg") == "netcfg"


def test_resolve_passthrough_short_name():
    """Le nom interne court est retourne tel quel."""
    assert resolve_tool_name("read") == "read"
    assert resolve_tool_name("graph_ppr") == "graph_ppr"


def test_resolve_passthrough_unknown():
    """Un nom inconnu est laisse intact (pas d'exception, no-op)."""
    assert resolve_tool_name("inconnu") == "inconnu"
    assert resolve_tool_name("forge.nope.xxx") == "forge.nope.xxx"


def test_resolve_non_string_safe():
    """Type non-string : retour identique sans crash."""
    assert resolve_tool_name(None) is None  # type: ignore[arg-type]
    assert resolve_tool_name(42) == 42      # type: ignore[arg-type]


def test_aliases_target_only_short_names():
    """Chaque alias pointe vers un nom court (pas vers une autre forme alias),
    et toutes les cibles sont distinctes des sources => pas de cycle.
    """
    from forge_mcp_registry import ToolRegistry

    # INSTANCE, pas la classe : certains handlers (graph_*) sont attaches au montage, et
    # `dispatch` teste `hasattr(self, "handle_<nom>")` -- meme chemin que lui.
    reg = ToolRegistry()
    for src, dst in _NAMESPACE_ALIASES.items():
        # cibles ne doivent JAMAIS contenir un point (= namespace canonique)
        assert "." not in dst, f"alias {src!r} pointe vers {dst!r} (namespace, pas court)"
        # ... et doivent etre un POINT FIXE de la resolution : `resolve_tool_name` ne fait
        # qu'un saut, une chaine a->b->c laisserait `b` au dispatch. L'identite
        # (`query_json` -> `query_json`) est un point fixe, donc admise.
        assert _NAMESPACE_ALIASES.get(dst, dst) == dst, (
            f"alias {src!r} -> {dst!r} -> {_NAMESPACE_ALIASES[dst]!r} (chaine)")
        # Un prefixe `forge_` n'est plus a lui seul un alias legacy : `forge_stats` (2026-06-04)
        # est un nom CANONIQUE. L'interdit reel est une cible MORTE : sans handler ni route,
        # dispatch rendrait « Outil inconnu ». Mesure 2026-09-27 : 0 sur 125.
        assert (hasattr(reg, "handle_" + dst)
                or dst.startswith(("netcfg_", "docker_", "dyn_"))), (
            f"alias {src!r} pointe vers {dst!r} : ni handler ni route (cible morte)")


# ────────────────────────────── enforce_explanation ───────────────────────────


def test_enforce_warn_missing_field(caplog):
    """Mode warn : champ absent emet un warning, sans exception."""
    caplog.set_level(logging.WARNING, logger="Nokido.MCP.Registry")
    enforce_explanation({"name": "read", "arguments": {"path": "/x"}}, mode="warn")
    assert any("explanation-missing" in r.message for r in caplog.records)


def test_enforce_warn_present_field_silent(caplog):
    """Mode warn : champ present => aucun warning emis."""
    caplog.set_level(logging.WARNING, logger="Nokido.MCP.Registry")
    enforce_explanation(
        {"name": "read", "arguments": {"path": "/x", "explanation": "why"}},
        mode="warn",
    )
    assert not any("explanation-missing" in r.message for r in caplog.records)


def test_enforce_error_missing_raises():
    """Mode error : champ absent => ValueError."""
    with pytest.raises(ValueError, match="explanation-missing"):
        enforce_explanation({"name": "read", "arguments": {"path": "/x"}}, mode="error")


def test_enforce_error_present_ok():
    """Mode error : champ present => silencieux, pas d'exception."""
    enforce_explanation(
        {"name": "read", "arguments": {"path": "/x", "explanation": "why"}},
        mode="error",
    )


def test_enforce_env_override(monkeypatch):
    """LAFORGE_EXPLANATION_MODE=error override l'argument mode=warn."""
    monkeypatch.setenv("LAFORGE_EXPLANATION_MODE", "error")
    with pytest.raises(ValueError):
        enforce_explanation({"name": "X", "arguments": {}}, mode="warn")


def test_enforce_empty_string_field_treated_missing():
    """Un champ explanation vide (whitespace) compte comme absent."""
    with pytest.raises(ValueError):
        enforce_explanation(
            {"name": "X", "arguments": {"explanation": "   "}},
            mode="error",
        )


def test_enforce_flat_args_form():
    """Forme `args directs` (sans wrapper {name, arguments}) marche aussi."""
    # ici on passe `arguments` au top-level
    enforce_explanation({"explanation": "ok"}, mode="error")  # no raise


# ──────────────────────────────── _all_tools ──────────────────────────────────


def test_all_tools_have_explanation_in_schema():
    """Chaque tool expose `explanation` dans inputSchema.properties."""
    reg = ToolRegistry()
    tools = reg._all_tools()
    assert tools, "_all_tools() ne doit pas etre vide"
    for t in tools:
        schema = t.get("inputSchema") or {}
        props = schema.get("properties") or {}
        assert "explanation" in props, f"tool {t.get('name')!r} sans explanation"
        assert props["explanation"]["type"] == "string"


def test_all_tools_explanation_not_required():
    """`explanation` ne doit PAS etre dans `required` (mode warn, soft)."""
    reg = ToolRegistry()
    for t in reg._all_tools():
        req = (t.get("inputSchema") or {}).get("required") or []
        assert "explanation" not in req, (
            f"tool {t.get('name')!r} : explanation est required, attendu optionnel"
        )


# ───────────────────────────── dispatch (alias->handler) ──────────────────────


class _DummyRegistry(ToolRegistry):
    """ToolRegistry sandbox : remplace les handlers reels par des trackers
    pour eviter tout effet de bord (DB, FS, evenements)."""

    def __init__(self):
        super().__init__()
        self.calls: list = []

        async def _track(args, agent, ring):
            self.calls.append({"args": args, "agent": agent, "ring": ring})
            return "TRACKED_OK"

        # remplace les handlers sensibles
        self.handle_read = _track  # type: ignore[method-assign]
        self.handle_rag = _track   # type: ignore[method-assign]

        # neutralise event bus / access switches via attribut bidon
        self._event_bus = type("NoBus", (), {"publish": lambda *a, **k: None})()

    def _get_ring_needed(self, name, args):
        return 4  # autorise tout


def test_dispatch_alias_canonical_routes_to_handler():
    """Appel via forme canonique `forge.code.read` arrive a handle_read."""
    reg = _DummyRegistry()
    res = asyncio.run(
        reg.dispatch(
            "forge.code.read",
            {"path": "/tmp/x", "explanation": "test"},
            agent="TEST",
            ring=0,
        )
    )
    assert res == "TRACKED_OK"
    assert len(reg.calls) == 1
    assert reg.calls[0]["args"]["path"] == "/tmp/x"


def test_dispatch_alias_legacy_prefix_routes_to_handler():
    """Appel via forme historique `forge_rag` arrive a handle_rag."""
    reg = _DummyRegistry()
    res = asyncio.run(
        reg.dispatch(
            "forge_rag",
            {"action": "search", "topic": "x", "explanation": "test"},
            agent="TEST",
            ring=0,
        )
    )
    assert res == "TRACKED_OK"
    assert len(reg.calls) == 1


def test_dispatch_short_name_still_works():
    """Backward-compat absolu : les noms cours `read` / `rag` marchent."""
    reg = _DummyRegistry()
    res = asyncio.run(
        reg.dispatch(
            "read",
            {"path": "/tmp/y", "explanation": "test"},
            agent="TEST",
            ring=0,
        )
    )
    assert res == "TRACKED_OK"
