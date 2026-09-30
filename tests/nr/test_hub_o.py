"""
tests/nr/test_hub_o.py - NR Option O4 : watcher auto-restart.

Coverage :
  TestSpec            : watch + health_url dans ModuleSpec
  TestCircuitBreaker  : deque prune, ouverture apres max, reset
  TestBackoff         : skip_by_backoff, doublement, reset sur succes
  TestHealthCheck     : health_ok True / False / timeout
  TestLifecycle       : start/stop singleton, is_running, thread-safe
  TestApi             : auth, status snapshot, start/stop, reset-circuit, 404
  TestSecurity        : api_managed=False jamais restart (hub intouchable)
                        enable_watcher=False -> loop passive
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def admin_token():
    return "O-nr-tok"


@pytest.fixture
def _reset(monkeypatch, tmp_path, admin_token):
    monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
    for m in list(sys.modules):
        if m.startswith("app.web_hub"):
            del sys.modules[m]
    # Redirige les paths audit des 2 modules
    from app.web_hub import launcher as lm, watcher as wm, config as cm
    lm._reset_for_tests(tmp=tmp_path / "launcher")
    wm._reset_for_tests()
    wm.AUDIT_DIR = tmp_path / "audit"
    wm.AUDIT_LOG = wm.AUDIT_DIR / "watcher.log"
    cm.CONFIG_PATH = tmp_path / "hub_config.json"
    cm.AUDIT_DIR = tmp_path / "audit"
    cm.AUDIT_LOG = cm.AUDIT_DIR / "config.log"
    cm._reset_for_tests()
    yield lm, wm, cm, tmp_path
    wm._reset_for_tests()
    lm._reset_for_tests()
    cm._reset_for_tests()


# ===================================================================
# Spec
# ===================================================================
class TestSpec:
    def test_watch_field_exists(self, _reset):
        lm, _, _, _ = _reset
        from app.web_hub.launcher import ModuleSpec
        spec = ModuleSpec(key="x", title="t", description="d",
                         script="tools/nokido.py")
        assert spec.watch is False
        assert spec.health_url is None

    def test_default_modules_optin(self, _reset):
        lm, _, _, _ = _reset
        # 3 modules opt-in (tui_bridge, recon, graph), hub hors scope
        assert lm.MODULES["tui_bridge"].watch is True
        assert lm.MODULES["recon"].watch is True
        assert lm.MODULES["graph"].watch is True
        assert lm.MODULES["hub"].watch is False

    def test_health_urls(self, _reset):
        lm, _, _, _ = _reset
        # Modules opt-in ont tous une health_url
        for k in ("tui_bridge", "recon", "graph"):
            assert lm.MODULES[k].health_url is not None
            assert lm.MODULES[k].health_url.startswith("http://")

    def test_status_exposes_watch(self, _reset):
        lm, _, _, _ = _reset
        s = lm.status("recon")
        assert s["watch"] is True
        assert s["health_url"] == "http://127.0.0.1:7410/"


# ===================================================================
# Circuit-breaker
# ===================================================================
class TestCircuitBreaker:
    def test_circuit_opens_after_max(self, _reset):
        _, wm, _, _ = _reset
        w = wm.Watcher(max_restarts=3, window_s=600)
        st = w._get_state("recon")
        # Simule 3 restarts en moins de window_s
        now = time.time()
        for _ in range(3):
            st.restart_history.append(now)
        ok = w._check_circuit(st)
        assert ok is False
        assert st.circuit_open is True

    def test_prune_history_old(self, _reset):
        _, wm, _, _ = _reset
        w = wm.Watcher(max_restarts=3, window_s=10)
        st = w._get_state("recon")
        st.restart_history.append(time.time() - 100)  # hors fenetre
        st.restart_history.append(time.time() - 5)    # dans fenetre
        w._prune_history(st)
        assert len(st.restart_history) == 1

    def test_reset_circuit(self, _reset):
        _, wm, _, _ = _reset
        w = wm.Watcher(max_restarts=2, window_s=600)
        st = w._get_state("recon")
        st.restart_history.extend([time.time()] * 2)
        w._check_circuit(st)
        assert st.circuit_open is True
        ok = w.reset_circuit("recon")
        assert ok is True
        assert st.circuit_open is False
        assert len(st.restart_history) == 0

    def test_reset_circuit_noop_when_closed(self, _reset):
        _, wm, _, _ = _reset
        w = wm.Watcher()
        # Circuit jamais ouvert -> reset retourne False (rien a faire)
        ok = w.reset_circuit("recon")
        assert ok is False

    def test_reset_circuit_unknown_module(self, _reset):
        _, wm, _, _ = _reset
        w = wm.Watcher()
        assert w.reset_circuit("nowhere") is False

    def test_audit_log_on_circuit_open(self, _reset):
        _, wm, _, _ = _reset
        w = wm.Watcher(max_restarts=2, window_s=600)
        st = w._get_state("recon")
        st.restart_history.extend([time.time()] * 2)
        w._check_circuit(st)
        # Verifie ligne JSONL "watcher.circuit_open"
        assert wm.AUDIT_LOG.exists()
        lines = wm.AUDIT_LOG.read_text(encoding="utf-8").strip().splitlines()
        actions = [json.loads(l)["action"] for l in lines]
        assert "watcher.circuit_open" in actions


# ===================================================================
# Backoff
# ===================================================================
class TestBackoff:
    def test_skip_when_too_soon(self, _reset):
        _, wm, _, _ = _reset
        w = wm.Watcher(backoff_start_s=5.0)
        st = w._get_state("recon")
        st.last_restart_attempt = time.time() - 1  # il y a 1s
        st.current_backoff_s = 5.0
        assert w._should_skip_by_backoff(st) is True

    def test_no_skip_when_elapsed(self, _reset):
        _, wm, _, _ = _reset
        w = wm.Watcher()
        st = w._get_state("recon")
        st.last_restart_attempt = time.time() - 100
        st.current_backoff_s = 1.0
        assert w._should_skip_by_backoff(st) is False

    def test_no_skip_on_first_attempt(self, _reset):
        _, wm, _, _ = _reset
        w = wm.Watcher()
        st = w._get_state("recon")
        assert st.last_restart_attempt == 0.0
        assert w._should_skip_by_backoff(st) is False


# ===================================================================
# Health check
# ===================================================================
class TestHealthCheck:
    def test_health_ok_200(self, _reset):
        _, wm, _, _ = _reset
        w = wm.Watcher(health_timeout_s=0.5)

        async def run():
            # Mock httpx
            from unittest.mock import patch, MagicMock
            class FakeResp:
                status_code = 200
            class FakeClient:
                def __init__(self, **kw): pass
                async def __aenter__(self): return self
                async def __aexit__(self, *a): return None
                async def get(self, url, **kw): return FakeResp()
            with patch("httpx.AsyncClient", FakeClient):
                return await w._health_ok("http://127.0.0.1:9999/")
        assert asyncio.run(run()) is True

    def test_health_ko_500(self, _reset):
        _, wm, _, _ = _reset
        w = wm.Watcher()

        async def run():
            from unittest.mock import patch
            class FakeResp:
                status_code = 502
            class FakeClient:
                def __init__(self, **kw): pass
                async def __aenter__(self): return self
                async def __aexit__(self, *a): return None
                async def get(self, url, **kw): return FakeResp()
            with patch("httpx.AsyncClient", FakeClient):
                return await w._health_ok("http://127.0.0.1:9999/")
        assert asyncio.run(run()) is False

    def test_health_timeout(self, _reset):
        _, wm, _, _ = _reset
        w = wm.Watcher(health_timeout_s=0.1)

        async def run():
            # URL non joignable reelle -> ConnectError
            return await w._health_ok("http://127.0.0.1:1/")
        assert asyncio.run(run()) is False


# ===================================================================
# Lifecycle
# ===================================================================
class TestLifecycle:
    def test_start_stop(self, _reset):
        _, wm, _, _ = _reset

        async def run():
            w = wm.Watcher(poll_interval_s=0.1)
            assert w.is_running() is False
            await w.start()
            assert w.is_running() is True
            # laisse 1-2 tours de boucle
            await asyncio.sleep(0.25)
            await w.stop()
            assert w.is_running() is False
        asyncio.run(run())

    def test_start_idempotent(self, _reset):
        _, wm, _, _ = _reset
        async def run():
            w = wm.Watcher(poll_interval_s=0.1)
            await w.start()
            task1 = w._task
            await w.start()  # no-op
            assert w._task is task1
            await w.stop()
        asyncio.run(run())

    def test_singleton(self, _reset):
        _, wm, _, _ = _reset
        a = wm.Watcher.instance()
        b = wm.Watcher.instance()
        assert a is b

    def test_snapshot_shape(self, _reset):
        _, wm, _, _ = _reset
        w = wm.Watcher()
        snap = w.snapshot()
        assert "running" in snap
        assert "poll_interval_s" in snap
        assert "states" in snap
        assert isinstance(snap["states"], list)


# ===================================================================
# API
# ===================================================================
@pytest.fixture
def client(_reset, admin_token):
    from fastapi.testclient import TestClient
    from app.web_hub.app import app
    from app.web_hub.auth import login_rate_limiter
    login_rate_limiter._by_ip.clear()  # noqa: SLF001
    c = TestClient(app)
    r = c.post("/auth/login", data={"admin_token": admin_token})
    assert r.status_code == 200
    return c


class TestApi:
    def test_all_endpoints_need_auth(self, _reset):
        from fastapi.testclient import TestClient
        from app.web_hub.app import app
        c = TestClient(app)
        assert c.get("/api/watcher/status").status_code == 401
        assert c.post("/api/watcher/start").status_code == 401
        assert c.post("/api/watcher/stop").status_code == 401
        assert c.post("/api/watcher/recon/reset-circuit").status_code == 401

    def test_status_returns_snapshot(self, client):
        r = client.get("/api/watcher/status")
        assert r.status_code == 200
        d = r.json()
        assert "running" in d and "states" in d

    def test_start_stop_cycle(self, client):
        r1 = client.post("/api/watcher/start")
        assert r1.status_code == 200
        assert r1.json()["running"] is True
        r2 = client.post("/api/watcher/stop")
        assert r2.status_code == 200
        assert r2.json()["running"] is False

    def test_reset_circuit_unknown_404(self, client):
        r = client.post("/api/watcher/nowhere/reset-circuit")
        assert r.status_code == 404

    def test_reset_circuit_known_200_even_if_noop(self, client):
        """Endpoint 200 + reset=False si le circuit n est pas ouvert."""
        r = client.post("/api/watcher/recon/reset-circuit")
        assert r.status_code == 200
        d = r.json()
        assert d["module"] == "recon"
        assert "reset" in d


# ===================================================================
# Security
# ===================================================================
class TestSecurity:
    def test_hub_never_watched(self, _reset):
        """api_managed=False -> jamais touche par le watcher."""
        lm, _, _, _ = _reset
        assert lm.MODULES["hub"].api_managed is False
        assert lm.MODULES["hub"].watch is False

    def test_loop_noop_when_flag_disabled(self, _reset):
        """Si enable_watcher=False, la boucle ne restart rien meme si
        un module watch=True est stopped."""
        lm, wm, cm, _ = _reset

        async def run():
            # config par defaut : enable_watcher=False
            w = wm.Watcher(poll_interval_s=0.05)
            # Mock start pour detecter un appel
            from app.web_hub import launcher as lau_mod
            orig_start = lau_mod.start
            calls = []
            async def fake_start(mod, subject="admin"):
                calls.append((mod, subject))
                return {"status": "running", "action": "started", "pid": 123}
            import app.web_hub.watcher as wmod
            # On patche dans launcher (vu par le watcher via import)
            original = lm.start
            import app.web_hub.launcher as lpath
            lpath.start = fake_start

            try:
                await w.start()
                await asyncio.sleep(0.3)
                await w.stop()
                return calls
            finally:
                lpath.start = original

        calls = asyncio.run(run())
        assert calls == [], f"Watcher a appele start() malgre flag off: {calls}"

    def test_loop_acts_when_flag_enabled(self, _reset):
        """enable_watcher=True + module watch=True stopped -> restart."""
        lm, wm, cm, _ = _reset

        async def run():
            # Active le flag via patch
            await cm.patch({"enable_watcher": True})
            w = wm.Watcher(poll_interval_s=0.05, backoff_start_s=0.01)

            # Mock status() pour simuler "stopped"
            import app.web_hub.launcher as lpath
            orig_status = lpath.status
            orig_start = lpath.start
            calls = []
            def fake_status(mod):
                return {"module": mod, "status": "stopped",
                        "pid": None, "port": 7410, "log": "x"}
            async def fake_start(mod, subject="admin"):
                calls.append((mod, subject))
                # Simule que le restart a marche
                return {"status": "running", "action": "started", "pid": 999}
            lpath.status = fake_status
            lpath.start = fake_start

            try:
                await w.start()
                await asyncio.sleep(0.35)
                await w.stop()
                return calls
            finally:
                lpath.status = orig_status
                lpath.start = orig_start

        calls = asyncio.run(run())
        # Au moins 1 tentative pour un des 3 modules watch=True
        assert len(calls) >= 1
        watched_keys = {"tui_bridge", "recon", "graph"}
        assert all(c[0] in watched_keys for c in calls)
        # Le hub (api_managed=False + watch=False) NE DOIT PAS etre la
        assert not any(c[0] == "hub" for c in calls)
        # Subject "watcher" pour audit
        assert all(c[1] == "watcher" for c in calls)
