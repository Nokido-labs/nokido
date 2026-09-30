# -*- coding: utf-8 -*-
"""
forge_litellm_router.py — Façade litellm.Router (PR-C switchboard).
================================================================================
Exploite le routing NATIF de litellm.Router (déjà dans la stack) au lieu de
réimplémenter cooldown/rate-limit/fallback à la main (cf. forge_llm_router.call_cascade).

`build_model_list(use_case, chain)` génère le model_list litellm DEPUIS
forge_llm_router.PROVIDERS (models/base_url/env_key/rpm/tpm/latency). Tous les
déploiements d'un même use_case partagent `model_name=use_case` → litellm.Router
load-balance + fallback + cooldown AUTOMATIQUEMENT dans le groupe.

NB : ce module N'EST PAS encore branché dans call_cascade (PR-D, derrière flag
FORGE_USE_LITELLM_ROUTER). Les pré-filtres souverains Nokido (firewall, persona,
is_dead_end, quota, host_cap, endocrine, route_with_dt) restent AUTOUR du Router.
"""
from __future__ import annotations

import os

__FORGE_COLOR__ = "GREEN"


def _providers():
    from nokido_agent.app.forge_llm_router import PROVIDERS

    return PROVIDERS


def build_model_list(use_case: str, chain: list[str] | None = None, providers: dict | None = None) -> list[dict]:
    """Génère le model_list litellm pour un use_case. Si chain=None, sélectionne les
    providers dont le `use_case` matche. Pur data (testable sans litellm)."""
    providers = providers if providers is not None else _providers()
    if chain is None:
        chain = [n for n, p in providers.items() if use_case in (p.get("use_case") or [])]
    ml: list[dict] = []
    for name in chain:
        p = providers.get(name)
        if not p or not p.get("models"):
            continue
        params = {"model": p["models"][0]}
        if p.get("rpm"):
            params["rpm"] = p["rpm"]
        if p.get("tpm"):
            params["tpm"] = p["tpm"]
        if p.get("base_url"):
            params["api_base"] = p["base_url"]
        env_key = p.get("env_key")
        if env_key:
            val = os.environ.get(env_key)
            if val:
                params["api_key"] = val
        ml.append(
            {
                "model_name": use_case,
                "litellm_params": params,
                "model_info": {"provider": name, "latency": p.get("latency", 1000)},
            }
        )
    return ml


def build_router(
    use_case: str,
    chain: list[str] | None = None,
    strategy: str = "latency-based-routing",
    cooldown_time: int = 60,
    allowed_fails: int = 1,
):
    """Construit un litellm.Router pour le use_case (load-balance + fallback + cooldown
    natifs). None si aucun déploiement ou litellm indispo. Cache par use_case."""
    ml = build_model_list(use_case, chain)
    if not ml:
        return None
    try:
        import litellm

        return litellm.Router(
            model_list=ml,
            routing_strategy=strategy,
            cooldown_time=cooldown_time,
            allowed_fails=allowed_fails,
            num_retries=0,
        )
    except Exception:
        return None


_router_cache: dict[str, object] = {}


def get_router(use_case: str):
    """Singleton par use_case (cache). None si non constructible."""
    if use_case not in _router_cache:
        r = build_router(use_case)
        if r is not None:
            _router_cache[use_case] = r
    return _router_cache.get(use_case)
