"""forge_vscode_mcp_sync : materialisation hub Nokido dans les addons VSCode.

Garde Police P1 : chaque identite d'addon (LAFORGE_AGENT) DOIT exister dans
config/agent_identities.json, sinon forge_videur la resout en inconnu (trou A4).
"""
import importlib
import json
from pathlib import Path

m = importlib.import_module("forge_vscode_mcp_sync")


def test_every_addon_identity_is_registered():
    d = json.loads((Path(m.ROOT) / "config" / "agent_identities.json").read_text("utf-8"))
    known = set((d.get("agents") or {}).keys())
    for name, spec in m.CLIENTS.items():
        agents = [spec["agent"]] if spec["transport"] == "http" else list(spec["servers"].values())
        for ag in agents:
            assert ag in known, f"identite {ag} ({name}) absente de agent_identities.json"


def test_http_block_shape():
    b = m._http_block("CLAUDE", "tok123")
    assert b["url"] == m.HUB_URL
    assert b["headers"]["X-Agent-Name"] == "CLAUDE"
    assert b["headers"]["Authorization"] == "Bearer tok123"  # token existant preserve


def test_stdio_block_uses_base_python_and_bridge():
    b = m._stdio_block("SIXTH")
    assert b["command"] == m.BRIDGE_PY and "miniforge3/python.exe" in b["command"]
    assert b["args"][0] == "-u" and b["args"][-1].endswith("mcp_bridge.py")
    assert b["env"]["LAFORGE_AGENT"] == "SIXTH"


def test_plan_client_failsafe_on_missing():
    plan = m.plan_client("ghost", {"path": Path("Z:/nope/none.json"), "transport": "http", "agent": "CLAUDE"})
    assert plan["exists"] is False and isinstance(plan["actions"], list)


def test_resolve_token_prefers_existing():
    assert m._resolve_token("CLAUDE", "keepme") == "keepme"  # ne casse jamais un addon qui marche
