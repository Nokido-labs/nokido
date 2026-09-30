"""
tests/nr/test_hub_m.py - NR Option M : open_path + bouton Ouvrir.

Coverage :
  Unit :
    - ModuleSpec.open_path est optionnel (default None)
    - status() expose open_path (valeur ou None)
    - Les 4 modules declarent un open_path

  API :
    - GET /api/launcher/modules retourne open_path pour chaque module
    - GET /api/launcher/{mod}/status retourne open_path

  UI :
    - Page /launcher contient la CSS .open, le texte "Ouvrir", "CLI only"
    - Page contient bien la logique api_managed cote JS
    - XSS : si un open_path contenait du HTML il serait escape (esc())

  Security :
    - open_path est defini par ModuleSpec en dur : pas d input utilisateur
    - URL malicieuse javascript: NON exposee (aucune dans MODULES)
    - Cross-mod : open_path toujours sous /<slug>/ ou /
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# Seule URL ABSOLUE admise pour un open_path : la BOUCLE LOCALE, port explicite, racine, et rien d'autre (fullmatch).
# Decision owner du 2026-09-25 (choix A, opencode) : son interface charge ses ressources en chemins absolus, un
# proxy a prefixe sous :7400 la casse -- `launcher.MODULES["opencode"].open_path` vaut donc `http://127.0.0.1:4096/`.
# Ce test n'avait pas suivi (rouge en CI de reference 706c68e4a). Tout autre hote, chemin ou schema reste refuse.
_BOUCLE_LOCALE = re.compile(r"http://(?:127\.0\.0\.1|localhost):\d{2,5}/")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "M-nr-tok")
    monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
    for m in list(sys.modules):
        if m.startswith("app.web_hub"):
            del sys.modules[m]
    from fastapi.testclient import TestClient
    from app.web_hub.app import app
    from app.web_hub.auth import login_rate_limiter
    login_rate_limiter._by_ip.clear()  # noqa: SLF001
    c = TestClient(app)
    r = c.post("/auth/login", data={"admin_token": "M-nr-tok"})
    assert r.status_code == 200
    return c


# -------------------------------------------------------------------
# Unit : ModuleSpec + status()
# -------------------------------------------------------------------
class TestOpenPathSpec:
    def test_module_spec_has_open_path_field(self, monkeypatch):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "x")
        for m in list(sys.modules):
            if m.startswith("app.web_hub"):
                del sys.modules[m]
        from app.web_hub.launcher import ModuleSpec
        # Construction sans open_path -> default None
        spec = ModuleSpec(key="x", title="t", description="d",
                         script="tools/nokido.py")
        assert spec.open_path is None

    def test_all_builtin_modules_have_open_path(self, monkeypatch):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "x")
        for m in list(sys.modules):
            if m.startswith("app.web_hub"):
                del sys.modules[m]
        from app.web_hub.launcher import MODULES
        expected = {
            # `recon` a ete retire du registre : l'attendre ici faisait echouer
            # un test sur un module qui n'existe plus, pas sur un open_path
            # manquant. Les trois modules reels sont verifies.
            "tui_bridge": "/tui/",
            "graph":      "/graph/",
            "hub":        "/",
        }
        for key, exp in expected.items():
            assert key in MODULES
            assert MODULES[key].open_path == exp, \
                f"{key}: expected {exp}, got {MODULES[key].open_path}"

    def test_status_exposes_open_path(self, monkeypatch):
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "x")
        for m in list(sys.modules):
            if m.startswith("app.web_hub"):
                del sys.modules[m]
        from app.web_hub.launcher import status
        s = status("tui_bridge")
        assert "open_path" in s
        assert s["open_path"] == "/tui/"

    def test_all_open_paths_are_safe(self, monkeypatch):
        """Security : aucun open_path ne doit contenir de schema externe
        ou de javascript: URI."""
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "x")
        for m in list(sys.modules):
            if m.startswith("app.web_hub"):
                del sys.modules[m]
        from app.web_hub.launcher import MODULES
        for k, spec in MODULES.items():
            if spec.open_path is None or _BOUCLE_LOCALE.fullmatch(spec.open_path):
                continue
            assert spec.open_path.startswith("/"), f"{k}: open_path doit etre relatif"
            assert "://" not in spec.open_path, f"{k}: URL absolue interdite"
            low = spec.open_path.lower()
            for bad in ("javascript:", "data:", "vbscript:", "file:"):
                assert bad not in low, f"{k}: URI scheme dangereux {bad}"


    def test_seule_la_boucle_locale_exacte_est_admise_en_absolu(self):
        admis = ("http://127.0.0.1:4096/", "http://localhost:7420/")
        refuses = ("http://evil.example:80/", "https://127.0.0.1:4096/", "http://127.0.0.1.evil.example:80/",
                   "http://127.0.0.1:4096/autre", "http://127.0.0.1:4096/?redir=x", "http://127.0.0.1/",
                   "//127.0.0.1:4096/", "http://[::1]:4096/")
        assert all(_BOUCLE_LOCALE.fullmatch(p) for p in admis)
        assert not any(_BOUCLE_LOCALE.fullmatch(p) for p in refuses)


# -------------------------------------------------------------------
# API
# -------------------------------------------------------------------
class TestApi:
    def test_list_includes_open_path(self, client):
        r = client.get("/api/launcher/modules")
        assert r.status_code == 200
        mods = r.json()["modules"]
        for m in mods:
            assert "open_path" in m
            assert "api_managed" in m

    def test_status_includes_open_path(self, client):
        # `graph` et non `hub` : ce test veut un module GERE par l'API, or le hub
        # porte `api_managed=False` par conception pour se proteger lui-meme --
        # un cas deja couvert par `test_hub_api_managed_false` juste en dessous.
        r = client.get("/api/launcher/graph/status")
        assert r.status_code == 200
        d = r.json()
        assert d["open_path"] == "/graph/"
        assert d["api_managed"] is True

    def test_hub_api_managed_false(self, client):
        r = client.get("/api/launcher/hub/status")
        d = r.json()
        assert d["open_path"] == "/"
        assert d["api_managed"] is False


# -------------------------------------------------------------------
# UI HTML
# -------------------------------------------------------------------
class TestLauncherPage:
    def test_has_open_button_css(self, client):
        html = client.get("/launcher").text
        assert "a.open" in html
        assert "background:#2563eb" in html  # couleur du bouton Ouvrir

    def test_has_cli_badge_css(self, client):
        html = client.get("/launcher").text
        assert ".badge-cli" in html

    def test_js_references_open_path(self, client):
        html = client.get("/launcher").text
        # Le JS doit referer a m.open_path et api_managed
        assert "open_path" in html
        assert "api_managed" in html

    def test_js_uses_esc_on_open_path(self, client):
        """Anti-XSS : le JS doit passer open_path dans esc() avant insertion."""
        html = client.get("/launcher").text
        # On cherche la construction du lien avec esc
        assert 'esc(m.open_path)' in html

    def test_js_target_blank_noopener(self, client):
        """Liens externes avec target=_blank doivent avoir rel=noopener."""
        html = client.get("/launcher").text
        assert 'target="_blank"' in html
        assert 'rel="noopener"' in html
