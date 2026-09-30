# -*- coding: utf-8 -*-
"""
forge_contract_net.py — Élection de worker style Contract-Net (switchboard backlog).
================================================================================
Au lieu d'un super-routeur central, on COLLECTE des "bids" (scores) de chaque
worker candidat capable, et on ÉLIT le meilleur. Version DÉTERMINISTE synchrone
sur les registres existants (pas de NATS — Nokido n'en a pas) :

  candidats = capability_registry.providers_for(use_case) (cloud/local)
            + forge_edge_fleet.list_edges() (noeuds distants)
  score     = tier (local>free>quota>paid) + latence + charge edge (cpu/ram)
              − exclusion dead_end (forge_motivation)

Extension future = marché de bids ASYNC sur forge_swarm_bus/Deno quand des
responders réels existent (multi-machines). Ici = le cœur d'élection réutilisable.
Anti-dup : zéro nouveau registre, pur scoring sur l'existant.
"""
from __future__ import annotations

__FORGE_COLOR__ = "GREEN"

TIER_WEIGHT = {"local": 1.0, "free": 0.7, "subscription_quota": 0.5, "paid_api": 0.2}
_W_TIER = 0.6
_W_LATENCY = 0.4


def _latency_score(latency_ms: float) -> float:
    return 1.0 / (1.0 + max(0.0, latency_ms) / 1000.0)


# ── Sources par défaut (injectables pour test) ────────────────────────────────
def _default_providers_for(use_case: str) -> list[str]:
    try:
        from nokido_agent.app.forge_capability_registry import providers_for

        return providers_for(use_case)
    except Exception:
        return []


def _default_tier_of(name: str) -> str:
    try:
        from nokido_agent.app.forge_provider_specs import get_tier

        return get_tier(name)
    except Exception:
        return "free"


def _default_latency_of(name: str) -> float:
    try:
        from nokido_agent.app.forge_llm_router import PROVIDERS

        return float(PROVIDERS.get(name, {}).get("latency", 1000))
    except Exception:
        return 1000.0


def _default_is_dead(name: str, use_case: str) -> bool:
    try:
        from nokido_agent.app.forge_motivation import is_dead_end

        return bool(is_dead_end(f"llm_call:{name}", use_case))
    except Exception:
        return False


def _default_edges() -> list[dict]:
    try:
        from nokido_agent.app.forge_edge_fleet import list_edges

        return list(list_edges())
    except Exception:
        return []


def collect_bids(
    use_case: str,
    *,
    providers=None,
    edges=None,
    tier_of=None,
    latency_of=None,
    is_dead=None,
) -> list[dict]:
    """Retourne les bids triés (score décroissant). Worker = provider ou edge:<name>."""
    providers = providers if providers is not None else _default_providers_for(use_case)
    tier_of = tier_of or _default_tier_of
    latency_of = latency_of or _default_latency_of
    is_dead = is_dead or _default_is_dead

    bids: list[dict] = []
    for name in providers:
        if is_dead(name, use_case):
            continue
        tier = tier_of(name)
        score = _W_TIER * TIER_WEIGHT.get(tier, 0.5) + _W_LATENCY * _latency_score(latency_of(name))
        bids.append({"worker": name, "kind": "provider", "tier": tier, "score": round(score, 4)})

    edges = edges if edges is not None else _default_edges()
    try:
        from nokido_agent.app.forge_edge_fleet import sert_le_chat
    except Exception:  # noqa: BLE001  muet-ok : sans le filtre, AUCUN noeud n'encherit (fail-closed)
        sert_le_chat = lambda _e: False  # noqa: E731
    for e in edges:
        if not sert_le_chat(e):
            continue  # hors ligne, non http, ou sans runtime d'inference : ne sait pas servir
        # charge edge : cpu bas + ram libre haute = meilleur bid
        cpu = float(e.get("cpu_pct", 50) or 50)
        ram = float(e.get("ram_free_mb", 4000) or 4000)
        load_score = (1.0 - min(cpu, 100) / 100.0) * 0.5 + min(ram / 16000.0, 1.0) * 0.5
        score = _W_TIER * TIER_WEIGHT["local"] + _W_LATENCY * load_score
        bids.append({"worker": f"edge:{e.get('name', '?')}", "kind": "edge", "tier": "local", "score": round(score, 4)})

    bids.sort(key=lambda b: b["score"], reverse=True)
    return bids


def elect_worker(use_case: str, **kw) -> dict:
    """Élit le meilleur worker pour un use_case. {'winner': bid|None, 'bids': [...]}"""
    bids = collect_bids(use_case, **kw)
    return {"winner": bids[0] if bids else None, "bids": bids}
