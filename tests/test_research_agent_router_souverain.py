"""tests/test_research_agent_router_souverain.py - Test routage LLM souverain et metadata provider dans research_agent."""
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 sur la VRAIE base (code
#   appele) (l.47)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import app.forge_research_agent as fra


def test_research_agent_llm_router_integration(monkeypatch):
    """Vérifie que research_agent passe par le routeur souverain et remonte llm_provider."""
    calls = []

    def mock_call_cascade(prompt, use_case="general", **kwargs):
        calls.append((prompt, use_case))
        if use_case == "strategy":
            return {"ok": True, "text": "WSL2 Docker crash logs\nDocker Desktop error", "provider": "github_llama_70b"}
        elif use_case == "synthesis":
            return {"ok": True, "text": "Synthèse valide de test.", "provider": "openrouter_gpt_oss"}
        else:
            return {"ok": True, "text": "1", "provider": "github_gpt41_mini"}

    class MockRouter:
        def call_cascade(self, prompt, use_case="general", **kwargs):
            return mock_call_cascade(prompt, use_case, **kwargs)

    import forge_llm_router
    monkeypatch.setattr(forge_llm_router, "get_router", lambda: MockRouter())

    # Mock _search, _fetch, _ingest
    def mock_search(q, n=5):
        return [
            {
                "title": "Docker crash fix",
                "url": "https://example.com/docker-fix",
                "content": "Fix for WSL2 Docker Desktop crash",
            }
        ], ""

    monkeypatch.setattr(fra, "_search", mock_search)
    monkeypatch.setattr(fra, "_fetch", lambda url: "Full text of docker crash fix")
    monkeypatch.setattr(fra, "_ingest", lambda url, title, text, domain, role: True)

    res = fra.research_agent("WSL2 Docker Desktop crash investigation", max_rounds=1, max_urls=1)

    assert res["ok"] is True
    assert res["synthesis_ok"] is True
    assert res["synthesis"] == "Synthèse valide de test."
    assert res["llm_provider"] == "openrouter_gpt_oss"
    assert "WSL2 Docker crash logs" in res["queries"]
    assert len(calls) >= 2
    # Vérifie que les use_cases strategy et synthesis ont été utilisés
    use_cases = [c[1] for c in calls]
    assert "strategy" in use_cases
    assert "synthesis" in use_cases


def test_research_agent_llm_provider_on_failure(monkeypatch):
    """Vérifie le comportement en cas d'échec LLM / provider nomme."""
    def mock_search(q, n=5):
        return [], "URLError: connection refused"

    monkeypatch.setattr(fra, "_search", mock_search)
    monkeypatch.setattr(fra, "_llm", lambda prompt, provider="auto": ("query 1", "ollama_local"))

    import forge_watch_agent as fwa
    import app.forge_watch_agent as fwa_app
    monkeypatch.setattr(fwa, "_academic_search", lambda q, n=4: [])
    monkeypatch.setattr(fwa_app, "_academic_search", lambda q, n=4: [])

    res = fra.research_agent("test failure case", max_rounds=1)

    assert res["ok"] is False
    assert res["error"] == "moteur injoignable"
    assert res["llm_provider"] == "ollama_local"


def test_search_retry_on_connection_error(monkeypatch):
    """Vérifie que _search réessaie sur erreur de connexion puis réussit."""
    import urllib.request
    import urllib.error

    attempts = 0

    class DummyResponse:
        def read(self):
            return b'{"results": [{"url": "https://example.com", "title": "Test"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def mock_urlopen(url, timeout=8):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise urllib.error.URLError("WinError 10061 Connection refused")
        return DummyResponse()

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: None)

    results, err = fra._search("test query", max_retries=3)
    assert attempts == 3
    assert len(results) == 1
    assert err == ""


def test_search_no_retry_on_4xx(monkeypatch):
    """Vérifie que _search ne réessaie pas sur erreur HTTP 4xx."""
    import urllib.request
    import urllib.error

    attempts = 0

    def mock_urlopen(url, timeout=8):
        nonlocal attempts
        attempts += 1
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: None)

    results, err = fra._search("test query", max_retries=3)
    assert attempts == 1
    assert len(results) == 0
    assert "HTTPError" in err

