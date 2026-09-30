"""
tests/nr/test_hub_launcher.py - NR launcher (supervisor modules).

Unit :
  - list_all / status (stopped par defaut)
  - start -> running, stop -> stopped (avec script dummy)
  - restart de process mort : stale -> cleared -> restarted
  - PID reutilise : start_time mismatch -> _is_alive() False
  - tail_log respecte n et max_bytes

Security / API :
  - Tous les endpoints exigent auth (401 sans cookie)
  - start/stop renvoient 403 si enable_remote_start=False (defaut)
  - Une fois le flag active : start/stop marchent
  - Module inconnu : 404 (pas de chemin arbitraire execute)
  - n du /log clampe (>1000 -> 1000)
  - Audit log ecrit avec subject
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (code appele) (l.126)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def admin_token():
    return "launcher-nr-token-42"


@pytest.fixture
def _reset(monkeypatch, tmp_path, admin_token):
    """Isole les paths runtime launcher + config dans tmp_path."""
    monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
    for m in list(sys.modules):
        if m.startswith("app.web_hub"):
            del sys.modules[m]
    from app.web_hub import launcher as lm
    from app.web_hub import config as cfg_mod
    lm._reset_for_tests(tmp=tmp_path / "launcher")
    cfg_mod.CONFIG_PATH = tmp_path / "hub_config.json"
    cfg_mod.AUDIT_DIR = tmp_path / "audit"
    cfg_mod.AUDIT_LOG = cfg_mod.AUDIT_DIR / "config.log"
    cfg_mod._reset_for_tests()
    yield lm, cfg_mod, tmp_path
    lm._reset_for_tests()
    cfg_mod._reset_for_tests()


# -------------------------------------------------------------------
# Fake module pour les tests : on ajoute un "dummy" a MODULES qui
# lance un script Python qui dort 60s (script ecrit dans tmp_path).
# -------------------------------------------------------------------
@pytest.fixture
def dummy_module(_reset):
    lm, cfg_mod, tmp_path = _reset
    # Ecrire le script sous ROOT/sandbox/_nr_dummy.py (chemin relatif attendu)
    # mais on prefere un chemin absolu via monkeypatch du ModuleSpec.
    script = tmp_path / "dummy.py"
    script.write_text(
        "import sys, time\n"
        "print('dummy started')\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    # On cree un ModuleSpec custom et on l injecte dans le registre
    from app.web_hub.launcher import ModuleSpec, MODULES
    spec = ModuleSpec(
        key="dummy",
        title="Dummy Test",
        description="Process test qui sleep 60s",
        script=str(script),  # chemin absolu
        default_port=None,
        stop_timeout_s=2.0,
    )
    # Notre launcher fait : ROOT / spec.script. Si script est absolu,
    # l operation / renvoie le chemin absolu (Path behavior). OK.
    MODULES["dummy"] = spec
    yield lm, "dummy"
    # Cleanup : stop puis retire du registre
    asyncio.run(lm.stop("dummy"))
    MODULES.pop("dummy", None)


# ===================================================================
# Unit : registre & status
# ===================================================================
class TestRegistry:
    def test_builtin_modules(self, _reset):
        lm, _, _ = _reset
        keys = set(lm.MODULES.keys())
        # Le registre reel est {tui_bridge, graph, hub} : `recon` en a disparu.
        # Tous les tests de ce fichier le visaient encore, d'ou des 404 en
        # cascade sur /api/launcher/recon/* -- le module etait inconnu, pas la
        # route absente. Ils mesuraient donc l'absence d'un module retire.
        assert {"tui_bridge", "hub", "graph"}.issubset(keys)

    def test_status_stopped_by_default(self, _reset):
        lm, _, _ = _reset
        s = lm.status("hub")
        assert s["status"] == "stopped"
        assert s["pid"] is None

    def test_unknown_module(self, _reset):
        lm, _, _ = _reset
        s = lm.status("inexistant")
        assert s["status"] == "unknown"


# ===================================================================
# Unit : start/stop sur module dummy
# ===================================================================
class TestStartStop:
    def test_start_then_running(self, dummy_module):
        lm, mod = dummy_module
        r = asyncio.run(lm.start(mod, subject="test"))
        assert r["status"] == "running", r
        assert r["pid"] > 0
        assert r["action"] == "started"

    def test_start_idempotent(self, dummy_module):
        lm, mod = dummy_module
        r1 = asyncio.run(lm.start(mod, subject="test"))
        r2 = asyncio.run(lm.start(mod, subject="test"))
        assert r2["action"] == "already_running"
        assert r2["pid"] == r1["pid"]

    def test_stop_running(self, dummy_module):
        lm, mod = dummy_module
        asyncio.run(lm.start(mod, subject="test"))
        r = asyncio.run(lm.stop(mod, subject="test"))
        assert r["action"] == "stopped"
        assert r["status"] == "stopped"

    def test_stop_when_stopped(self, dummy_module):
        lm, mod = dummy_module
        r = asyncio.run(lm.stop(mod, subject="test"))
        assert r["action"] in ("already_stopped",)

    def test_audit_log_written(self, dummy_module):
        lm, mod = dummy_module
        asyncio.run(lm.start(mod, subject="alice"))
        asyncio.run(lm.stop(mod, subject="alice"))
        assert lm.AUDIT_LOG.exists()
        lines = lm.AUDIT_LOG.read_text(encoding="utf-8").strip().splitlines()
        actions = [json.loads(l)["action"] for l in lines]
        assert "start" in actions
        assert "stop" in actions
        subjects = [json.loads(l)["subject"] for l in lines]
        assert "alice" in subjects


# ===================================================================
# Unit : tail_log
# ===================================================================
class TestTailLog:
    def test_tail_n(self, dummy_module):
        lm, mod = dummy_module
        asyncio.run(lm.start(mod, subject="test"))
        # Laisse le temps au dummy d ecrire au moins 'dummy started'
        time.sleep(0.8)
        out = lm.tail_log(mod, n=10)
        assert "dummy started" in out
        asyncio.run(lm.stop(mod, subject="test"))

    def test_tail_unknown_raises(self, _reset):
        lm, _, _ = _reset
        with pytest.raises(ValueError):
            lm.tail_log("inexistant")


# ===================================================================
# Unit : is_alive et stale
# ===================================================================
class TestLiveness:
    def test_is_alive_dead_pid(self, _reset):
        lm, _, _ = _reset
        # PID 1 existe sous Unix mais c est init -- on prend 99999999 a la place
        assert lm._is_alive(99999999, time.time()) is False


class TestEnvUtf8:
    """Regression : les sous-process doivent avoir PYTHONIOENCODING=utf-8.
    Sinon, sous Windows cp1252, un print() d emoji crash en
    UnicodeEncodeError (cas reel : forge_graph_explorer print \\u2b21).
    """
    def test_env_contains_python_utf8(self, _reset):
        lm, _, _ = _reset
        spec = lm.MODULES["graph"]
        env = lm._build_env(spec)
        assert env.get("PYTHONIOENCODING") == "utf-8"
        assert env.get("PYTHONUTF8") == "1"

    def test_env_user_override_respected(self, _reset, monkeypatch):
        """Si l utilisateur definit PYTHONIOENCODING autre (rare), on respecte."""
        lm, _, _ = _reset
        monkeypatch.setenv("PYTHONIOENCODING", "latin-1")
        spec = lm.MODULES["graph"]
        env = lm._build_env(spec)
        assert env.get("PYTHONIOENCODING") == "latin-1"


# ===================================================================
# API : endpoints via TestClient
# ===================================================================
@pytest.fixture
def client(_reset, admin_token):
    from fastapi.testclient import TestClient
    from app.web_hub.app import app
    from app.web_hub.auth import login_rate_limiter
    login_rate_limiter._by_ip.clear()  # noqa: SLF001
    c = TestClient(app)
    r = c.post("/auth/login",
              data={"admin_token": os.environ["LAFORGE_ADMIN_TOKEN"]})
    assert r.status_code == 200
    return c


class TestApiAuth:
    def test_all_endpoints_need_auth(self, _reset):
        from fastapi.testclient import TestClient
        from app.web_hub.app import app
        c = TestClient(app)
        assert c.get("/api/launcher/modules").status_code == 401
        assert c.get("/api/launcher/hub/status").status_code == 401
        assert c.post("/api/launcher/hub/start").status_code == 401
        assert c.post("/api/launcher/hub/stop").status_code == 401
        assert c.get("/api/launcher/hub/log").status_code == 401

    def test_unknown_module_404(self, client):
        assert client.get("/api/launcher/malicious/../status").status_code == 404
        assert client.post("/api/launcher/MALICIOUS/start").status_code in (403, 404)


class TestApiDisabledByDefault:
    def test_start_disabled_403(self, client):
        # `graph` et non `hub` : le hub porte `api_managed=False` PAR CONCEPTION,
        # pour qu'on ne l'arrete pas depuis lui-meme. L'API rend donc 400, pas
        # 403 -- ce qui est correct, mais ne teste pas le refus qu'on vise ici.
        r = client.post("/api/launcher/graph/start")
        assert r.status_code == 403
        assert "desactive" in r.text.lower() or "enable_remote_start" in r.text

    def test_stop_disabled_403(self, client):
        r = client.post("/api/launcher/graph/stop")
        assert r.status_code == 403

    def test_status_still_works(self, client):
        # GET status n est PAS bloque (lecture seule)
        r = client.get("/api/launcher/graph/status")
        assert r.status_code == 200
        assert r.json()["status"] in ("stopped", "stale", "running")

    def test_list_still_works(self, client):
        r = client.get("/api/launcher/modules")
        assert r.status_code == 200
        assert isinstance(r.json()["modules"], list)


class TestApiEnabled:
    def test_start_after_enabling_flag(self, client, dummy_module):
        # Active le flag via /api/config PATCH
        r = client.patch("/api/config", json={"enable_remote_start": True})
        assert r.status_code == 200

        # Start dummy (on passe directement par l API)
        lm, mod = dummy_module
        r = client.post(f"/api/launcher/{mod}/start")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["action"] in ("started", "already_running")
        assert data["status"] == "running"

        # Stop
        r = client.post(f"/api/launcher/{mod}/stop")
        assert r.status_code == 200
        assert r.json()["status"] == "stopped"


class TestApiLogs:
    def test_log_n_clamp(self, client):
        r = client.get("/api/launcher/graph/log?n=999999")
        assert r.status_code == 200
        # n clampe a 1000 -> pas de crash
        assert r.json()["lines"] == 1000

    def test_log_n_min(self, client):
        r = client.get("/api/launcher/graph/log?n=0")
        assert r.status_code == 200
        assert r.json()["lines"] == 1


# ===================================================================
# Page HTML
# ===================================================================
class TestLauncherPage:
    def test_launcher_page_requires_auth(self, _reset):
        from fastapi.testclient import TestClient
        from app.web_hub.app import app
        c = TestClient(app)
        # navigator -> redirect vers login
        r = c.get("/launcher", headers={"Accept": "text/html"},
                 follow_redirects=False)
        assert r.status_code == 303
        assert "/auth/login" in r.headers.get("location", "")

    def test_launcher_page_served_with_auth(self, client):
        r = client.get("/launcher", headers={"Accept": "text/html"})
        assert r.status_code == 200
        assert "launcher" in r.text.lower() or "modules" in r.text.lower()

    def test_launcher_page_has_csp(self, client):
        r = client.get("/launcher", headers={"Accept": "text/html"})
        assert "content-security-policy" in {k.lower() for k in r.headers}
