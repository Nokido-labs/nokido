"""
tests/nr/test_hub_ws_auth.py - NR pour auth WebSocket sur ReverseProxy.

Le middleware HTTP ne voit pas les WS -> securite-in-depth dans le proxy.
Coverage :
  - extract_token_from_ws_scope : cookie / subprotocol / aucun
  - Query string rejetee (OWASP : pas de token en URL)
  - authorize_ws : fail_closed, enabled=False, token invalide, token valide
  - E2E : proxy WS + backend echo ; refus anonyme (code 4401), accepte avec cookie
"""
from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# -------------------------------------------------------------------
# Utils
# -------------------------------------------------------------------
def _headers(d: dict) -> list:
    return [(k.encode("latin-1"), v.encode("latin-1")) for k, v in d.items()]


def _scope(headers: dict, subprotocols=None, query: str = "") -> dict:
    return {
        "type": "websocket",
        "headers": _headers(headers),
        "subprotocols": subprotocols or [],
        "query_string": query.encode(),
        "path": "/",
        "root_path": "/tui",
    }


@pytest.fixture
def admin_token():
    return "ws-auth-test-token-42"


@pytest.fixture
def auth_cfg(monkeypatch, admin_token):
    monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
    for m in list(sys.modules):
        if m.startswith("app.web_hub.auth"):
            del sys.modules[m]
    from app.web_hub.auth import AuthConfig
    return AuthConfig.from_env()


# -------------------------------------------------------------------
# Token extraction (unit)
# -------------------------------------------------------------------
class TestExtractToken:
    def test_cookie(self):
        from app.web_hub.auth import extract_token_from_ws_scope
        sc = _scope({"cookie": "lf_session=abc.def.ghi; other=xyz"})
        assert extract_token_from_ws_scope(sc) == "abc.def.ghi"

    def test_cookie_missing(self):
        from app.web_hub.auth import extract_token_from_ws_scope
        sc = _scope({"cookie": "other=xyz"})
        assert extract_token_from_ws_scope(sc) is None

    def test_subprotocol_lf_jwt(self):
        from app.web_hub.auth import extract_token_from_ws_scope
        sc = _scope({}, subprotocols=["lf-jwt", "mytoken"])
        assert extract_token_from_ws_scope(sc) == "mytoken"

    def test_subprotocol_header_raw(self):
        """Certains clients ne fournissent pas scope['subprotocols']
        mais mettent tout dans le header directement."""
        from app.web_hub.auth import extract_token_from_ws_scope
        sc = _scope({"sec-websocket-protocol": "lf-jwt, tok-xyz"})
        assert extract_token_from_ws_scope(sc) == "tok-xyz"

    def test_cookie_wins_over_subprotocol(self):
        """Si les 2 sont presents, cookie prioritaire."""
        from app.web_hub.auth import extract_token_from_ws_scope
        sc = _scope({"cookie": "lf_session=cook"}, subprotocols=["lf-jwt", "proto"])
        assert extract_token_from_ws_scope(sc) == "cook"

    def test_query_string_ignored(self):
        """SECURITE : token dans URL query string NE DOIT PAS etre accepte."""
        from app.web_hub.auth import extract_token_from_ws_scope
        sc = _scope({}, query="token=should-be-ignored&other=x")
        assert extract_token_from_ws_scope(sc) is None

    def test_nothing(self):
        from app.web_hub.auth import extract_token_from_ws_scope
        assert extract_token_from_ws_scope(_scope({})) is None

    def test_malformed_cookie_value(self):
        from app.web_hub.auth import extract_token_from_ws_scope
        sc = _scope({"cookie": "lf_session="})  # empty value
        assert extract_token_from_ws_scope(sc) is None


# -------------------------------------------------------------------
# authorize_ws (unit)
# -------------------------------------------------------------------
class TestAuthorizeWs:
    def test_valid_token_accepted(self, auth_cfg):
        from app.web_hub.auth import authorize_ws, issue_token
        tok = issue_token(auth_cfg, subject="admin")
        sc = _scope({"cookie": f"lf_session={tok}"})
        payload = authorize_ws(auth_cfg, sc)
        assert payload is not None
        assert payload["sub"] == "admin"

    def test_no_token_refused(self, auth_cfg):
        from app.web_hub.auth import authorize_ws
        sc = _scope({})
        assert authorize_ws(auth_cfg, sc) is None

    def test_garbage_token_refused(self, auth_cfg):
        from app.web_hub.auth import authorize_ws
        sc = _scope({"cookie": "lf_session=not.a.jwt"})
        assert authorize_ws(auth_cfg, sc) is None

    def test_fail_closed_refuses_even_with_token(self, monkeypatch):
        """Si LAFORGE_ADMIN_TOKEN n est pas set : refuse TOUT."""
        monkeypatch.delenv("LAFORGE_ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
        for m in list(sys.modules):
            if m.startswith("app.web_hub.auth"):
                del sys.modules[m]
        from app.web_hub.auth import AuthConfig, authorize_ws
        cfg = AuthConfig.from_env()
        sc = _scope({"cookie": "lf_session=whatever"})
        assert authorize_ws(cfg, sc) is None

    def test_disabled_bypass(self, monkeypatch):
        """Auth explicitement off (dev) : authorize_ws retourne payload bypass."""
        monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "0")
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "any")
        for m in list(sys.modules):
            if m.startswith("app.web_hub.auth"):
                del sys.modules[m]
        from app.web_hub.auth import AuthConfig, authorize_ws
        cfg = AuthConfig.from_env()
        assert authorize_ws(cfg, _scope({})) is not None


# -------------------------------------------------------------------
# E2E : backend echo + proxy WS avec auth_cfg
# -------------------------------------------------------------------
def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]
    s.close(); return p


@pytest.fixture
def ws_stack(monkeypatch, admin_token):
    """Stack complete : backend echo + proxy en process, avec AUTH_CFG."""
    monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
    for m in list(sys.modules):
        if m.startswith("app.web_hub"):
            del sys.modules[m]

    import websockets
    from websockets.asyncio.server import serve as ws_serve
    import uvicorn
    from fastapi import FastAPI
    from app.web_hub.proxy import ReverseProxy
    from app.web_hub.auth import AuthConfig, issue_token

    backend_port = _free_port()
    hub_port = _free_port()
    cfg = AuthConfig.from_env()
    token = issue_token(cfg, subject="admin")

    stop_event = threading.Event()

    async def echo(ws):
        try:
            async for m in ws:
                await ws.send(m)
        except Exception:
            pass

    def backend_thread():
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        async def main():
            async with ws_serve(echo, "127.0.0.1", backend_port, max_size=None):
                while not stop_event.is_set():
                    await asyncio.sleep(0.05)
        loop.run_until_complete(main())

    t_back = threading.Thread(target=backend_thread, daemon=True)
    t_back.start()

    hub = FastAPI()
    hub.mount("/ws", ReverseProxy(f"http://127.0.0.1:{backend_port}",
                                 auth_cfg=cfg))

    def hub_thread():
        uvicorn.run(hub, host="127.0.0.1", port=hub_port,
                    log_level="error", access_log=False)

    t_hub = threading.Thread(target=hub_thread, daemon=True)
    t_hub.start()
    time.sleep(1.5)
    yield {"hub_port": hub_port, "token": token}
    stop_event.set()


class TestE2E:
    def test_anonymous_refused(self, ws_stack):
        """Pas de cookie ni subprotocol -> 4401 (code WS >=4000 = app-level)."""
        import websockets
        from websockets.asyncio.client import connect as ws_client
        from websockets.exceptions import InvalidStatus, ConnectionClosed

        uri = f"ws://127.0.0.1:{ws_stack['hub_port']}/ws/"

        async def run():
            try:
                async with ws_client(uri, open_timeout=4) as ws:
                    # Si on arrive la c est que le handshake est passe -- not expected
                    # Certains clients notifient le close a la 1re frame
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    except Exception:
                        pass
                    return "connected-unexpectedly"
            except (InvalidStatus, ConnectionClosed) as e:
                return f"refused: {type(e).__name__}: {getattr(e, 'rcvd', None) or getattr(e, 'code', None)}"
            except Exception as e:
                return f"exc: {type(e).__name__}: {e}"

        r = asyncio.run(run())
        assert "refused" in r or "exc" in r or "connected-unexpectedly" not in r, \
            f"expected refusal, got {r!r}"

    def test_cookie_accepted(self, ws_stack):
        """Avec cookie lf_session valide, echo fonctionne."""
        from websockets.asyncio.client import connect as ws_client

        uri = f"ws://127.0.0.1:{ws_stack['hub_port']}/ws/"
        token = ws_stack["token"]

        async def run():
            async with ws_client(
                uri, open_timeout=5,
                additional_headers={"Cookie": f"lf_session={token}"},
            ) as ws:
                await ws.send("ping")
                r = await asyncio.wait_for(ws.recv(), timeout=3)
                return r

        r = asyncio.run(run())
        assert r == "ping"

    def test_subprotocol_accepted(self, ws_stack):
        """Via Sec-WebSocket-Protocol = lf-jwt, <token>."""
        from websockets.asyncio.client import connect as ws_client

        uri = f"ws://127.0.0.1:{ws_stack['hub_port']}/ws/"
        token = ws_stack["token"]

        async def run():
            async with ws_client(
                uri, open_timeout=5,
                subprotocols=["lf-jwt", token],
            ) as ws:
                await ws.send("hello-subproto")
                return await asyncio.wait_for(ws.recv(), timeout=3)

        r = asyncio.run(run())
        assert r == "hello-subproto"

    def test_tampered_cookie_refused(self, ws_stack):
        """Token tamperise -> refus propre."""
        from websockets.asyncio.client import connect as ws_client
        from websockets.exceptions import InvalidStatus, ConnectionClosed

        uri = f"ws://127.0.0.1:{ws_stack['hub_port']}/ws/"
        tamp = ws_stack["token"][:-3] + "AAA"

        async def run():
            try:
                async with ws_client(
                    uri, open_timeout=4,
                    additional_headers={"Cookie": f"lf_session={tamp}"},
                ) as ws:
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=2)
                    except Exception:
                        pass
                    return "connected"
            except (InvalidStatus, ConnectionClosed):
                return "refused"
            except Exception as e:
                return f"exc: {type(e).__name__}"

        r = asyncio.run(run())
        assert r != "connected", f"tampered token should be refused, got {r!r}"
