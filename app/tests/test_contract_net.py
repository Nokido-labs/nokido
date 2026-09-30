# -*- coding: utf-8 -*-
"""
Step 3 switchboard — Contract-Net : élection déterministe de worker.
Sources injectées (offline) : local low-latency doit gagner.
"""
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from nokido_agent.app import forge_contract_net as cn  # noqa: E402

_TIERS = {"ollama_local": "local", "groq": "free", "claude": "paid_api"}
_LAT = {"ollama_local": 1500, "groq": 200, "claude": 2000}


def _tier_of(n):
    return _TIERS.get(n, "free")


def _lat_of(n):
    return _LAT.get(n, 1000)


def _no_dead(n, uc):
    return False


def test_local_wins_election():
    res = cn.elect_worker(
        "code",
        providers=["ollama_local", "groq", "claude"],
        edges=[],
        tier_of=_tier_of,
        latency_of=_lat_of,
        is_dead=_no_dead,
    )
    assert res["winner"]["worker"] == "ollama_local"     # tier local prime
    assert res["winner"]["score"] == max(b["score"] for b in res["bids"])


def test_dead_end_excluded():
    dead = lambda n, uc: n == "ollama_local"  # noqa: E731
    res = cn.elect_worker(
        "code", providers=["ollama_local", "groq"], edges=[],
        tier_of=_tier_of, latency_of=_lat_of, is_dead=dead,
    )
    workers = [b["worker"] for b in res["bids"]]
    assert "ollama_local" not in workers
    assert res["winner"]["worker"] == "groq"


def test_edge_bids_included():
    res = cn.elect_worker(
        "vision", providers=[], is_dead=_no_dead,
        edges=[{"name": "minipc2", "cpu_pct": 10, "ram_free_mb": 12000, "status": "online",
                "url": "http://minipc2:11434", "capabilities": {"runtime": "ollama"}}],
        tier_of=_tier_of, latency_of=_lat_of,
    )
    assert res["winner"]["worker"] == "edge:minipc2"
    assert res["winner"]["kind"] == "edge"


def test_no_candidates_no_winner():
    res = cn.elect_worker("code", providers=[], edges=[], is_dead=_no_dead)
    assert res["winner"] is None
    assert res["bids"] == []


def test_collect_bids_sorted_desc():
    bids = cn.collect_bids(
        "code", providers=["ollama_local", "groq", "claude"], edges=[],
        tier_of=_tier_of, latency_of=_lat_of, is_dead=_no_dead,
    )
    scores = [b["score"] for b in bids]
    assert scores == sorted(scores, reverse=True)
