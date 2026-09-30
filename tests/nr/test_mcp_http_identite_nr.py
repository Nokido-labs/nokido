"""NR — le serveur MCP HTTP ne se laisse plus dicter l'identite, ni ouvrir sans jeton (2026-09-29).

Signalement d'une session d'audit, verifie dans le code (`tools/forge_mcp_http.py`, serveur dormant) :
- sans jeton configure, `_check_bearer` rendait « acces libre » pour /mcp et /metrics ;
- l'en-tete X-Agent REMPLACAIT l'identite authentifiee (un jeton d'agent pouvait se dire CLAUDE) ;
- /init ecrivait LAFORGE_AGENT (tout le processus) depuis X-Agent AVANT de valider le jeton OTA.
Les tests exercent les VRAIS gestionnaires via `construire_app` + le client de test Starlette.
"""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

testclient = pytest.importorskip("starlette.testclient")
import forge_mcp_http as H  # noqa: E402

_CFG = {"host": "127.0.0.1", "port": 0, "path": "/mcp", "token": "", "origins": "localhost,127.0.0.1,testserver"}
_PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


def _faux_securite(monkeypatch, identite="GEMINI", ota_ok=False):
    """Module de securite factice : le jeton d'agent designe `identite` ; le jeton OTA vaut `ota_ok`."""
    class _Sec:
        audit = types.SimpleNamespace(log=lambda *a, **k: None)

        @staticmethod
        def authenticate_bearer(auth):
            return (True, identite) if auth.endswith("jeton-agent") else (False, "Token invalide")

    class _Inbound:
        @staticmethod
        def validate_incoming(token, source_ip="", user_agent=""):
            return (True, "", {"agent_id": "AGENT_OTA", "rights": []}) if ota_ok else (False, "jeton OTA invalide", {})

    mod = types.ModuleType("nokido_agent.app.forge_mcp_security")
    mod.get_security = lambda: _Sec()
    mod.get_inbound_manager = lambda: _Inbound()
    mod.detect_ssrf_beacon = lambda texte: (False, "")
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_mcp_security", mod)


def _client(cfg):
    app, _ = H.construire_app(mcp_server=object(), project_root=ROOT, cfg=dict(cfg))
    return testclient.TestClient(app)


def test_sans_jeton_configure_l_acces_est_refuse(monkeypatch):
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_mcp_security", None)  # pas de module de securite
    monkeypatch.delenv("MCP_HTTP_SANS_JETON", raising=False)
    r = _client(_CFG).post("/mcp", json=_PING)
    assert r.status_code == 401, "acces libre sans jeton configure"
    assert _client(_CFG).get("/metrics").status_code == 401


def test_l_ouverture_sans_jeton_demande_un_drapeau_explicite_en_boucle_locale(monkeypatch):
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_mcp_security", None)
    monkeypatch.setenv("MCP_HTTP_SANS_JETON", "1")
    assert _client(_CFG).post("/mcp", json=_PING).status_code != 401
    expose = dict(_CFG, host="0.0.0.0")
    assert _client(expose).post("/mcp", json=_PING).status_code == 401, "ouvert sans jeton hors boucle locale"


def test_x_agent_ne_remplace_pas_l_identite_du_jeton(monkeypatch):
    _faux_securite(monkeypatch, identite="GEMINI")
    monkeypatch.setenv("LAFORGE_AGENT", "AVANT")
    cfg = dict(_CFG, token="configure")
    r = _client(cfg).post("/mcp", json=_PING,
                          headers={"Authorization": "Bearer jeton-agent", "X-Agent": "CLAUDE"})
    assert r.status_code != 401
    import os
    assert os.environ["LAFORGE_AGENT"] == "GEMINI", "l'en-tete X-Agent a remplace l'identite authentifiee"


def test_init_ne_touche_pas_l_identite_si_le_jeton_ota_est_invalide(monkeypatch):
    _faux_securite(monkeypatch, ota_ok=False)
    monkeypatch.setenv("LAFORGE_AGENT", "AVANT")
    r = _client(_CFG).get("/init", params={"session": "faux"}, headers={"X-Agent": "USURPATEUR"})
    assert r.status_code == 403
    import os
    assert os.environ["LAFORGE_AGENT"] == "AVANT", "identite changee par une requete au jeton invalide"


def test_init_pose_l_identite_du_jeton_valide_pas_celle_de_l_en_tete(monkeypatch):
    _faux_securite(monkeypatch, ota_ok=True)
    monkeypatch.setenv("LAFORGE_AGENT", "AVANT")
    r = _client(_CFG).get("/init", params={"session": "bon"}, headers={"X-Agent": "USURPATEUR"})
    assert r.status_code == 200
    import os
    assert os.environ["LAFORGE_AGENT"] == "AGENT_OTA"
