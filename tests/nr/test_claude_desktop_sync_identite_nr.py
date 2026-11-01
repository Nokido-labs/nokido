"""NR : la synchro Claude Desktop porte l'identite LAFORGE_AGENT=CLAUDE_DESKTOP (pas BRIDGE)."""
import importlib.util
import json
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "tools" / "forge_claude_desktop_sync.py"

def _mod(tmp_path):
    spec = importlib.util.spec_from_file_location("fcds_nr", SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.CFG = tmp_path / "Claude" / "claude_desktop_config.json"
    return m

def test_entree_generee_porte_identite(tmp_path):
    m = _mod(tmp_path)
    m.sync_mcp(False)
    cfg = json.loads(m.CFG.read_text(encoding="utf-8"))
    assert cfg["mcpServers"]["Nokido"]["env"]["LAFORGE_AGENT"] == "CLAUDE_DESKTOP"

def test_identite_existante_conservee(tmp_path):
    m = _mod(tmp_path)
    m.CFG.parent.mkdir(parents=True)
    existant = {"mcpServers": {"Nokido": {"command": "x", "env": {"LAFORGE_AGENT": "AUTRE"}}}}
    m.CFG.write_text(json.dumps(existant), encoding="utf-8")
    m.sync_mcp(False)
    cfg = json.loads(m.CFG.read_text(encoding="utf-8"))
    assert cfg["mcpServers"]["Nokido"]["env"]["LAFORGE_AGENT"] == "AUTRE"
