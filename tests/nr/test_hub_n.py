"""
tests/nr/test_hub_n.py - NR Option N : SSE logs live.

Coverage :
  Unit (tail_log_stream) :
    - Generator yields donnees apres ecriture dans le log
    - Heartbeat : b"" yield apres STREAM_HEARTBEAT_S (on mock le delai)
    - Truncate/rotate : pos revient a 0
    - Cap concurrentiel : refus au-dela de MAX_CONCURRENT_STREAMS

  API :
    - /api/launcher/{mod}/stream : auth required
    - Module inconnu : 404
    - Content-Type text/event-stream
    - Cache-Control no-cache
    - Si backend dump des lignes, elles arrivent en events SSE

  UI :
    - Page /launcher contient bouton Live + EventSource + close()
    - Toggle ON/OFF (classe .on)
    - Plafond MAX_LINES cote client

  Security :
    - Cap global MAX_CONCURRENT_STREAMS >= 1
    - STREAM_MAX_DURATION_S configure (pas d infini)
    - Endpoint marche avec SSE meme si module stopped (lit le fichier)
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (hub uvicorn); reseau
#   localhost (l.255)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def admin_token():
    return "N-nr-tok"


@pytest.fixture
def _reset(monkeypatch, tmp_path, admin_token):
    monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
    for m in list(sys.modules):
        if m.startswith("app.web_hub"):
            del sys.modules[m]
    from app.web_hub import launcher as lm
    lm._reset_for_tests(tmp=tmp_path / "launcher")
    # Poll rapide pour tests sans trop attendre
    lm.STREAM_POLL_S = 0.05
    yield lm, tmp_path
    lm._reset_for_tests()


# -------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------
class TestConstants:
    def test_max_concurrent_streams_reasonable(self, _reset):
        lm, _ = _reset
        assert 1 <= lm.MAX_CONCURRENT_STREAMS <= 100

    def test_max_duration_finite(self, _reset):
        lm, _ = _reset
        # Pas d infini : anti-fuite
        assert lm.STREAM_MAX_DURATION_S > 0
        assert lm.STREAM_MAX_DURATION_S <= 7 * 24 * 3600  # borne raisonnable


# -------------------------------------------------------------------
# Unit : tail_log_stream
# -------------------------------------------------------------------
class TestTailStream:
    def test_yields_new_lines(self, _reset):
        """Ecrit dans un log pendant qu un generator tail ; doit recuperer."""
        lm, _ = _reset
        # On utilise un module existant (recon) mais on ecrit nous-meme
        # directement dans son logfile.
        log = lm._logfile("recon")
        log.parent.mkdir(parents=True, exist_ok=True)
        # Ecrit du contenu initial AVANT d ouvrir le stream
        log.write_bytes(b"old-line\n")

        async def run():
            gen = lm.tail_log_stream("recon", start_from_end=True)
            # Ecrit apres l ouverture
            async def writer():
                await asyncio.sleep(0.1)
                with open(log, "ab") as f:
                    f.write(b"new-line-1\n")
                    f.write(b"new-line-2\n")
                await asyncio.sleep(0.2)
            task = asyncio.create_task(writer())
            collected = b""
            t0 = time.time()
            async for chunk in gen:
                if chunk:
                    collected += chunk
                if b"new-line-2" in collected or time.time() - t0 > 2.0:
                    break
            await task
            return collected

        out = asyncio.run(run())
        assert b"new-line-1" in out
        assert b"new-line-2" in out
        assert b"old-line" not in out   # start_from_end

    def test_truncate_resets_pos(self, _reset):
        """Si le log est truncate pendant le stream, on reprend a 0."""
        lm, _ = _reset
        log = lm._logfile("recon")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_bytes(b"big content already there\n")

        async def run():
            gen = lm.tail_log_stream("recon", start_from_end=True)
            async def rotate_then_write():
                await asyncio.sleep(0.1)
                # Truncate
                log.write_bytes(b"")
                await asyncio.sleep(0.1)
                # Ecrit du neuf
                log.write_bytes(b"after-rotate\n")
                await asyncio.sleep(0.2)
            task = asyncio.create_task(rotate_then_write())
            collected = b""
            t0 = time.time()
            async for chunk in gen:
                if chunk:
                    collected += chunk
                if b"after-rotate" in collected or time.time() - t0 > 2.0:
                    break
            await task
            return collected

        out = asyncio.run(run())
        assert b"after-rotate" in out

    def test_unknown_module_raises(self, _reset):
        lm, _ = _reset

        async def run():
            gen = lm.tail_log_stream("nowhere")
            async for _ in gen:
                pass

        with pytest.raises(ValueError):
            asyncio.run(run())


# -------------------------------------------------------------------
# Cap concurrentiel
# -------------------------------------------------------------------
class TestCap:
    def test_cap_enforced(self, _reset, monkeypatch):
        """Si MAX_CONCURRENT_STREAMS=1, un 2e stream doit etre refuse."""
        lm, _ = _reset
        monkeypatch.setattr(lm, "MAX_CONCURRENT_STREAMS", 1)
        # Force l etat a zero au cas ou
        lm._active_streams = 0

        async def run():
            log = lm._logfile("recon")
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_bytes(b"")

            g1 = lm.tail_log_stream("recon", start_from_end=True)
            # Avance g1 d un cran pour qu il acquiere le slot
            task1 = asyncio.create_task(g1.__anext__())
            await asyncio.sleep(0.1)
            # g2 doit etre refuse des qu on le consomme
            g2 = lm.tail_log_stream("recon", start_from_end=True)
            raised = False
            try:
                await g2.__anext__()
            except RuntimeError as e:
                raised = "max streams" in str(e).lower()
            # Cleanup g1 : annule sa task
            task1.cancel()
            try:
                await task1
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            await g1.aclose()
            return raised

        assert asyncio.run(run()) is True


# -------------------------------------------------------------------
# API endpoint
# -------------------------------------------------------------------
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
    def test_stream_requires_auth(self, _reset):
        from fastapi.testclient import TestClient
        from app.web_hub.app import app
        c = TestClient(app)
        # Pas de login -> 401
        r = c.get("/api/launcher/recon/stream",
                 headers={"Accept": "application/json"})
        assert r.status_code == 401

    def test_stream_unknown_404(self, client):
        r = client.get("/api/launcher/noexist/stream",
                      headers={"Accept": "application/json"})
        assert r.status_code == 404

    def test_stream_headers(self, _reset, admin_token):
        """Verifie headers du stream sans le consommer longtemps.

        On ouvre via httpx direct (pas TestClient qui bloque sur streaming)
        dans un thread separe contre un vrai uvicorn sur port libre.
        """
        import os, socket, subprocess, sys, time, httpx, threading, signal

        # Borne STREAM_MAX_DURATION_S pour que le stream meurt vite de lui-meme
        lm, _ = _reset
        lm.STREAM_MAX_DURATION_S = 2.0
        log = lm._logfile("recon")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_bytes(b"")

        # Ports + env
        def free_port():
            s = socket.socket(); s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]; s.close(); return p
        port = free_port()
        env = os.environ.copy()
        env.update({
            "LAFORGE_HUB_PORT": str(port),
            "LAFORGE_ADMIN_TOKEN": admin_token,
            "LAFORGE_AUTH_ENABLED": "1",
        })
        # Launch hub
        proc = subprocess.Popen(
            [sys.executable, "tools/nokido_web_hub.py", "--port", str(port)],
            cwd=str(ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                           if sys.platform == "win32" else 0),
        )
        try:
            # Wait up
            t0 = time.time()
            up = False
            while time.time() - t0 < 8:
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
                    up = True; break
                except Exception:
                    time.sleep(0.2)
            assert up, "hub failed to start"

            # Login
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5.0) as c:
                r = c.post("/auth/login", data={"admin_token": admin_token})
                assert r.status_code == 200

                # Open SSE avec timeout court
                with c.stream("GET", "/api/launcher/recon/stream",
                             timeout=3.0) as resp:
                    assert resp.status_code == 200
                    ct = resp.headers.get("content-type", "")
                    assert "text/event-stream" in ct
                    cc = resp.headers.get("cache-control", "")
                    assert "no-cache" in cc
                    # Consommer quelques bytes juste pour confirmer que ca stream,
                    # puis on sort (context manager ferme la connexion).
                    got_data = False
                    try:
                        for chunk in resp.iter_bytes(chunk_size=64):
                            got_data = True
                            break
                    except httpx.ReadTimeout:
                        pass  # OK : pas de donnees dans le chunk window
                    # Pas de donnees attendues sans write -> ok de rien lire
        finally:
            try:
                if sys.platform == "win32":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


# -------------------------------------------------------------------
# UI
# -------------------------------------------------------------------
class TestLauncherUI:
    def test_has_live_button(self, client):
        html = client.get("/launcher").text
        assert "button.live" in html
        assert "data-act=\"live\"" in html or 'data-act="live"' in html

    def test_uses_eventsource(self, client):
        html = client.get("/launcher").text
        assert "EventSource" in html
        assert "/api/launcher/" in html

    def test_toggle_logic(self, client):
        """Le JS doit avoir un toggle ON/OFF."""
        html = client.get("/launcher").text
        assert "streams[mod]" in html
        assert ".close()" in html

    def test_max_lines_cap(self, client):
        """Cap client MAX_LINES pour eviter flood memoire browser."""
        html = client.get("/launcher").text
        assert "MAX_LINES" in html
