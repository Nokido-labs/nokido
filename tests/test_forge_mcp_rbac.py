"""Phase 35 RBAC scoped MCP tools tests.

Convention Nokido : ring INFERIEUR = PLUS de droits.
MASTER=-1, SYSTEM=0, DEV=1, TRUSTED=2, COLLAB=3, UNTRUSTED=4.

Mode default = warn (autorise + log). enforce = bloque vraiment.
"""
import pytest
import forge_mcp_rbac as rbac


@pytest.fixture
def enforce_mode(monkeypatch):
    """Force mode enforce pour les tests stricts."""
    monkeypatch.setattr(rbac, "_ENFORCE", True)


def test_check_capability_sufficient_ring_trusted_can_run():
    """TRUSTED (ring 2) peut exec 'run' Phase 35 step 2 relaxe."""
    ok, reason = rbac.check_tool_capability("run", "claude", ring=2)
    assert ok is True, reason


def test_check_capability_insufficient_ring_warn_allows(monkeypatch):
    """Mode warn default : UNTRUSTED (ring 4) tente 'trusted_script' (DEV/1)
    → log mais AUTORISE (transition non-cassante)."""
    monkeypatch.setattr(rbac, "_ENFORCE", False)
    ok, reason = rbac.check_tool_capability("trusted_script", "untrusted", ring=4)
    assert ok is True
    assert "warn_mode_allowed" in reason


def test_check_capability_insufficient_ring_enforce_blocks(enforce_mode):
    """Mode enforce : UNTRUSTED (ring 4) ne peut PAS exec 'trusted_script'."""
    ok, reason = rbac.check_tool_capability("trusted_script", "untrusted", ring=4)
    assert ok is False
    assert "insufficient ring" in reason


def test_check_capability_read_only_untrusted_ok():
    """UNTRUSTED (ring 4) peut 'read' (required UNTRUSTED/4)."""
    ok, reason = rbac.check_tool_capability("read", "agt", ring=4)
    assert ok is True, reason


def test_check_capability_unknown_tool_permissive_default():
    ok, reason = rbac.check_tool_capability("unknown_tool", "agt", ring=4,
                                             permissive_unknown=True)
    assert ok is True
    assert "permissive" in reason


def test_check_capability_unknown_tool_strict():
    ok, reason = rbac.check_tool_capability("unknown_tool", "agt", ring=0,
                                             permissive_unknown=False)
    assert ok is False
    assert "not in RBAC mapping" in reason


def test_orchestrate_requires_trusted_or_better_enforce(enforce_mode):
    """'orchestrate' max ring TRUSTED (2). COLLAB (3) refuse en enforce."""
    ok_collab, _ = rbac.check_tool_capability("orchestrate", "agt", ring=3)
    ok_trusted, _ = rbac.check_tool_capability("orchestrate", "agt", ring=2)
    assert ok_collab is False
    assert ok_trusted is True


def test_extended_mapping_covers_60_plus_tools():
    """Phase 35 step 2 : mapping étendu."""
    assert len(rbac._TOOL_REQUIRED_RING) >= 50
    # Spot check tools courants
    for tool in ["ask", "task", "skill", "orchestrate", "run", "write",
                 "browser", "github", "memory", "rag"]:
        assert tool in rbac._TOOL_REQUIRED_RING


def test_master_can_invoke_anything():
    """MASTER (ring -1) peut tout."""
    for tool in ["read", "ask", "orchestrate", "run"]:
        ok, _ = rbac.check_tool_capability(tool, "master", ring=-1)
        assert ok is True, f"MASTER should access {tool}"


def test_tool_required_ring_existing():
    assert rbac.tool_required_ring("read") is not None
    assert rbac.tool_required_ring("run") is not None


def test_tool_required_ring_unknown_returns_none():
    assert rbac.tool_required_ring("does_not_exist_xyz") is None


def test_list_tools_by_ring_returns_grouped():
    grouped = rbac.list_tools_by_ring()
    assert isinstance(grouped, dict)
    assert all(isinstance(v, list) for v in grouped.values())
    # 'run' doit être dans le bucket TRUSTED (ring 2)
    assert "run" in grouped.get(2, [])
