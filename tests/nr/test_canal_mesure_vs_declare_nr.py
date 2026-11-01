"""NR identites phase 2 : l'audit journalise le transport SIGNALE a cote du canal declare."""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def _hub():
    import nokido_hub
    return nokido_hub


class _Req:
    def __init__(self, headers=None):
        self.headers = headers or {}


def test_en_tete_forge_par_client_http_est_signale_stdio_bridge():
    """Preuve que X-Transport n'est PAS une authentification : un client HTTP
    quelconque qui pose l'en-tete est signale STDIO_BRIDGE (SIGNAL != PREUVE)."""
    req = _Req({"X-Transport": "stdio-bridge/9", "User-Agent": "curl/8"})
    assert _hub()._transport_signale(req) == "STDIO_BRIDGE"


def test_bridge_mesure_par_en_tete_x_transport():
    assert _hub()._transport_signale(_Req({"X-Transport": "stdio-bridge/3.1"})) == "STDIO_BRIDGE"


def test_requete_sans_marque_bridge_est_http_direct():
    assert _hub()._transport_signale(_Req({"User-Agent": "curl/8"})) == "HTTP_DIRECT"


def test_illisible_donne_inconnu_jamais_devine():
    h = _hub()
    assert h._transport_signale(None) == "INCONNU"

    class _Cass:
        @property
        def headers(self):
            raise RuntimeError("boom")
    assert h._transport_signale(_Cass()) == "INCONNU"


def test_contradiction_declare_vs_mesure():
    h = _hub()
    assert h._canal_contradictoire("STDIO_CLAUDE", "HTTP_DIRECT") is True
    assert h._canal_contradictoire("HTTP_DIRECT", "STDIO_BRIDGE") is True


def test_pas_de_contradiction_si_coherent_ou_inconnu():
    h = _hub()
    assert h._canal_contradictoire("STDIO_CLAUDE", "STDIO_BRIDGE") is False
    assert h._canal_contradictoire("HTTP_DIRECT", "HTTP_DIRECT") is False
    assert h._canal_contradictoire("STDIO_CLAUDE", "INCONNU") is False


def test_log_network_passe_les_champs_a_net_log(monkeypatch):
    h = _hub()
    vus = {}
    mod = types.ModuleType("nokido_agent.app.forge_network_logger")

    class _E:
        def __getattr__(self, n):
            return n
    mod.NetworkChannel = _E()
    mod.Direction = types.SimpleNamespace(IN="IN", OUT="OUT")
    mod.net_log = lambda *a, **k: vus.update(k)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_network_logger", mod)
    monkeypatch.setattr(h, "_write_db", lambda e: None)
    monkeypatch.setattr(h, "_sse_broadcast", lambda e: None)
    # 29/10 : CLAUDE (Claude Code) parle en MCP Streamable HTTP -> canal HTTP_CLAUDE, COHERENT avec HTTP_DIRECT
    # (test_canal_claude_code_http_nr). La vraie contradiction : BRIDGE (pont stdio de Claude Desktop) qui arrive
    # SANS sa marque X-Transport. Meme assertion, cas reellement contradictoire.
    h._log_network("IN", method="tools/call", tool="x", agent="BRIDGE",
                   request=_Req({"User-Agent": "curl/8"}))
    assert vus["meta"]["transport_signale"] == "HTTP_DIRECT"
    assert vus["meta"]["canal_contradictoire"] is True
