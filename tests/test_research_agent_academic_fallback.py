"""tests/test_research_agent_academic_fallback.py - Test repli academique pour research_agent."""
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 sur la VRAIE base (code
#   appele); reseau SearXNG reel (code appele) (l.47)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import app.forge_research_agent as fra


def test_research_agent_academic_fallback(monkeypatch):
    """Verifie le basculement vers _academic_search quand SearXNG rend une erreur."""
    # Mock LLM queries output
    monkeypatch.setattr(fra, "_llm", lambda prompt, provider="auto": "query 1\nquery 2")

    # Mock _search error (SearXNG down)
    def mock_search(q, n=5):
        return [], "URLError: Connection refused"

    monkeypatch.setattr(fra, "_search", mock_search)

    # Mock _academic_search return
    academic_called = []

    def mock_academic_search(q, n=8):
        academic_called.append(q)
        return [
            {
                "title": f"Academic Paper for {q}",
                "url": f"https://arxiv.org/abs/2026.{len(academic_called)}",
                "content": "Abstract content of academic paper",
                "engine": "arxiv_direct",
            }
        ]

    import forge_watch_agent as fwa_direct
    import app.forge_watch_agent as fwa
    monkeypatch.setattr(fwa_direct, "_academic_search", mock_academic_search)
    monkeypatch.setattr(fwa, "_academic_search", mock_academic_search)

    # Mock _fetch and _ingest to bypass network/DB
    monkeypatch.setattr(fra, "_fetch", lambda url: "Full text content")
    monkeypatch.setattr(fra, "_ingest", lambda url, title, text, domain, role: True)

    res = fra.research_agent("test query objective", max_rounds=1, max_urls=2)

    assert res["ok"] is True
    assert res["search_path"] == "academique"
    assert len(res["search_errors"]) > 0
    assert "URLError" in res["search_errors"][0]
    assert res["found"] > 0
    assert len(academic_called) > 0


def test_research_agent_searxng_normal(monkeypatch):
    """Verifie le chemin normal SearXNG sans erreur."""
    monkeypatch.setattr(fra, "_llm", lambda prompt, provider="auto": "query 1")

    def mock_search(q, n=5):
        return [
            {
                "title": "SearXNG Result",
                "url": "https://example.com/res1",
                "content": "SearXNG content",
            }
        ], ""

    monkeypatch.setattr(fra, "_search", mock_search)
    monkeypatch.setattr(fra, "_fetch", lambda url: "Full text content")
    monkeypatch.setattr(fra, "_ingest", lambda url, title, text, domain, role: True)

    res = fra.research_agent("normal objective", max_rounds=1, max_urls=2)

    assert res["ok"] is True
    assert res["search_path"] == "searxng"
    assert len(res["search_errors"]) == 0
