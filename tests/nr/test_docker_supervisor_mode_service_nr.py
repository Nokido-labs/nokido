# -*- coding: utf-8 -*-
"""NR (28/10, accord owner) : le hub parle au gateway Docker MCP du SERVICE owner, en HTTP authentifie.

Le hub ne lance plus `docker mcp gateway run` lui-meme (sous son compte il meurt : base dans le profil owner).
Mode « service » (defaut) : docker.wanted (ensure_daemon) -> reveil de NokidoDockerMcpGateway -> port ouvert ->
JSON-RPC sur http://127.0.0.1:8811/mcp, Bearer MCP_GATEWAY_AUTH_TOKEN, session Mcp-Session-Id apres initialize,
reponse JSON ou flux SSE. Le mode stdio reste disponible (LAFORGE_DOCKER_MCP_TRANSPORT=stdio)."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_docker_supervisor as fds  # noqa: E402


def test_mode_service_par_defaut_et_url(monkeypatch):
    monkeypatch.delenv("LAFORGE_DOCKER_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("LAFORGE_DOCKER_MCP_PORT", raising=False)
    assert fds._mode_service() is True
    assert fds._url_gateway() == "http://127.0.0.1:8811/mcp"
    monkeypatch.setenv("LAFORGE_DOCKER_MCP_TRANSPORT", "stdio")
    assert fds._mode_service() is False


def test_reponse_sse_lue():
    brut = 'event: message\ndata: {"jsonrpc":"2.0","id":3,"result":{"tools":[{"name":"mcp-find"}]}}\n\n'
    assert fds._lire_reponse(brut, "text/event-stream")["result"]["tools"][0]["name"] == "mcp-find"
    assert fds._lire_reponse('{"jsonrpc":"2.0","id":1,"result":{}}', "application/json")["id"] == 1
    assert fds._lire_reponse("", "application/json") is None


def test_appel_reveille_docker_et_service_puis_parle_en_bearer(monkeypatch):
    monkeypatch.delenv("LAFORGE_DOCKER_MCP_TRANSPORT", raising=False)
    journal, envois = [], []

    async def daemon(self):
        journal.append("docker")

    monkeypatch.setattr(fds.DockerSupervisor, "ensure_daemon", daemon)
    monkeypatch.setattr(fds, "_demarrer_service_gateway", lambda: journal.append("service"))
    monkeypatch.setattr(fds, "_port_ouvert", lambda port: True)
    monkeypatch.setattr(fds, "_jeton_gateway", lambda: "jeton-test")
    monkeypatch.setattr(fds, "_demander_docker", lambda: None)

    def post(url, corps, jeton, session=None, timeout=15.0):
        envois.append((url, corps.get("method"), jeton, session))
        if corps.get("method") == "initialize":
            return {"jsonrpc": "2.0", "id": corps["id"], "result": {}}, "sess-1"
        if corps.get("method") == "tools/call":
            return {"jsonrpc": "2.0", "id": corps["id"], "result": {"content": [{"type": "text", "text": "ok"}]}}, session
        return None, session

    monkeypatch.setattr(fds, "_post_http", post)
    sup = fds.DockerSupervisor()
    assert asyncio.run(sup.call_tool("mcp-find", {"query": "x"})) == "ok"
    assert journal == ["docker", "service"]
    methodes = [m for _, m, _, _ in envois]
    assert methodes[0] == "initialize" and "tools/call" in methodes
    assert all(u == "http://127.0.0.1:8811/mcp" and j == "jeton-test" for u, _, j, _ in envois)
    assert [s for _, m, _, s in envois if m == "tools/call"] == ["sess-1"]


def test_sans_jeton_bloque_par_dependance(monkeypatch):
    monkeypatch.delenv("LAFORGE_DOCKER_MCP_TRANSPORT", raising=False)

    async def daemon(self):
        return None

    monkeypatch.setattr(fds.DockerSupervisor, "ensure_daemon", daemon)
    monkeypatch.setattr(fds, "_demarrer_service_gateway", lambda: None)
    monkeypatch.setattr(fds, "_port_ouvert", lambda port: True)
    monkeypatch.setattr(fds, "_jeton_gateway", lambda: None)
    with pytest.raises(fds.DockerSupervisorError, match="BLOQUE_PAR_DEPENDANCE"):
        asyncio.run(fds.DockerSupervisor().list_tools(force=True))
