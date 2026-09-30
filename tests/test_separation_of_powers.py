# -*- coding: utf-8 -*-
"""Unit tests for the separation of powers alignment invariant."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from forge_separation import enforce_separation

def test_validation_separation():
    # 1. Agent X trying to validate task produced by X -> deny
    task_by_x = {"to_agent": "CLAUDE", "from_agent": "GEMINI"}
    ok, reason = enforce_separation(actor_agent="CLAUDE", action="validate_task", target=task_by_x)
    assert not ok
    assert "cannot validate or review its own task" in reason
    
    # 2. Agent Y trying to validate task produced by X -> ok
    ok, reason = enforce_separation(actor_agent="GEMINI", action="validate_task", target=task_by_x)
    assert ok
    assert reason == ""

def test_task_result_separation():
    # 1. Creator = worker -> deny result submission
    task_self = {"from_agent": "CLAUDE", "to_agent": "CLAUDE"}
    ok, reason = enforce_separation(actor_agent="CLAUDE", action="task.result", target=task_self)
    assert not ok
    assert "Creator/Validator" in reason and "cannot be the same as worker" in reason
    
    # 2. Creator != worker -> ok
    task_ok = {"from_agent": "GEMINI", "to_agent": "CLAUDE"}
    ok, reason = enforce_separation(actor_agent="CLAUDE", action="task.result", target=task_ok)
    assert ok

def test_judge_edit_protection():
    # 1. Standard agent (ring > 0) trying to edit judge module -> deny
    mock_ident = {"ring": 2, "agent": "CLAUDE"}
    with patch("forge_videur.resolve_identity", return_value=mock_ident):
        ok, reason = enforce_separation(
            actor_agent="CLAUDE",
            action="governed_edit",
            target="app/forge_trust_score.py"
        )
        assert not ok
        assert "forbidden from editing judge module" in reason
        
    # 2. Standard agent (ring > 0) trying to edit normal module -> ok
    with patch("forge_videur.resolve_identity", return_value=mock_ident):
        ok, reason = enforce_separation(
            actor_agent="CLAUDE",
            action="governed_edit",
            target="app/forge_active_inference.py"
        )
        assert ok
        
    # 3. System agent (ring 0) trying to edit judge module -> ok
    mock_sys_ident = {"ring": 0, "agent": "SYSTEM"}
    with patch("forge_videur.resolve_identity", return_value=mock_sys_ident):
        ok, reason = enforce_separation(
            actor_agent="SYSTEM",
            action="governed_edit",
        target="app/forge_trust_score.py"
        )
        assert ok


@pytest.mark.asyncio
async def test_registry_integration_governed_edit():
    from pathlib import Path
    from app.forge_mcp_registry import ToolRegistry
    
    with patch("forge_separation.enforce_separation", return_value=(False, "mocked violation")):
        class MockRegistry:
            root = Path("%NOKIDO_WORKSPACE%/LaForge")
            
        reg = MockRegistry()
        res = await ToolRegistry.handle_governed_edit(reg, {"path": "app/forge_trust_score.py", "content": "test"}, "CLAUDE", 2)
        assert "Separation of powers violation" in res


@pytest.mark.asyncio
async def test_registry_integration_task_result():
    from pathlib import Path
    from app.forge_mcp_registry import ToolRegistry
    
    with patch("forge_separation.enforce_separation", return_value=(False, "mocked task violation")):
        class MockRegistry:
            root = Path("%NOKIDO_WORKSPACE%/LaForge")
            
        reg = MockRegistry()
        res = await ToolRegistry.handle_task_result(reg, {"task_id": "test_tid"}, "CLAUDE", 2)
        assert "Separation of powers violation" in res

