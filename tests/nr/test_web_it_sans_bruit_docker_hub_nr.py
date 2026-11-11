"""NR -- la categorie `it` de SearXNG n'ajoute plus d'images Docker Hub hors sujet (10/11 soir).

Mesure : « meteo Lyon novembre » -> images hub.docker.com lyon24/social-* ; « pytest-split store durations » ->
dhi/secrets-store-csi-driver. Le moteur `docker hub` de la categorie `it` repond a tout mot-cle. Contrats :
  1. resultat `it` du moteur docker hub ecarte quand la requete ne parle pas de Docker/conteneur/image ;
  2. garde si la requete parle de Docker ;
  3. les autres moteurs `it` (github...) passent.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_web_fallback as W  # noqa: E402


def _brancher(monkeypatch):
    def _sx(query, n, engines="", categories=""):
        if categories == "it":
            return [{"title": "lyon24/social", "url": "https://hub.docker.com/r/lyon24/social", "engine": "docker hub"},
                    {"title": "repo", "url": "https://github.com/a/b", "engine": "github"}], None
        return [{"title": "web", "url": "https://ex.org/w", "engine": "brave"}], None
    monkeypatch.setattr(W, "_searxng_diag", _sx)


def _urls(query):
    async def _f():
        return await W._searxng_fusion(asyncio.get_running_loop(), query, 5)
    fusion, _, _ = asyncio.run(_f())
    return [r["url"] for r in fusion]


def test_docker_hub_ecarte_hors_sujet(monkeypatch):
    _brancher(monkeypatch)
    u = _urls("meteo Lyon novembre")
    assert "https://hub.docker.com/r/lyon24/social" not in u
    assert "https://github.com/a/b" in u and "https://ex.org/w" in u


def test_docker_hub_garde_si_requete_docker(monkeypatch):
    _brancher(monkeypatch)
    assert "https://hub.docker.com/r/lyon24/social" in _urls("image docker searxng")
