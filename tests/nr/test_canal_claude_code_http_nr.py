"""NR (owner 29/10 : « le tray affiche stdio claude, mais le CLI est en HTTP streamable ? ») : le canal se deduit du
TRANSPORT MESURE avant le nom de l'agent.

Cause : _resolve_channel (tools/nokido_hub.py) et la graine _CHANNEL_SEED mappaient CLAUDE et CLAUDE_CLI sur
STDIO_CLAUDE, heritage du temps ou seul Claude Desktop (pont stdio, X-Transport: stdio-bridge) parlait au hub. Claude
Code se connecte en MCP Streamable HTTP (.mcp.json type http) : il etait etiquete STDIO a chaque appel, et
_canal_contradictoire le savait sans que personne l'affiche.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class _Req:
    def __init__(self, entetes):
        self.headers = entetes


def _hub():
    nom = "nokido_hub_nr_canal"
    if nom in sys.modules:
        return sys.modules[nom]
    sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]
    spec = importlib.util.spec_from_file_location(nom, ROOT / "tools" / "nokido_hub.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[nom] = m
    spec.loader.exec_module(m)
    return m


def test_claude_code_en_http_n_est_pas_stdio():
    h = _hub()
    assert h._resolve_channel("CLAUDE", _Req({"User-Agent": "claude-code/2.1"})) == "HTTP_CLAUDE"
    assert h._resolve_channel("CLAUDE_CLI", _Req({})) == "HTTP_CLAUDE"


def test_le_pont_stdio_reste_stdio_quel_que_soit_le_nom():
    h = _hub()
    assert h._resolve_channel("CLAUDE", _Req({"X-Transport": "stdio-bridge/1.4"})) == "STDIO_CLAUDE"
    assert h._resolve_channel("BRIDGE", _Req({"X-Transport": "stdio-bridge/1.4"})) == "STDIO_CLAUDE"


def test_canal_connu_de_l_enum_et_contradiction_coherente():
    h = _hub()
    from nokido_agent.app.forge_network_logger import NetworkChannel
    assert NetworkChannel("HTTP_CLAUDE").value == "HTTP_CLAUDE"
    assert h._canal_contradictoire("HTTP_CLAUDE", "HTTP_DIRECT") is False
    assert h._canal_contradictoire("HTTP_CLAUDE", "STDIO_BRIDGE") is True
    assert h._CHANNEL_SEED["CLAUDE"][0] == "HTTP_CLAUDE"
