"""
tests/nr/test_hub_csp.py - NR Content-Security-Policy centralisee.

Resout le trou Gemini #3 : la CSP etait une f-string en dur dans app.py.
Extraite vers app/web_hub/csp.py. Ce module verifie :

  - Equivalence BIT-A-BIT avec la CSP historique (zero regression).
  - Presence de chaque directive attendue.
  - Ordre stable des tokens (deterministe).
  - Extensibilite via extra_cdns / module_ports.
  - Les modules proxies (7410/7420/7440) sont bien autorises en
    http:// ET ws:// sur 127.0.0.1 ET localhost.
  - Le header est pose sur chaque response HTTP.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# -------------------------------------------------------------------
# Fixtures : reimport propre + client auth
# -------------------------------------------------------------------
@pytest.fixture
def admin_token():
    return "super-secret-admin-token-csp"


@pytest.fixture
def fresh_csp():
    """Module csp reimporte pour chaque test (isole)."""
    for m in list(sys.modules):
        if m.startswith("app.web_hub.csp"):
            del sys.modules[m]
    from app.web_hub import csp as mod
    return mod


@pytest.fixture
def client_auth_on(monkeypatch, admin_token):
    monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
    monkeypatch.delenv("LAFORGE_JWT_SECRET", raising=False)
    for m in list(sys.modules):
        if m.startswith("app.web_hub"):
            del sys.modules[m]
    from fastapi.testclient import TestClient
    from app.web_hub.app import app
    from app.web_hub.auth import login_rate_limiter
    login_rate_limiter._by_ip.clear()  # noqa: SLF001
    return TestClient(app)


# -------------------------------------------------------------------
# Equivalence bit-a-bit avec la CSP historique
# -------------------------------------------------------------------
# Cette string est le SNAPSHOT de la CSP produite par app.py avant
# la refacto (commit e1c11f7 etat). Si ce test casse, cela signifie
# qu'on a change le contenu de la CSP et il faut mettre a jour ce
# snapshot CONSCIEMMENT, pas par accident.
EXPECTED_HISTORICAL_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' "
    "https://cdn.tailwindcss.com https://unpkg.com "
    "https://cdnjs.cloudflare.com "
    "http://127.0.0.1:7410 http://127.0.0.1:7420 http://127.0.0.1:7440 "
    "http://localhost:7410 http://localhost:7420 http://localhost:7440; "
    "style-src 'self' 'unsafe-inline' "
    "https://cdn.tailwindcss.com https://fonts.googleapis.com "
    "http://127.0.0.1:7410 http://127.0.0.1:7420 http://127.0.0.1:7440 "
    "http://localhost:7410 http://localhost:7420 http://localhost:7440; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data: "
    "http://127.0.0.1:7410 http://127.0.0.1:7420 http://127.0.0.1:7440 "
    "http://localhost:7410 http://localhost:7420 http://localhost:7440; "
    "connect-src 'self' "
    "http://127.0.0.1:7410 http://127.0.0.1:7420 http://127.0.0.1:7440 "
    "http://localhost:7410 http://localhost:7420 http://localhost:7440 "
    "ws://127.0.0.1:7410 ws://127.0.0.1:7420 ws://127.0.0.1:7440 "
    "ws://localhost:7410 ws://localhost:7420 ws://localhost:7440; "
    "frame-ancestors 'none'; "
    "base-uri 'self';"
)


class TestHistoricalEquivalence:
    def test_default_build_matches_historical_snapshot(self, fresh_csp):
        """La sortie par defaut = la f-string historique de app.py.

        Si ce test casse : decision consciente necessaire (update snapshot +
        justification dans le commit).
        """
        assert fresh_csp.build_csp() == EXPECTED_HISTORICAL_CSP

    def test_output_ends_with_semicolon(self, fresh_csp):
        """Historique terminait toujours par ';' - on garde la convention."""
        assert fresh_csp.build_csp().rstrip().endswith(";")

    def test_no_double_semicolon(self, fresh_csp):
        assert ";;" not in fresh_csp.build_csp()


# -------------------------------------------------------------------
# Directives individuelles : presence, ordre
# -------------------------------------------------------------------
class TestDirectives:
    EXPECTED_DIRECTIVES = (
        "default-src", "script-src", "style-src", "font-src",
        "img-src", "connect-src", "frame-ancestors", "base-uri",
    )

    def _parse(self, csp: str) -> dict[str, list[str]]:
        """Parse 'name t1 t2; name t1 ...' -> {name: [tokens]}."""
        out = {}
        for part in csp.rstrip(";").split(";"):
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            if not tokens:
                continue
            out[tokens[0]] = tokens[1:]
        return out

    def test_all_expected_directives_present(self, fresh_csp):
        csp = fresh_csp.build_csp()
        parsed = self._parse(csp)
        for d in self.EXPECTED_DIRECTIVES:
            assert d in parsed, f"directive manquante : {d}"

    def test_directives_in_stable_order(self, fresh_csp):
        """L'ordre des directives est deterministe (important pour diff)."""
        csp = fresh_csp.build_csp()
        positions = [csp.index(d + " ") for d in self.EXPECTED_DIRECTIVES
                     if d + " " in csp]
        assert positions == sorted(positions)

    def test_default_src_is_self_only(self, fresh_csp):
        parsed = self._parse(fresh_csp.build_csp())
        assert parsed["default-src"] == ["'self'"]

    def test_frame_ancestors_none(self, fresh_csp):
        """Anti-clickjacking : frame-ancestors DOIT etre 'none'."""
        parsed = self._parse(fresh_csp.build_csp())
        assert parsed["frame-ancestors"] == ["'none'"]

    def test_base_uri_self(self, fresh_csp):
        """Anti-base-tag-injection : base-uri DOIT etre 'self'."""
        parsed = self._parse(fresh_csp.build_csp())
        assert parsed["base-uri"] == ["'self'"]

    def test_script_src_has_unsafe_inline(self, fresh_csp):
        """Requis par le dashboard HTML inline + Tailwind CDN runtime."""
        parsed = self._parse(fresh_csp.build_csp())
        assert "'unsafe-inline'" in parsed["script-src"]
        assert "'self'" in parsed["script-src"]

    def test_font_src_allows_data_uris(self, fresh_csp):
        """data: requis pour les icon fonts embarquees."""
        parsed = self._parse(fresh_csp.build_csp())
        assert "data:" in parsed["font-src"]

    def test_img_src_allows_data_uris(self, fresh_csp):
        """Images base64 inline (favicon, badges) necessaires."""
        parsed = self._parse(fresh_csp.build_csp())
        assert "data:" in parsed["img-src"]


# -------------------------------------------------------------------
# Modules proxies : 127.0.0.1 + localhost, http + ws, sur 3 ports
# -------------------------------------------------------------------
class TestModuleOrigins:
    def test_script_src_contains_http_modules(self, fresh_csp):
        csp = fresh_csp.build_csp()
        # recon 7410, graph 7420, tui 7440 -> defaut
        for port in (7410, 7420, 7440):
            assert f"http://127.0.0.1:{port}" in csp
            assert f"http://localhost:{port}" in csp

    def test_connect_src_contains_ws_modules(self, fresh_csp):
        csp = fresh_csp.build_csp()
        for port in (7410, 7420, 7440):
            assert f"ws://127.0.0.1:{port}" in csp
            assert f"ws://localhost:{port}" in csp

    def test_ws_only_in_connect_not_script(self, fresh_csp):
        """ws:// n'a rien a faire dans script-src (pas executable)."""
        csp = fresh_csp.build_csp()
        # Parse pour isoler script-src
        script_part = [p for p in csp.split(";")
                       if p.strip().startswith("script-src")][0]
        assert "ws://" not in script_part

    def test_custom_module_ports(self, fresh_csp):
        """On peut injecter d'autres ports sans toucher app.py."""
        csp = fresh_csp.build_csp(module_ports=[9999])
        assert "http://127.0.0.1:9999" in csp
        assert "ws://127.0.0.1:9999" in csp
        # Les defauts ne doivent PAS fuiter
        assert "7410" not in csp
        assert "7440" not in csp

    def test_empty_module_ports_valid(self, fresh_csp):
        """Aucun module locaux : la CSP reste valide (juste plus restrictive)."""
        csp = fresh_csp.build_csp(module_ports=[])
        assert "127.0.0.1" not in csp
        assert "ws://" not in csp  # plus rien de local
        # Les CDN externes restent
        assert "https://cdn.tailwindcss.com" in csp


# -------------------------------------------------------------------
# Extensibilite : ajouter un CDN sans toucher les constantes
# -------------------------------------------------------------------
class TestExtensibility:
    def test_extra_script_cdn_added(self, fresh_csp):
        csp = fresh_csp.build_csp(
            extra_cdns={"script": ["https://newcdn.example.com"]},
        )
        # Apparait dans script-src
        script_part = [p for p in csp.split(";")
                       if p.strip().startswith("script-src")][0]
        assert "https://newcdn.example.com" in script_part
        # N'apparait PAS ailleurs (pas de fuite)
        style_part = [p for p in csp.split(";")
                      if p.strip().startswith("style-src")][0]
        assert "https://newcdn.example.com" not in style_part

    def test_extra_connect_cdn_added(self, fresh_csp):
        """Typique pour les endpoints API externes (API monitoring, etc)."""
        csp = fresh_csp.build_csp(
            extra_cdns={"connect": ["https://api.example.com"]},
        )
        connect_part = [p for p in csp.split(";")
                        if p.strip().startswith("connect-src")][0]
        assert "https://api.example.com" in connect_part

    def test_extra_cdns_empty_dict_noop(self, fresh_csp):
        """extra_cdns={} doit produire le meme resultat que defaut."""
        assert fresh_csp.build_csp(extra_cdns={}) == fresh_csp.build_csp()

    def test_extra_cdns_none_noop(self, fresh_csp):
        assert fresh_csp.build_csp(extra_cdns=None) == fresh_csp.build_csp()


# -------------------------------------------------------------------
# Integration : le header est effectivement pose sur les responses
# -------------------------------------------------------------------
class TestIntegrationHeader:
    def test_csp_header_on_login_page(self, client_auth_on):
        r = client_auth_on.get("/auth/login")
        assert r.status_code == 200
        csp = r.headers.get("content-security-policy", "")
        assert csp, "CSP header absent"
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_csp_header_on_health(self, client_auth_on):
        r = client_auth_on.get("/health")
        assert r.status_code == 200
        assert "content-security-policy" in (h.lower() for h in r.headers)

    def test_csp_header_matches_build_csp(self, client_auth_on, fresh_csp):
        r = client_auth_on.get("/auth/login")
        expected = fresh_csp.build_csp()
        assert r.headers["content-security-policy"] == expected

    def test_other_security_headers_still_present(self, client_auth_on):
        """Regression : X-Frame, nosniff, Referrer-Policy, Permissions-Policy."""
        r = client_auth_on.get("/auth/login")
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"
        assert r.headers.get("referrer-policy") == "same-origin"
        assert "geolocation=()" in r.headers.get("permissions-policy", "")
