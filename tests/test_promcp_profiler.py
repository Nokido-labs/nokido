"""Profiling par tool MCP (item 2 du pack P2).

L'enregistrement vit sur le chemin chaud du dispatch : il doit etre silencieux,
borne, et ne JAMAIS remonter d'exception.
"""
from __future__ import annotations

import os
import sys
import time

import pytest

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import forge_promcp_profiler as pp  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "DB", tmp_path / "t.db")
    return pp.DB


def test_record_puis_stats(db):
    pp.record("rag", 120.0, ok=True, payload_bytes=10)
    pp.record("rag", 80.0, ok=True)
    pp.record("run", 5.0, ok=False)
    s = pp.stats(since_hours=1)
    assert s["ok"] and s["n_calls"] == 3
    assert s["tools"]["rag"]["n"] == 2
    assert s["tools"]["rag"]["mean_ms"] == pytest.approx(100.0, abs=0.1)
    assert s["tools"]["run"]["error_rate"] == 1.0


def test_record_ne_leve_jamais(monkeypatch, tmp_path):
    """Sur le chemin chaud : une base illisible ne doit pas casser le dispatch."""
    monkeypatch.setattr(pp, "DB", tmp_path / "nope" / "x" / "t.db")
    pp.record("rag", 1.0)  # ne doit pas lever


def test_kill_switch(db, monkeypatch):
    monkeypatch.setenv("LAFORGE_PROMCP_PROFILE", "0")
    pp.record("rag", 50.0)
    assert pp.stats(since_hours=1)["n_calls"] == 0


def test_p95_pas_la_moyenne(db):
    """La queue fait attendre l'appelant ; une moyenne la lisse.

    90 appels rapides + 10 lents : la moyenne (~109 ms) ne ressemble a AUCUN appel
    reel, le p50 montre le cas courant et le p95 montre ce que subit l'appelant
    malchanceux. (Un seul point lent sur 20 ne DOIT pas bouger le p95 : 19/20 = 95%
    des appels sont rapides — c'est la definition, pas un bug.)
    """
    for _ in range(90):
        pp.record("t", 10.0)
    for _ in range(10):
        pp.record("t", 1000.0)
    m = pp.stats(since_hours=1)["tools"]["t"]
    assert m["p50_ms"] == pytest.approx(10.0, abs=0.1)
    assert m["p95_ms"] >= 1000.0
    assert 100.0 < m["mean_ms"] < 120.0  # la moyenne ne decrit personne


def test_costliest_trie_sur_le_CUMUL(db):
    """Un tool tiede appele mille fois coute plus qu'un tool lent appele deux fois."""
    for _ in range(100):
        pp.record("frequent", 20.0)     # 2000 ms cumules
    pp.record("lent", 500.0)
    pp.record("lent", 400.0)            # 900 ms cumules
    top = pp.costliest(limit=2, since_hours=1)
    assert top[0]["tool"] == "frequent"


def test_fenetre_temporelle(db):
    pp.record("vieux", 10.0)
    # on repousse l'enregistrement hors fenetre
    import sqlite3
    c = sqlite3.connect(str(pp.DB))
    c.execute("UPDATE promcp_tool_metrics SET ts=?", (time.time() - 40 * 3600,))
    c.commit()
    c.close()
    assert pp.stats(since_hours=1)["n_calls"] == 0
    assert pp.stats(since_hours=48)["n_calls"] == 1


def test_cout_inconnu_vaut_None_pas_zero(db):
    """Pour le routage, 'jamais mesure' ne doit JAMAIS se lire 'gratuit'."""
    assert pp.observed_cost_ms("jamais_appele") is None
    pp.record("connu", 42.0)
    assert pp.observed_cost_ms("connu") == pytest.approx(42.0, abs=0.5)


def test_stats_sur_base_absente_est_propre(monkeypatch, tmp_path):
    monkeypatch.setattr(pp, "DB", tmp_path / "vide.db")
    s = pp.stats()
    assert s["ok"] is True and s["tools"] == {}
