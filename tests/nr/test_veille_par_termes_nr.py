"""NR : une veille par termes donnes saute l'etape LLM. Banc 6/11 : seuls des termes experts trouvent des depots utiles."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nokido_agent.app import forge_db_path, forge_watch_agent as W  # noqa: E402


class _FauxConn:
    def __init__(self):
        self.lignes = []

    def execute(self, sql, params=()):
        self.lignes.append((sql, params))


def _creer(monkeypatch, **kw):
    conn = _FauxConn()
    monkeypatch.setattr(forge_db_path, "write_retry", lambda f: f(conn))
    monkeypatch.setattr(W, "_reveiller_consommateur", lambda: "ok")
    W.create_job("agent output verification", idea_id="t", agent="T", **kw)
    return conn


def test_termes_donnes_sautent_les_etapes_llm(monkeypatch):
    conn = _creer(monkeypatch, termes=["agent output verification", "llm hallucination detection"])
    noeuds = [p[3] for s, p in conn.lignes if "agent_chain_nodes" in s]
    assert noeuds == ["search", "refine", "crawl", "ingest", "store"]
    ctx = next(json.loads(p[1]) for s, p in conn.lignes if "agent_chain_context" in s)
    assert ctx["keywords_verified"] == ["agent output verification", "llm hallucination detection"]
    job = next(p for s, p in conn.lignes if "INTO watch_jobs" in s)
    assert job[3] == "search"


def test_sans_termes_la_chaine_reste_entiere(monkeypatch):
    noeuds = [p[3] for s, p in _creer(monkeypatch).lignes if "agent_chain_nodes" in s]
    assert noeuds[:2] == ["keywords", "verify_kw"]


def test_termes_vides_refuses(monkeypatch):
    with pytest.raises(ValueError):
        _creer(monkeypatch, termes=["  "])
