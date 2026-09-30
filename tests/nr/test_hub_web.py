"""
tests/nr/test_hub_web.py - Tests NR pour le hub web + ctf_web.

Suite de non-regression rejouable apres chaque modif du hub. Aucun
process externe lance (TestClient uniquement) => rapide et deterministe.

Usage :
    pytest tests/nr/test_hub_web.py -v
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def client():
    """TestClient sans auth (tests legacy pre-auth D).
    On force LAFORGE_AUTH_ENABLED=0 + reimport pour recreer AUTH_CFG."""
    import os
    os.environ["LAFORGE_AUTH_ENABLED"] = "0"
    os.environ.setdefault("LAFORGE_ADMIN_TOKEN", "nr-baseline-dummy")
    for mod in list(sys.modules):
        if mod.startswith("app.web_hub"):
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from app.web_hub.app import app
    return TestClient(app)


# ---------------------------------------------------------------
# Hub
# ---------------------------------------------------------------
class TestHub:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok"
        assert "version" in d

    def test_dashboard_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        html = r.text.lower()
        for kw in ("laforge", "<html", "refreshstatus", "data-service=\"ctf\""):
            assert kw in html, f"dashboard missing {kw!r}"

    def test_dashboard_polling_interval(self, client):
        html = client.get("/").text
        # Historiquement setInterval(refreshStatus, 5000). Depuis L : refreshAll
        # (wrapper qui appelle applyFeatureFlags + refreshStatus).
        assert ("setInterval(refreshAll, 5000)" in html
                or "setInterval(refreshStatus, 5000)" in html)

    def test_dashboard_dot_tooltip(self, client):
        html = client.get("/").text
        assert "dot.title" in html, "les tooltips de status dots doivent exister"

    def test_status_shape(self, client):
        r = client.get("/status")
        assert r.status_code == 200
        d = r.json()
        assert d["hub"]["ok"] is True
        for svc in ("recon", "graph", "ctf", "tui"):
            assert svc in d, f"missing service key {svc}"


# ---------------------------------------------------------------
# CTF Runner (monte sous /ctf)
# ---------------------------------------------------------------
@pytest.mark.skip(reason="/ctf (app.ctf_web) extrait vers nokido-redteam 2026-08-22")
class TestCtf:
    def test_ping(self, client):
        r = client.get("/ctf/ping")
        assert r.status_code == 200
        assert r.text.strip('"\n ') == "pong"

    def test_health(self, client):
        r = client.get("/ctf/health")
        d = r.json()
        assert d["status"] == "ok"
        assert d["challenges"] >= 1

    def test_index_html(self, client):
        r = client.get("/ctf/")
        assert r.status_code == 200
        assert "<html" in r.text.lower()

    def test_list_api(self, client):
        r = client.get("/ctf/api/challenges")
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list)
        assert len(arr) >= 1
        # ES1337 doit etre filtre (disabled:true)
        slugs = {c["slug"] for c in arr}
        assert "ES1337" not in slugs, "ES1337 doit etre filtre (disabled)"

    def test_detail_known(self, client):
        r = client.get("/ctf/c/got_milk")
        assert r.status_code == 200

    def test_detail_unknown(self, client):
        assert client.get("/ctf/c/bogus_XYZ").status_code == 404

    def test_run_unknown_404(self, client):
        assert client.post("/ctf/api/run/bogus_XYZ").status_code == 404


# ---------------------------------------------------------------
# Securite / Injection
# ---------------------------------------------------------------
class TestSecurity:
    @pytest.mark.parametrize("bad", [
        "../etc/passwd",
        "..%2F..%2Fetc%2Fpasswd",
        "../../flag.txt",
        "%00../secret",
    ])
    def test_path_traversal_ctf_detail(self, client, bad):
        # Le registre expose seulement les slugs explicites du disque ;
        # toute forme path-traversal doit retourner 404 (pas 500/200).
        r = client.get(f"/ctf/c/{bad}")
        assert r.status_code in (404, 422), (
            f"path traversal doit etre refuse, got {r.status_code} for {bad!r}")

    def test_html_escape_description(self, client):
        # Les templates doivent escape les champs du challenge.json.
        # On regarde la page de got_milk : description contient "<" ou backticks ?
        r = client.get("/ctf/c/got_milk")
        # Rien de brut du style <script> ou </body> au milieu du <pre>
        assert "<script>alert" not in r.text
        # Le descriptif got_milk est "`nc {box} {port}`" -> les backticks
        # restent textuels mais les caracteres speciaux HTML doivent etre escape
        # (v. html.escape dans templates.py)

    def test_status_no_credentials_leak(self, client):
        r = client.get("/status").json()
        # Ne jamais retourner de cle sensible dans le status
        for v in r.values():
            s = json.dumps(v).lower()
            for forbidden in ("password", "secret", "token", "api_key", "cookie"):
                assert forbidden not in s, f"leak forbidden={forbidden}"

    def test_cors_not_wildcard_without_auth(self, client):
        # Le hub NE DOIT PAS activer "*" pour Access-Control-Allow-Origin
        # (attenuation CSRF basique quand on ajoutera auth)
        r = client.get("/health")
        acao = r.headers.get("access-control-allow-origin", "")
        assert acao != "*", "CORS '*' dangereux : refuser"


# ---------------------------------------------------------------
# Registre
# ---------------------------------------------------------------
@pytest.mark.skip(reason="app.ctf_web.registry extrait vers nokido-redteam 2026-08-22")
class TestRegistry:
    def test_disabled_filter(self):
        from app.ctf_web.registry import list_challenges
        active = list_challenges()
        total = list_challenges(include_disabled=True)
        assert len(total) >= len(active)
        disabled = {c["slug"] for c in total if c.get("disabled")}
        for d in disabled:
            assert d not in {c["slug"] for c in active}

    def test_schema_normalise(self):
        from app.ctf_web.registry import list_challenges
        for c in list_challenges(include_disabled=True):
            for required in ("slug", "name", "category", "points", "files",
                             "disabled"):
                assert required in c, f"schema missing {required}"


# ---------------------------------------------------------------
# Proxy ASGI : attributs statiques (sans reseau)
# ---------------------------------------------------------------
class TestProxy:
    def test_ws_target_http_to_ws(self):
        from app.web_hub.proxy import ReverseProxy
        assert ReverseProxy("http://127.0.0.1:1")._ws_target == "ws://127.0.0.1:1"

    def test_ws_target_https_to_wss(self):
        from app.web_hub.proxy import ReverseProxy
        assert ReverseProxy("https://x.y")._ws_target == "wss://x.y"

    def test_hop_by_hop_headers_filtered(self):
        from app.web_hub.proxy import _HOP_BY_HOP
        for h in ("connection", "host", "upgrade", "transfer-encoding"):
            assert h in _HOP_BY_HOP

    def test_effective_path_strips_root(self):
        from app.web_hub.proxy import ReverseProxy
        ep = ReverseProxy._effective_path
        assert ep({"path": "/tui/", "root_path": "/tui"}) == "/"
        assert ep({"path": "/tui/foo", "root_path": "/tui"}) == "/foo"
        assert ep({"path": "/recon/api", "root_path": "/recon"}) == "/api"
        assert ep({"path": "/tui", "root_path": "/tui"}) == "/"
        assert ep({"path": "", "root_path": ""}) == "/"
        # Edge : path n etant pas prefixe par root_path (ne casse pas)
        assert ep({"path": "/other", "root_path": "/tui"}) == "/other"

    def test_effective_path_normalises_leading_slash(self):
        from app.web_hub.proxy import ReverseProxy
        # root_path vide + path sans leading slash : on force "/"
        assert ReverseProxy._effective_path({"path": "abc",
                                             "root_path": ""}) == "/abc"
