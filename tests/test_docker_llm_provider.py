"""Docker comme provider LLM (Docker Model Runner / conteneur OpenAI-compat).
Non-régression registre + is_available fail-safe (jamais d'exception si DMR off)."""
import importlib

ap = importlib.import_module("forge_agent_proxy")


def test_docker_provider_registered():
    assert "docker" in ap._PROVIDERS
    p = ap._PROVIDERS["docker"]
    assert p.cost_tier == 0  # LOCAL souverain (conteneur), jamais facturé cloud
    assert p.name == "docker"


def test_docker_base_env_override(monkeypatch):
    monkeypatch.setenv("DOCKER_LLM_BASE", "http://localhost:9999/v1/")
    assert ap.DockerModelRunner._base() == "http://localhost:9999/v1"  # rstrip /
    monkeypatch.delenv("DOCKER_LLM_BASE", raising=False)
    assert ap.DockerModelRunner._base() == "http://localhost:12434/engines/v1"  # défaut DMR


def test_docker_is_available_no_crash(monkeypatch):
    # endpoint mort -> False, jamais d'exception (conteneur LLM absent = indispo géré)
    monkeypatch.setenv("DOCKER_LLM_BASE", "http://127.0.0.1:1/v1")
    assert ap._PROVIDERS["docker"].is_available() is False
