"""tests/nr/test_ingress_auth_tools_nr.py — NR ingress loopback durcis.

Reconciliation SECURITE 05 (branche source tache/opencode_glm/1d858135c9b6).
Verifie sur forge_anthropic_ingress et forge_gemini_ingress :
- 401 sans jeton
- 401 jeton invalide
- 401 jeton expire
- 200 jeton valide sans tools
- 400 avec tools (ou tool_choice / tool_config)
- 400 corps illisible (non JSON ou non dict)
Sans acces reseau, avec le vrai TestClient Starlette.
"""

from __future__ import annotations

import time

import pytest
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route

from nokido_agent.app.forge_integrity import CapabilityToken, IntegrityRing, get_manager
from nokido_agent.app.forge_auth_tokens import login_agent
from nokido_agent.app import forge_llm_format_bridge as bridge
from nokido_agent.tools import forge_anthropic_ingress
from nokido_agent.tools import forge_gemini_ingress


@pytest.fixture
def auth_token(monkeypatch):
    """Genere un CapabilityToken valide pour les tests sans vault DPAPI."""
    mgr = get_manager()
    tokens = {"CLAUDE_CLI": "test_claude_token_secret"}
    tok = login_agent("CLAUDE_CLI", secret_id="test_claude_token_secret", agent_tokens=tokens)
    return tok


@pytest.fixture
def expired_token():
    """Genere un CapabilityToken expire pour tester le refus 401 sur expiration (SECURITE 05)."""
    mgr = get_manager()
    cap = CapabilityToken(
        sub="CLAUDE_CLI",
        ring=IntegrityRing.TRUSTED,
        scopes={},
        exp=time.time() - 3600,
        iat=time.time() - 7200,
        jti="expired_test_jti",
    )
    return cap.encode(mgr._secret)


@pytest.fixture(autouse=True)
def _trace_neutralisee(monkeypatch):
    """07/11 : chaque appel proxy trace son slot dans `token_usage`. Ici, aucune ecriture vers la base de
    production ; la trace elle-meme est prouvee par tests/nr/test_identite_slot_api_nr.py sur base temporaire."""
    async def pas_de_trace(*args, **kwargs):
        return None

    monkeypatch.setattr(bridge, "tracer_appel_slot", pas_de_trace)


@pytest.fixture
def anthropic_client(monkeypatch):
    # Mock ask_via_hub pour eviter tout appel reseau / hub
    async def fake_ask(*args, **kwargs):
        return bridge.AskResult(ok=True, reply="reponse simulee", provider="ollama", it=10, ot=5)

    monkeypatch.setattr(bridge, "ask_via_hub", fake_ask)
    app = Starlette(
        routes=[
            Route("/v1/messages", forge_anthropic_ingress.messages, methods=["POST"]),
        ]
    )
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def gemini_client(monkeypatch):
    # Mock ask_via_hub pour eviter tout appel reseau / hub
    async def fake_ask(*args, **kwargs):
        return bridge.AskResult(ok=True, reply="reponse simulee", provider="ollama", it=10, ot=5)

    monkeypatch.setattr(bridge, "ask_via_hub", fake_ask)
    app = Starlette(
        routes=[
            Route("/v1beta/models/{rest:path}", forge_gemini_ingress.generate, methods=["POST"]),
        ]
    )
    return TestClient(app, raise_server_exceptions=True)


# --- Tests Anthropic Ingress ---

def test_anthropic_401_sans_jeton(anthropic_client):
    r = anthropic_client.post("/v1/messages", json={"messages": [{"role": "user", "content": "bonjour"}]})
    assert r.status_code == 401
    assert r.json()["type"] == "error"
    assert r.json()["error"]["type"] == "authentication_error"


def test_anthropic_401_jeton_invalide(anthropic_client):
    r = anthropic_client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer badtoken123"},
        json={"messages": [{"role": "user", "content": "bonjour"}]},
    )
    assert r.status_code == 401
    assert r.json()["type"] == "error"
    assert r.json()["error"]["type"] == "authentication_error"


def test_anthropic_401_jeton_expire(anthropic_client, expired_token):
    r = anthropic_client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {expired_token}"},
        json={"messages": [{"role": "user", "content": "bonjour"}]},
    )
    assert r.status_code == 401
    assert r.json()["type"] == "error"
    assert r.json()["error"]["type"] == "authentication_error"


def test_anthropic_200_jeton_valide_sans_tools(anthropic_client, auth_token):
    r = anthropic_client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"messages": [{"role": "user", "content": "bonjour"}]},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "message"
    assert data["content"][0]["text"] == "reponse simulee"


def test_anthropic_400_avec_tools(anthropic_client, auth_token):
    r = anthropic_client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={
            "messages": [{"role": "user", "content": "bonjour"}],
            "tools": [{"name": "get_weather", "description": "weather tool"}],
        },
    )
    assert r.status_code == 400
    assert r.json()["type"] == "error"
    assert "tools" in r.json()["error"]["message"]


def test_anthropic_400_avec_tool_choice(anthropic_client, auth_token):
    r = anthropic_client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={
            "messages": [{"role": "user", "content": "bonjour"}],
            "tool_choice": "auto",
        },
    )
    assert r.status_code == 400
    assert r.json()["type"] == "error"
    assert "tools" in r.json()["error"]["message"]


def test_anthropic_400_corps_illisible(anthropic_client, auth_token):
    r = anthropic_client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"},
        content="corps non json",
    )
    assert r.status_code == 400
    assert r.json()["type"] == "error"
    assert r.json()["error"]["type"] == "invalid_request_error"


# --- Tests Gemini Ingress ---

def test_gemini_401_sans_jeton(gemini_client):
    r = gemini_client.post(
        "/v1beta/models/gemini-2.5-pro:generateContent",
        json={"contents": [{"role": "user", "parts": [{"text": "bonjour"}]}]},
    )
    assert r.status_code == 401
    assert "error" in r.json()


def test_gemini_401_jeton_invalide(gemini_client):
    r = gemini_client.post(
        "/v1beta/models/gemini-2.5-pro:generateContent",
        headers={"Authorization": "Bearer badtoken123"},
        json={"contents": [{"role": "user", "parts": [{"text": "bonjour"}]}]},
    )
    assert r.status_code == 401
    assert "error" in r.json()


def test_gemini_401_jeton_expire(gemini_client, expired_token):
    r = gemini_client.post(
        "/v1beta/models/gemini-2.5-pro:generateContent",
        headers={"Authorization": f"Bearer {expired_token}"},
        json={"contents": [{"role": "user", "parts": [{"text": "bonjour"}]}]},
    )
    assert r.status_code == 401
    assert "error" in r.json()


def test_gemini_200_jeton_valide_sans_tools(gemini_client, auth_token):
    r = gemini_client.post(
        "/v1beta/models/gemini-2.5-pro:generateContent",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"contents": [{"role": "user", "parts": [{"text": "bonjour"}]}]},
    )
    assert r.status_code == 200
    data = r.json()
    assert "candidates" in data
    assert data["candidates"][0]["content"]["parts"][0]["text"] == "reponse simulee"


def test_gemini_400_avec_tools(gemini_client, auth_token):
    r = gemini_client.post(
        "/v1beta/models/gemini-2.5-pro:generateContent",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={
            "contents": [{"role": "user", "parts": [{"text": "bonjour"}]}],
            "tools": [{"function_declarations": [{"name": "fake"}]}],
        },
    )
    assert r.status_code == 400
    assert "tools" in r.json()["error"]["message"]


def test_gemini_400_avec_tool_config(gemini_client, auth_token):
    r = gemini_client.post(
        "/v1beta/models/gemini-2.5-pro:generateContent",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={
            "contents": [{"role": "user", "parts": [{"text": "bonjour"}]}],
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
        },
    )
    assert r.status_code == 400
    assert "tools" in r.json()["error"]["message"]


def test_gemini_400_corps_illisible(gemini_client, auth_token):
    r = gemini_client.post(
        "/v1beta/models/gemini-2.5-pro:generateContent",
        headers={"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"},
        content="corps non json",
    )
    assert r.status_code == 400
    assert "error" in r.json()
