"""NR -- des moteurs SearXNG MUETS ne se lisent pas comme un web VIDE.

MESURE 2026-09-26 : les 4 veilles RSI lancees par l'organe de la soif (veille_on_gap) rendent
SANS EFFET ; research_agent rend ok=false, error « no results », search_errors = [] -- SearXNG
repond, mais ZERO resultat pour « Darwin Godel Machine evaluation », sujet largement publie.
Le repli academique n'agit que sur ERREUR : un zero rendu par des moteurs suspendus passait donc
pour une absence de matiere, et personne n'allait reparer. L'API SearXNG nomme pourtant ses moteurs
defaillants (`unresponsive_engines`) -- forge_watch_agent le lit deja (L849). UNKNOWN n'est pas NO.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_research_agent as ra  # noqa: E402


class _Rep(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _servir(monkeypatch, corps: dict):
    monkeypatch.setattr(ra.urllib.request, "urlopen", lambda url, timeout=None: _Rep(json.dumps(corps).encode()))
    monkeypatch.setattr(ra, "_SEARXNG_DOWN_UNTIL", 0.0)


def test_des_moteurs_muets_sont_une_erreur_nommee(monkeypatch):
    _servir(monkeypatch, {"results": [], "unresponsive_engines": [["google", "timeout"], ["duckduckgo", "CAPTCHA"]]})
    res, err = ra._search("Darwin Godel Machine", 4)
    assert res == [] and "google" in err and "duckduckgo" in err


def test_des_resultats_restent_des_resultats(monkeypatch):
    _servir(monkeypatch, {"results": [{"url": "https://x", "title": "t"}], "unresponsive_engines": [["google", "timeout"]]})
    res, err = ra._search("q", 4)
    assert len(res) == 1 and err == ""


def test_un_zero_honnete_reste_un_zero(monkeypatch):
    _servir(monkeypatch, {"results": [], "unresponsive_engines": []})
    assert ra._search("q", 4) == ([], "")
