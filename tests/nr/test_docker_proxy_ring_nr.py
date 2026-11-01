"""
tests/nr/test_docker_proxy_ring_nr.py — NR tests for Docker MCP proxy ring enforcement.
"""

import pytest
import asyncio
from app.forge_mcp_registry import ToolRegistry

@pytest.mark.asyncio
async def test_docker_proxy_ring_refused():
    reg = ToolRegistry()
    # Use a dummy docker tool name without a native handler
    # Ring 1 par defaut (owner 28/10, apres inventaire mesure : les clients ring 1 y accedent VIA le hub) :
    # ring 2 et au-dela refuses
    for ring in (2, 4):
        res = await reg.dispatch("docker_ps", {"argv": ["ps"]}, "TEST_AGENT", ring)
        assert isinstance(res, str)
        assert "SECURITY: Acces refuse" in res

@pytest.mark.asyncio
async def test_docker_proxy_ring_allowed(monkeypatch):
    reg = ToolRegistry()
    # Mock the proxy handler to avoid real Docker interaction
    async def fake_proxy(name, args, agent, ring):
        return {"ok": True, "tool": name}
    monkeypatch.setattr(reg, "_handle_docker_proxy", fake_proxy, raising=False)
    res = await reg.dispatch("docker_ps", {"argv": ["ps"]}, "TEST_AGENT", 1)
    assert isinstance(res, dict)
    assert res.get("ok") is True
    assert res.get("tool") == "docker_ps"
