"""tests/test_docker_action_routing.py — Test du routage de docker_action dans MCPRegistry.

Vérifie la correction du bug (1) : docker_action ne doit PAS être intercepté par
_handle_docker_proxy (qui produisait `unknown tool "action"`), mais bien routé
vers handle_docker_action.
"""

import pytest
import asyncio
from app.forge_mcp_registry import ToolRegistry

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : docker reel + SQLite timeout=30 (code appele)
#   (l.17)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)


@pytest.mark.asyncio
async def test_docker_action_routing_not_proxied():
    reg = ToolRegistry()
    # Appel de docker_action via dispatch
    res = await reg.dispatch("docker_action", {"argv": ["ps", "-a"]}, "TEST_AGENT", 1)
    res_str = str(res)
    
    # L'erreur de routage cassé était 'unknown tool "action"'
    assert "unknown tool \"action\"" not in res_str
    assert "ERR: docker gateway" not in res_str
    
    # Doit avoir été routé vers handle_docker_action (qui effectue la décision DockerPolicy)
    # Soit la réponse est le JSON de spawn / execution, soit l'erreur de privilèges spawn_trusted.
    assert ("spawn trusted" in res_str or "CONTAINER ID" in res_str or "ok" in res_str or "decision" in res_str)


@pytest.mark.asyncio
async def test_docker_action_real_ps_a():
    from app.forge_docker_agent import decide
    # Vérifier que decide() autorise ps -a
    decision, reason = decide(["ps", "-a", "--format", "{{.Names}}"])
    assert decision == "ALLOW"
    assert "ps" in reason
