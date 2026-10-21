"""NR -- la reclamation crawl4ai se RELACHE, et l'arret gouverne de Docker la relache aussi (2026-10-20).

Mesure du 20/10 : une recherche web d'agent (route crawl, emetteur demander_crawl4ai:forge_crawl_tool) a pose
sandbox/crawl4ai.wanted ; NokidoDockerKeeper a REDEMARRE Docker Desktop apres que l'owner l'eut quitte (16:10, 16:15) ;
`nokido_ensure_service{docker, stopped}` a retire docker.wanted mais LAISSE crawl4ai.wanted, faute de toute fonction
pour la relacher : seule l'expiration (TTL 900 s) ou un retrait a la main l'ont fait. Une demande sans relache est un
reveil a sens unique.

Ce qui est garde : `relacher_crawl4ai()` retire la reclamation (idempotent) ; `release_daemon()` -- appele par l'arret
gouverne -- retire docker.wanted ET crawl4ai.wanted.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


@pytest.fixture
def agent(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("docker_agent_relache_nr", RACINE / "app" / "forge_docker_agent.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "WANT_FLAG", tmp_path / "docker.wanted")
    monkeypatch.setattr(m, "CRAWL4AI_FLAG", tmp_path / "crawl4ai.wanted")
    return m


def test_relacher_crawl4ai_retire_la_reclamation_et_reste_idempotent(agent):
    agent.CRAWL4AI_FLAG.write_text("1792505188.19", encoding="utf-8")
    assert agent.relacher_crawl4ai() == {"ok": True, "action": "crawl4ai_wanted_cleared"}
    assert not agent.CRAWL4AI_FLAG.exists()
    assert agent.relacher_crawl4ai()["ok"] is True, "relacher une reclamation absente n'est pas une erreur"


def test_l_arret_gouverne_relache_aussi_crawl4ai(agent):
    agent.WANT_FLAG.write_text("1", encoding="utf-8")
    agent.CRAWL4AI_FLAG.write_text("1", encoding="utf-8")
    assert agent.release_daemon()["ok"] is True
    assert not agent.WANT_FLAG.exists() and not agent.CRAWL4AI_FLAG.exists()
