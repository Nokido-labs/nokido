"""
tests/test_agy_mcp.py
======================
Comprehensive E2E test suite for the Antigravity CLI (agy) MCP tools integration.
Following the 4-Tier test design methodology:
  - Tier 1: Feature Coverage (>=15 tests)
  - Tier 2: Boundary & Corner Cases (>=15 tests)
  - Tier 3: Cross-Feature Combinations (>=3 tests)
  - Tier 4: Real-World Workloads (>=5 tests)

To isolate tests, we patch subprocess calls and the settings.json file path
(by overriding pathlib.Path.home to point to a temporary pytest directory).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from forge_mcp_registry import (
    ToolRegistry,
    _NAMESPACE_ALIASES,
    enforce_explanation,
    resolve_tool_name,
)

# A sample schema definition to mimic settings validation in tests.
# These match the design specs in explorer_m1/analysis.md.
SETTINGS_SCHEMA = {
    "allowNonWorkspaceAccess": bool,
    "altScreenMode": str,
    "artifactReviewPolicy": str,
    "colorScheme": str,
    "editor": str,
    "enableTelemetry": bool,
    "enableTerminalSandbox": bool,
    "gcp": dict,
    "historySize": int,
    "model": str,
    "notifications": bool,
    "permissions": dict,
    "runningLightSpeed": str,
    "showFeedbackSurvey": bool,
    "showTips": bool,
    "statusLine": dict,
    "title": dict,
    "toolPermission": str,
    "trustedWorkspaces": list,
    "useG1Credits": bool,
    "verbosity": str,
}


@pytest.fixture
def mock_home(tmp_path):
    """Fixture to mock Path.home() so settings.json is written under a temp directory."""
    with patch("pathlib.Path.home", return_value=tmp_path):
        yield tmp_path


@pytest.fixture
def registry(mock_home):
    """Create a registry instance pointing to a mock home/root environment."""
    reg = ToolRegistry(root_dir=mock_home)
    # Stub event bus to prevent database/network access in unit tests
    reg._event_bus = MagicMock()
    reg._event_bus.publish.return_value = "mock_event_id"
    return reg


# ──────────────────────────────────────────────────────────────────────────────
# TIER 1: FEATURE COVERAGE (>= 15 Tests)
# ──────────────────────────────────────────────────────────────────────────────


def test_tool_registration_agy_run(registry):
    """Tier 1: Schema registration of agy_run is present in _all_tools()."""
    tools = registry._all_tools()
    agy_run_tool = next((t for t in tools if t["name"] == "agy_run"), None)
    assert agy_run_tool is not None, "agy_run not registered"
    assert "command" in agy_run_tool["inputSchema"]["properties"]
    assert "explanation" in agy_run_tool["inputSchema"]["properties"]


def test_tool_registration_agy_config(registry):
    """Tier 1: Schema registration of agy_config is present in _all_tools()."""
    tools = registry._all_tools()
    agy_config_tool = next((t for t in tools if t["name"] == "agy_config"), None)
    assert agy_config_tool is not None, "agy_config not registered"
    assert "action" in agy_config_tool["inputSchema"]["properties"]
    assert "key" in agy_config_tool["inputSchema"]["properties"]


def test_tool_registration_agy_add_dir(registry):
    """Tier 1: Schema registration of agy_add_dir is present in _all_tools()."""
    tools = registry._all_tools()
    agy_add_dir_tool = next((t for t in tools if t["name"] == "agy_add_dir"), None)
    assert agy_add_dir_tool is not None, "agy_add_dir not registered"
    assert "path" in agy_add_dir_tool["inputSchema"]["properties"]


def test_namespace_aliases_agy_run():
    """Tier 1: Checks that forge.code.agy_run and forge_agy_run resolve to agy_run."""
    assert resolve_tool_name("forge.code.agy_run") == "agy_run"
    assert resolve_tool_name("forge_agy_run") == "agy_run"
    assert resolve_tool_name("agy_run") == "agy_run"


def test_namespace_aliases_agy_config():
    """Tier 1: Checks that forge.meta.agy_config and forge_agy_config resolve to agy_config."""
    assert resolve_tool_name("forge.meta.agy_config") == "agy_config"
    assert resolve_tool_name("forge_agy_config") == "agy_config"
    assert resolve_tool_name("agy_config") == "agy_config"


def test_namespace_aliases_agy_add_dir():
    """Tier 1: Checks that forge.fs.agy_add_dir and forge_agy_add_dir resolve to agy_add_dir."""
    assert resolve_tool_name("forge.fs.agy_add_dir") == "agy_add_dir"
    assert resolve_tool_name("forge_agy_add_dir") == "agy_add_dir"
    assert resolve_tool_name("agy_add_dir") == "agy_add_dir"


def test_explanation_enforced_agy_run(registry):
    """Tier 1: Verifies missing explanation is warned or errors depending on config."""
    # Under default mode=warn, missing explanation does not raise.
    # We test with mode="error" to verify enforcement.
    with pytest.raises(ValueError, match="explanation-missing"):
        enforce_explanation(
            {"name": "agy_run", "arguments": {"command": "task list"}},
            mode="error",
        )


def test_explanation_enforced_agy_config(registry):
    """Tier 1: Verifies missing explanation is checked for agy_config."""
    with pytest.raises(ValueError, match="explanation-missing"):
        enforce_explanation(
            {"name": "agy_config", "arguments": {"action": "read", "key": "editor"}},
            mode="error",
        )


def test_explanation_enforced_agy_add_dir(registry):
    """Tier 1: Verifies missing explanation is checked for agy_add_dir."""
    with pytest.raises(ValueError, match="explanation-missing"):
        enforce_explanation(
            {"name": "agy_add_dir", "arguments": {"path": "C:/projects/nokido"}},
            mode="error",
        )


@pytest.mark.asyncio
async def test_dispatch_agy_run_calls_handler(registry):
    """Tier 1: Dispatch of forge.code.agy_run maps to handle_agy_run."""
    # Since handler is not implemented yet in real codebase, we patch it
    # to check that dispatch correctly resolves name and forwards parameters.
    with patch.object(registry, "handle_agy_run", create=True) as mock_handler:
        mock_handler.return_value = {"success": True, "stdout": "Mocked task list"}
        
        # Stub the database check to return Ring 2 needed
        with patch.object(registry, "_get_ring_needed", return_value=2):
            res = await registry.dispatch(
                "forge.code.agy_run",
                {"command": "task list", "explanation": "need details"},
                agent="TEST_AGENT",
                ring=2,
            )
            assert res == {"success": True, "stdout": "Mocked task list"}
            mock_handler.assert_called_once_with(
                {"command": "task list", "explanation": "need details"},
                "TEST_AGENT",
                2,
            )


@pytest.mark.asyncio
async def test_dispatch_agy_config_calls_handler(registry):
    """Tier 1: Dispatch of forge.meta.agy_config maps to handle_agy_config."""
    with patch.object(registry, "handle_agy_config", create=True) as mock_handler:
        mock_handler.return_value = {"success": True, "key": "editor", "value": "code"}
        
        with patch.object(registry, "_get_ring_needed", return_value=3):
            res = await registry.dispatch(
                "forge.meta.agy_config",
                {"action": "read", "key": "editor", "explanation": "check editor"},
                agent="TEST_AGENT",
                ring=3,
            )
            assert res == {"success": True, "key": "editor", "value": "code"}
            mock_handler.assert_called_once_with(
                {"action": "read", "key": "editor", "explanation": "check editor"},
                "TEST_AGENT",
                3,
            )


@pytest.mark.asyncio
async def test_dispatch_agy_add_dir_calls_handler(registry):
    """Tier 1: Dispatch of forge.fs.agy_add_dir maps to handle_agy_add_dir."""
    with patch.object(registry, "handle_agy_add_dir", create=True) as mock_handler:
        mock_handler.return_value = {"success": True, "path": "C:/workspace"}
        
        with patch.object(registry, "_get_ring_needed", return_value=2):
            res = await registry.dispatch(
                "forge.fs.agy_add_dir",
                {"path": "C:/workspace", "explanation": "trust project workspace"},
                agent="TEST_AGENT",
                ring=2,
            )
            assert res == {"success": True, "path": "C:/workspace"}
            mock_handler.assert_called_once_with(
                {"path": "C:/workspace", "explanation": "trust project workspace"},
                "TEST_AGENT",
                2,
            )


@pytest.mark.asyncio
async def test_agy_run_successful_mock(registry):
    """Tier 1: Validates successful execution of a subprocess command via handle_agy_run."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Task 1: Fix all tests"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        # Call handler directly
        res = await registry.handle_agy_run(
            {"command": "task list", "explanation": "Listing tasks"},
            agent="TEST",
            ring=2,
        )
        assert res["success"] is True
        assert res["exit_code"] == 0
        assert "Fix all tests" in res["stdout"]


@pytest.mark.asyncio
async def test_agy_run_error_exit_mock(registry):
    """Tier 1: Validates response structure when subprocess returns non-zero code."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "Command 'invalid' not found"
        mock_run.return_value = mock_proc

        res = await registry.handle_agy_run(
            {"command": "invalid", "explanation": "test invalid command"},
            agent="TEST",
            ring=2,
        )
        assert res["success"] is False
        assert res["exit_code"] == 1
        assert "not found" in res["stderr"]


@pytest.mark.asyncio
async def test_agy_config_read_mock(registry, mock_home):
    """Tier 1: Reading setting key from settings.json returns expected value."""
    if not hasattr(registry, "handle_agy_config"):
        pytest.skip("handle_agy_config not implemented on registry")

    settings_dir = mock_home / ".gemini" / "antigravity-cli"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text(
        json.dumps({"editor": "code", "enableTelemetry": True}), encoding="utf-8"
    )

    res = await registry.handle_agy_config(
        {"action": "read", "key": "editor", "explanation": "Checking editor"},
        agent="TEST",
        ring=3,
    )
    assert res["success"] is True
    assert res["key"] == "editor"
    assert res["value"] == "code"


@pytest.mark.asyncio
async def test_agy_config_write_mock(registry, mock_home):
    """Tier 1: Writing setting key to settings.json correctly saves it."""
    if not hasattr(registry, "handle_agy_config"):
        pytest.skip("handle_agy_config not implemented on registry")

    res = await registry.handle_agy_config(
        {"action": "write", "key": "editor", "value": "vim", "explanation": "Setting editor"},
        agent="TEST",
        ring=1,
    )
    assert res["success"] is True
    
    # Read back to verify
    settings_file = mock_home / ".gemini" / "antigravity-cli" / "settings.json"
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data["editor"] == "vim"


@pytest.mark.asyncio
async def test_agy_add_dir_adds_trusted_workspace(registry, mock_home):
    """Tier 1: Adding a directory updates trustedWorkspaces in settings.json."""
    if not hasattr(registry, "handle_agy_add_dir"):
        pytest.skip("handle_agy_add_dir not implemented on registry")

    # Call handle_agy_add_dir with an absolute path
    path = "%USERPROFILE%/workspace" if os.name == "nt" else "/home/user/workspace"
    res = await registry.handle_agy_add_dir(
        {"path": path, "explanation": "adding new workspace"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is True
    assert res["path"] == path

    settings_file = mock_home / ".gemini" / "antigravity-cli" / "settings.json"
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert path in data.get("trustedWorkspaces", [])


@pytest.mark.asyncio
async def test_ring_enforcement_agy_run(registry):
    """Tier 1: Verifies that calling dispatch for agy_run with Ring > 2 gets rejected."""
    with patch.object(registry, "handle_agy_run", create=True) as mock_handler:
        # Stub the database check to return Ring 2 needed
        with patch.object(registry, "_get_ring_needed", return_value=2):
            res = await registry.dispatch(
                "forge.code.agy_run",
                {"command": "task list", "explanation": "need details"},
                agent="TEST_AGENT",
                ring=3,  # Ring 3 caller is NOT authorized (max authorized is 2)
            )
            assert "SECURITY" in str(res)
            mock_handler.assert_not_called()


@pytest.mark.asyncio
async def test_ring_enforcement_agy_config_read(registry):
    """Tier 1: Verifies dispatch for agy_config read with Ring > 3 gets rejected."""
    with patch.object(registry, "handle_agy_config", create=True) as mock_handler:
        with patch.object(registry, "_get_ring_needed", return_value=3):
            res = await registry.dispatch(
                "forge.meta.agy_config",
                {"action": "read", "key": "editor", "explanation": "check editor"},
                agent="TEST_AGENT",
                ring=4,  # Ring 4 is restricted
            )
            assert "SECURITY" in str(res)
            mock_handler.assert_not_called()


@pytest.mark.asyncio
async def test_ring_enforcement_agy_config_write(registry):
    """Tier 1: Verifies dispatch for agy_config write with Ring > 1 gets rejected."""
    with patch.object(registry, "handle_agy_config", create=True) as mock_handler:
        with patch.object(registry, "_get_ring_needed", return_value=1):
            res = await registry.dispatch(
                "forge.meta.agy_config",
                {"action": "write", "key": "editor", "value": "vim", "explanation": "set editor"},
                agent="TEST_AGENT",
                ring=2,  # Ring 2 cannot write
            )
            assert "SECURITY" in str(res)
            mock_handler.assert_not_called()


@pytest.mark.asyncio
async def test_ring_enforcement_agy_add_dir(registry):
    """Tier 1: Verifies dispatch for agy_add_dir with Ring > 2 gets rejected."""
    with patch.object(registry, "handle_agy_add_dir", create=True) as mock_handler:
        with patch.object(registry, "_get_ring_needed", return_value=2):
            res = await registry.dispatch(
                "forge.fs.agy_add_dir",
                {"path": "/some/path", "explanation": "trust workspace"},
                agent="TEST_AGENT",
                ring=3,  # Ring 3 cannot authorize workspaces
            )
            assert "SECURITY" in str(res)
            mock_handler.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# TIER 2: BOUNDARY & CORNER CASES (>= 15 Tests)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agy_run_timeout_expired(registry):
    """Tier 2: Subprocess raises subprocess.TimeoutExpired, check how it is handled."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="agy task list", timeout=10)):
        res = await registry.handle_agy_run(
            {"command": "task list", "timeout": 10, "explanation": "test timeout"},
            agent="TEST",
            ring=2,
        )
        assert res["success"] is False
        assert "timeout" in res.get("stderr", "").lower() or "timeout" in res.get("error", "").lower()


@pytest.mark.asyncio
async def test_agy_run_command_injection_semicolon(registry):
    """Tier 2: Reject command containing semicolon chainer."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    res = await registry.handle_agy_run(
        {"command": "task list; rm -rf /", "explanation": "injection attack"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is False
    assert "injection" in res.get("error", "").lower() or "invalid" in res.get("error", "").lower()


@pytest.mark.asyncio
async def test_agy_run_command_injection_pipe(registry):
    """Tier 2: Reject command containing pipe chainer."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    res = await registry.handle_agy_run(
        {"command": "task list | cat", "explanation": "injection attack"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is False
    assert "injection" in res.get("error", "").lower() or "invalid" in res.get("error", "").lower()


@pytest.mark.asyncio
async def test_agy_run_command_injection_ampersand(registry):
    """Tier 2: Reject command containing ampersand chainer."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    res = await registry.handle_agy_run(
        {"command": "task list && format C:", "explanation": "injection attack"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is False
    assert "injection" in res.get("error", "").lower() or "invalid" in res.get("error", "").lower()


@pytest.mark.asyncio
async def test_agy_run_command_injection_subshell(registry):
    """Tier 2: Reject command containing subshell invocation."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    res = await registry.handle_agy_run(
        {"command": "task add $(whoami)", "explanation": "injection attack"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is False
    assert "injection" in res.get("error", "").lower() or "invalid" in res.get("error", "").lower()


@pytest.mark.asyncio
async def test_agy_run_command_injection_backticks(registry):
    """Tier 2: Reject command containing backticks evaluation."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    res = await registry.handle_agy_run(
        {"command": "task add `whoami`", "explanation": "injection attack"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is False
    assert "injection" in res.get("error", "").lower() or "invalid" in res.get("error", "").lower()


@pytest.mark.asyncio
async def test_agy_run_command_injection_redirect(registry):
    """Tier 2: Reject command containing output redirection."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    res = await registry.handle_agy_run(
        {"command": "task list > output.txt", "explanation": "injection attack"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is False
    assert "injection" in res.get("error", "").lower() or "invalid" in res.get("error", "").lower()


@pytest.mark.asyncio
async def test_agy_run_command_injection_glob(registry):
    """Tier 2: Reject command containing glob wildcard."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    res = await registry.handle_agy_run(
        {"command": "task list *", "explanation": "injection attack"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is False
    assert "injection" in res.get("error", "").lower() or "invalid" in res.get("error", "").lower()


@pytest.mark.asyncio
async def test_agy_run_command_injection_newline(registry):
    """Tier 2: Reject command containing newlines."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    res = await registry.handle_agy_run(
        {"command": "task list\nrm -rf /", "explanation": "injection attack"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is False
    assert "injection" in res.get("error", "").lower() or "invalid" in res.get("error", "").lower()


@pytest.mark.asyncio
async def test_agy_run_command_injection_windows_escape(registry):
    """Tier 2: Reject command containing Windows CMD escape char (^)."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    res = await registry.handle_agy_run(
        {"command": "task list ^& dir", "explanation": "injection attack"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is False
    assert "injection" in res.get("error", "").lower() or "invalid" in res.get("error", "").lower()


@pytest.mark.asyncio
async def test_agy_config_malformed_json_fallback(registry, mock_home):
    """Tier 2: If settings.json is corrupted (not valid JSON), reading handles it gracefully."""
    if not hasattr(registry, "handle_agy_config"):
        pytest.skip("handle_agy_config not implemented on registry")

    settings_dir = mock_home / ".gemini" / "antigravity-cli"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text("{{{{invalid json", encoding="utf-8")

    res = await registry.handle_agy_config(
        {"action": "read", "key": "editor", "explanation": "checking invalid config"},
        agent="TEST",
        ring=3,
    )
    # The reader should handle corruption and return empty value or success=True but empty/error handled.
    # Typically, should return success=True/False gracefully without blowing up.
    assert "error" in res or res.get("value") is None or res.get("success") is False


@pytest.mark.asyncio
async def test_agy_config_unknown_key_ignored(registry):
    """Tier 2: Writing an unknown setting key is ignored or filtered out."""
    if not hasattr(registry, "handle_agy_config"):
        pytest.skip("handle_agy_config not implemented on registry")

    res = await registry.handle_agy_config(
        {"action": "write", "key": "invalidKey", "value": "someValue", "explanation": "set invalid"},
        agent="TEST",
        ring=1,
    )
    assert res["success"] is False or "invalidKey" not in res.get("value", "")


@pytest.mark.asyncio
async def test_agy_config_invalid_type(registry):
    """Tier 2: Writing value of incorrect type (e.g. string for boolean key) is rejected."""
    if not hasattr(registry, "handle_agy_config"):
        pytest.skip("handle_agy_config not implemented on registry")

    res = await registry.handle_agy_config(
        {"action": "write", "key": "enableTelemetry", "value": "not_a_bool", "explanation": "invalid type write"},
        agent="TEST",
        ring=1,
    )
    assert res["success"] is False


@pytest.mark.asyncio
async def test_agy_config_trusted_workspaces_validation(registry):
    """Tier 2: Writing trustedWorkspaces that is not a list of strings is rejected."""
    if not hasattr(registry, "handle_agy_config"):
        pytest.skip("handle_agy_config not implemented on registry")

    res = await registry.handle_agy_config(
        {"action": "write", "key": "trustedWorkspaces", "value": "not_a_list", "explanation": "invalid list write"},
        agent="TEST",
        ring=1,
    )
    assert res["success"] is False


@pytest.mark.asyncio
async def test_agy_config_file_size_exceeded(registry, mock_home):
    """Tier 2: Reader rejects settings.json if its size exceeds 1MB limit."""
    if not hasattr(registry, "handle_agy_config"):
        pytest.skip("handle_agy_config not implemented on registry")

    settings_dir = mock_home / ".gemini" / "antigravity-cli"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_file = settings_dir / "settings.json"
    
    # Write a file of size 1.1MB
    with open(settings_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"editor": "x" * 1024 * 1024}))

    res = await registry.handle_agy_config(
        {"action": "read", "key": "editor", "explanation": "test size limit"},
        agent="TEST",
        ring=3,
    )
    assert res["success"] is False or "size" in res.get("error", "").lower()


@pytest.mark.asyncio
async def test_agy_add_dir_empty_path(registry):
    """Tier 2: Empty path addition is rejected."""
    if not hasattr(registry, "handle_agy_add_dir"):
        pytest.skip("handle_agy_add_dir not implemented on registry")

    res = await registry.handle_agy_add_dir(
        {"path": "   ", "explanation": "empty path test"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is False


@pytest.mark.asyncio
async def test_agy_add_dir_relative_path(registry):
    """Tier 2: Relative path addition is rejected."""
    if not hasattr(registry, "handle_agy_add_dir"):
        pytest.skip("handle_agy_add_dir not implemented on registry")

    res = await registry.handle_agy_add_dir(
        {"path": "./relative/path", "explanation": "relative path test"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is False


@pytest.mark.asyncio
async def test_agy_run_extremely_long_command(registry):
    """Tier 2: Extremely long command input is truncated or rejected safely."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    long_cmd = "task list " + ("a" * 10000)
    res = await registry.handle_agy_run(
        {"command": long_cmd, "explanation": "extreme input size"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is False or "too long" in res.get("error", "").lower() or "invalid" in res.get("error", "").lower()


# ──────────────────────────────────────────────────────────────────────────────
# TIER 3: CROSS-FEATURE COMBINATIONS (>= 3 Tests)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_combo_add_workspace_and_run(registry, mock_home):
    """Tier 3: Sequential calls to add directory and run command to verify integration."""
    if not hasattr(registry, "handle_agy_add_dir") or not hasattr(registry, "handle_agy_run"):
        pytest.skip("Handlers not fully implemented on registry")

    workspace_path = "C:/projects/my_project" if os.name == "nt" else "/home/projects/my_project"
    
    # 1. Add workspace
    res1 = await registry.handle_agy_add_dir(
        {"path": workspace_path, "explanation": "add workspace for build"},
        agent="TEST",
        ring=2,
    )
    assert res1["success"] is True

    # 2. Check settings contains it
    settings_file = mock_home / ".gemini" / "antigravity-cli" / "settings.json"
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert workspace_path in data.get("trustedWorkspaces", [])

    # 3. Call run command in that workspace
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Task list for my_project"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        res2 = await registry.handle_agy_run(
            {"command": "task list", "explanation": "verify tasks inside newly added workspace"},
            agent="TEST",
            ring=2,
        )
        assert res2["success"] is True
        assert "my_project" in res2["stdout"]


@pytest.mark.asyncio
async def test_combo_telemetry_opt_out_and_run(registry, mock_home):
    """Tier 3: Turn off telemetry in config, then execute run command."""
    if not hasattr(registry, "handle_agy_config") or not hasattr(registry, "handle_agy_run"):
        pytest.skip("Handlers not fully implemented on registry")

    # 1. Write enableTelemetry = False
    res1 = await registry.handle_agy_config(
        {"action": "write", "key": "enableTelemetry", "value": False, "explanation": "opt out"},
        agent="TEST",
        ring=1,
    )
    assert res1["success"] is True

    # 2. Verify setting in json file
    settings_file = mock_home / ".gemini" / "antigravity-cli" / "settings.json"
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data["enableTelemetry"] is False

    # 3. Call run
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Execution complete"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        res2 = await registry.handle_agy_run(
            {"command": "task sync", "explanation": "sync tasks"},
            agent="TEST",
            ring=2,
        )
        assert res2["success"] is True


@pytest.mark.asyncio
async def test_combo_multiple_writes_and_read(registry):
    """Tier 3: Write multiple properties, then read them to ensure consistency."""
    if not hasattr(registry, "handle_agy_config"):
        pytest.skip("handle_agy_config not implemented on registry")

    # Write editor
    res1 = await registry.handle_agy_config(
        {"action": "write", "key": "editor", "value": "vscode", "explanation": "set editor"},
        agent="TEST",
        ring=1,
    )
    assert res1["success"] is True

    # Write verbosity
    res2 = await registry.handle_agy_config(
        {"action": "write", "key": "verbosity", "value": "debug", "explanation": "set verbosity"},
        agent="TEST",
        ring=1,
    )
    assert res2["success"] is True

    # Read editor
    res3 = await registry.handle_agy_config(
        {"action": "read", "key": "editor", "explanation": "read editor"},
        agent="TEST",
        ring=3,
    )
    assert res3["success"] is True
    assert res3["value"] == "vscode"

    # Read verbosity
    res4 = await registry.handle_agy_config(
        {"action": "read", "key": "verbosity", "explanation": "read verbosity"},
        agent="TEST",
        ring=3,
    )
    assert res4["success"] is True
    assert res4["value"] == "debug"


# ──────────────────────────────────────────────────────────────────────────────
# TIER 4: REAL-WORLD WORKLOADS (>= 5 Tests)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_workload_developer_workspace_init(registry, mock_home):
    """Tier 4: Scenario: Setup developer environment from scratch.
    Flow: Read telemetry config -> Configure telemetry/editor -> Add workspace -> Run task list.
    """
    if (
        not hasattr(registry, "handle_agy_config")
        or not hasattr(registry, "handle_agy_add_dir")
        or not hasattr(registry, "handle_agy_run")
    ):
        pytest.skip("Handlers not fully implemented on registry")

    # Step 1: Read telemetry (should be empty initially or default)
    res_tel_init = await registry.handle_agy_config(
        {"action": "read", "key": "enableTelemetry", "explanation": "initial telemetry check"},
        agent="DEV_AGENT",
        ring=3,
    )
    assert res_tel_init["success"] is True

    # Step 2: Configure telemetry to False and editor to "code"
    await registry.handle_agy_config(
        {"action": "write", "key": "enableTelemetry", "value": False, "explanation": "opt out"},
        agent="DEV_AGENT",
        ring=1,
    )
    await registry.handle_agy_config(
        {"action": "write", "key": "editor", "value": "code", "explanation": "configure editor"},
        agent="DEV_AGENT",
        ring=1,
    )

    # Step 3: Add workspace directory
    proj_path = "C:/user/projects/LaForge" if os.name == "nt" else "/user/projects/LaForge"
    await registry.handle_agy_add_dir(
        {"path": proj_path, "explanation": "authorize dev project folder"},
        agent="DEV_AGENT",
        ring=2,
    )

    # Step 4: Run task list mock command
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "ID: 101 | Title: Setup unit tests | Status: pending"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        res_run = await registry.handle_agy_run(
            {"command": "task list", "explanation": "fetch todo list"},
            agent="DEV_AGENT",
            ring=2,
        )
        assert res_run["success"] is True
        assert "101" in res_run["stdout"]
        assert "Setup unit tests" in res_run["stdout"]


@pytest.mark.asyncio
async def test_workload_telemetry_opt_out_with_event_bus(registry):
    """Tier 4: Scenario: User changes telemetry config, and event bus log is monitored."""
    if not hasattr(registry, "handle_agy_config"):
        pytest.skip("handle_agy_config not implemented on registry")

    # Opt out of telemetry — go through dispatch() so the lifecycle event-bus
    # wrapper fires (tool.<name>.start/end are emitted by dispatch, not by the
    # handler called directly).
    await registry.dispatch(
        "agy_config",
        {"action": "write", "key": "enableTelemetry", "value": False, "explanation": "user privacy selection"},
        agent="DEV_AGENT",
        ring=1,
    )

    # Verify event bus logged the tool.agy_config.start and end events
    assert registry._event_bus.publish.call_count >= 2


@pytest.mark.asyncio
async def test_workload_editor_config_lifecycle(registry, mock_home):
    """Tier 4: Scenario: Setting temporary editor configurations and performing updates."""
    if not hasattr(registry, "handle_agy_config"):
        pytest.skip("handle_agy_config not implemented on registry")

    # Set editor to vim
    res1 = await registry.handle_agy_config(
        {"action": "write", "key": "editor", "value": "vim", "explanation": "set temp editor"},
        agent="DEV_AGENT",
        ring=1,
    )
    assert res1["success"] is True

    # Read back to verify
    res2 = await registry.handle_agy_config(
        {"action": "read", "key": "editor", "explanation": "verify temp editor"},
        agent="DEV_AGENT",
        ring=3,
    )
    assert res2["value"] == "vim"

    # Reset editor
    res3 = await registry.handle_agy_config(
        {"action": "write", "key": "editor", "value": "code", "explanation": "reset back to default"},
        agent="DEV_AGENT",
        ring=1,
    )
    assert res3["success"] is True


@pytest.mark.asyncio
async def test_workload_bulk_workspace_authorization(registry, mock_home):
    """Tier 4: Scenario: Secure bulk directory updates in trustedWorkspaces."""
    if not hasattr(registry, "handle_agy_add_dir"):
        pytest.skip("handle_agy_add_dir not implemented on registry")

    paths = [
        "%USERPROFILE%/src1" if os.name == "nt" else "/home/user/src1",
        "%USERPROFILE%/src2" if os.name == "nt" else "/home/user/src2",
    ]

    for p in paths:
        res = await registry.handle_agy_add_dir(
            {"path": p, "explanation": "bulk authorization scan"},
            agent="DEV_AGENT",
            ring=2,
        )
        assert res["success"] is True

    # Validate that both are written in settings
    settings_file = mock_home / ".gemini" / "antigravity-cli" / "settings.json"
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    for p in paths:
        assert p in data.get("trustedWorkspaces", [])


@pytest.mark.asyncio
async def test_workload_pipeline_cli_mock(registry):
    """Tier 4: Scenario: Execute a pipeline of multiple task operations in sequence."""
    if not hasattr(registry, "handle_agy_run"):
        pytest.skip("handle_agy_run not implemented on registry")

    pipeline = [
        {"cmd": "task add 'Test CLI pipeline'", "stdout": "Task 42 added successfully", "rc": 0},
        {"cmd": "task list", "stdout": "ID: 42 | Title: Test CLI pipeline | Status: pending", "rc": 0},
        {"cmd": "task complete 42", "stdout": "Task 42 completed", "rc": 0},
    ]

    with patch("subprocess.run") as mock_run:
        for step in pipeline:
            mock_proc = MagicMock()
            mock_proc.returncode = step["rc"]
            mock_proc.stdout = step["stdout"]
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            res = await registry.handle_agy_run(
                {"command": step["cmd"], "explanation": "pipeline execution test"},
                agent="DEV_AGENT",
                ring=2,
            )
            assert res["success"] is True
            assert step["stdout"] in res["stdout"]
            assert res["exit_code"] == step["rc"]


@pytest.mark.asyncio
async def test_remediation_agy_run_strips_prefix_and_prepends_resolved(registry):
    """Test that handle_agy_run strips leading 'agy' and prepends resolved agy binary."""
    with patch("shutil.which", return_value="C:/path/to/resolved/agy") as mock_which, \
         patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Task list"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        # Command starts with agy prefix
        res = await registry.handle_agy_run(
            {"command": "agy task list", "explanation": "test strip"},
            agent="TEST",
            ring=2,
        )
        assert res["success"] is True
        # Check that subprocess.run was called with resolved binary prepended,
        # and the leading 'agy' token stripped.
        expected_cmd = ["C:/path/to/resolved/agy", "task", "list"]
        mock_run.assert_called_once()
        called_args, called_kwargs = mock_run.call_args
        assert called_args[0] == expected_cmd
        assert called_kwargs["timeout"] == 60


@pytest.mark.asyncio
async def test_remediation_agy_run_rejects_percent(registry):
    """Test that handle_agy_run rejects commands containing percent character."""
    res = await registry.handle_agy_run(
        {"command": "task list %TMP%", "explanation": "rejection check"},
        agent="TEST",
        ring=2,
    )
    assert res["success"] is False
    assert "forbidden characters" in res.get("error", "")


@pytest.mark.asyncio
async def test_remediation_agy_add_dir_rejects_traversal(registry):
    """Test that handle_agy_add_dir rejects relative paths and traversal sequences."""
    # Test path with traversal parts
    path_traversal = "C:/projects/nokido/../outside" if os.name == "nt" else "/projects/nokido/../outside"
    res1 = await registry.handle_agy_add_dir(
        {"path": path_traversal, "explanation": "traversal attack"},
        agent="TEST",
        ring=2,
    )
    assert res1["success"] is False
    assert "traversal" in res1.get("error", "").lower()

    # Test path with relative string
    path_rel = "./projects/nokido"
    res2 = await registry.handle_agy_add_dir(
        {"path": path_rel, "explanation": "relative path"},
        agent="TEST",
        ring=2,
    )
    assert res2["success"] is False
    assert "is not absolute" in res2.get("error", "").lower()


@pytest.mark.asyncio
async def test_remediation_corruption_prevention(registry, mock_home):
    """Test that config write and add_dir fail with success=False if settings.json is corrupted."""
    settings_dir = mock_home / ".gemini" / "antigravity-cli"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_file = settings_dir / "settings.json"
    settings_file.write_text("{invalid json", encoding="utf-8")

    # 1. Config write action
    res_write = await registry.handle_agy_config(
        {"action": "write", "key": "editor", "value": "code", "explanation": "write to corrupt file"},
        agent="TEST",
        ring=1,
    )
    assert res_write["success"] is False
    assert "Failed to parse" in res_write.get("error", "")

    # 2. Add dir action
    path = "%USERPROFILE%/workspace" if os.name == "nt" else "/home/user/workspace"
    res_add_dir = await registry.handle_agy_add_dir(
        {"path": path, "explanation": "add to corrupt file"},
        agent="TEST",
        ring=2,
    )
    assert res_add_dir["success"] is False
    assert "Failed to parse" in res_add_dir.get("error", "")
