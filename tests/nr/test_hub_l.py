"""
tests/nr/test_hub_l.py - NR Option L : feature flags dashboard + entrypoint.

Coverage :
  L1 - Dashboard :
    - data-feature-key sur chaque card
    - applyFeatureFlags JS present
    - lien /launcher dans la nav
  L1 - Hub API :
    - api_managed=False (hub) refuse start via API
    - api_managed=False refuse stop via API
  L2 - Entrypoint CLI :
    - status rc=0
    - doctor rc<=1 (0 ou 1 selon env)
    - argparse rejette commandes inconnues
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.110)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# -------------------------------------------------------------------
# Dashboard HTML
# -------------------------------------------------------------------
@pytest.fixture
def client(monkeypatch):
    """TestClient authentifie admin."""
    monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "L-nr-tok")
    monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
    for m in list(sys.modules):
        if m.startswith("app.web_hub"):
            del sys.modules[m]
    from fastapi.testclient import TestClient
    from app.web_hub.app import app
    from app.web_hub.auth import login_rate_limiter
    login_rate_limiter._by_ip.clear()  # noqa: SLF001
    c = TestClient(app)
    r = c.post("/auth/login", data={"admin_token": "L-nr-tok"})
    assert r.status_code == 200
    return c


class TestDashboardFeatureFlags:
    def test_has_data_feature_key(self, client):
        html = client.get("/").text
        # Chaque card de service doit avoir data-feature-key
        for svc in ("ctf", "recon", "graph", "tui"):
            assert f'data-feature-key="feature_{svc}"' in html, \
                f"card {svc} manque data-feature-key"

    def test_js_apply_feature_flags(self, client):
        html = client.get("/").text
        assert "applyFeatureFlags" in html
        assert "/api/config" in html  # le JS fetch la config
        assert "data-feature-key" in html  # selector utilise

    def test_nav_link_launcher(self, client):
        html = client.get("/").text
        assert 'href="/launcher"' in html

    def test_refresh_all_startup(self, client):
        html = client.get("/").text
        # refreshAll() est appele au demarrage et en interval
        assert "refreshAll" in html


# -------------------------------------------------------------------
# API : api_managed=False refuse start/stop du hub
# -------------------------------------------------------------------
class TestHubApiManaged:
    def test_start_hub_via_api_400(self, client):
        # Meme avec flag active, le hub refuse
        client.patch("/api/config", json={"enable_remote_start": True})
        r = client.post("/api/launcher/hub/start")
        assert r.status_code == 400
        assert "CLI" in r.text or "api_managed" in r.text or "managed" in r.text

    def test_stop_hub_via_api_400(self, client):
        client.patch("/api/config", json={"enable_remote_start": True})
        r = client.post("/api/launcher/hub/stop")
        assert r.status_code == 400

    def test_hub_status_still_readable(self, client):
        """GET status est lecture seule, doit marcher."""
        r = client.get("/api/launcher/hub/status")
        assert r.status_code == 200
        assert r.json()["module"] == "hub"

    def test_hub_in_list(self, client):
        r = client.get("/api/launcher/modules")
        mods = {m["module"] for m in r.json()["modules"]}
        assert "hub" in mods


# -------------------------------------------------------------------
# Entrypoint CLI
# -------------------------------------------------------------------
def _run_nokido(args: list, timeout: int = 15, env_extra: dict | None = None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "tools/nokido.py", *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=timeout,
        env=env,
    )


class TestEntrypoint:
    def test_status_returns_0(self):
        r = _run_nokido(["status"])
        assert r.returncode == 0, r.stderr
        assert "Nokido modules" in r.stdout

    def test_doctor_reports_deps(self):
        r = _run_nokido(["doctor"])
        # 0 si tout OK, 1 si WARN/MISSING : on accepte les 2 tant qu on n a
        # pas ecrit en crash
        assert r.returncode in (0, 1), r.stderr
        assert "fastapi" in r.stdout
        assert "port 7400" in r.stdout

    def test_unknown_cmd_fails(self):
        r = _run_nokido(["wreak-havoc"])
        assert r.returncode != 0
        assert "invalid choice" in (r.stderr + r.stdout).lower()

    def test_help_has_all_commands(self):
        r = _run_nokido(["--help"])
        assert r.returncode == 0
        out = r.stdout.lower()
        for cmd in ("up", "down", "status", "hub", "open", "logs", "doctor"):
            assert cmd in out


# -------------------------------------------------------------------
# ModuleSpec : api_managed metadata
# -------------------------------------------------------------------
class TestApiManagedFlag:
    def test_hub_not_api_managed(self, monkeypatch):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "x")
        for m in list(sys.modules):
            if m.startswith("app.web_hub"):
                del sys.modules[m]
        from app.web_hub.launcher import MODULES
        assert "hub" in MODULES
        assert MODULES["hub"].api_managed is False

    def test_others_api_managed(self, monkeypatch):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "x")
        for m in list(sys.modules):
            if m.startswith("app.web_hub"):
                del sys.modules[m]
        from app.web_hub.launcher import MODULES
        for k in ("tui_bridge", "recon", "graph"):
            assert MODULES[k].api_managed is True, f"{k} devrait etre api_managed"
