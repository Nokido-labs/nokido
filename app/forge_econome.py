# -*- coding: utf-8 -*-
"""
forge_econome.py — Organe ECONOME (gouverneur du cout cloud)
============================================================
Organe P2 jusqu'ici DORMANT (cf. forge_organ_agents : "budget cloud :
CORTISOL_QUOTA_CLOUD emis, gate s'en sert, PAS DE GOUVERNEUR SOURCE").

L'efferent existait deja et n'attendait qu'une source :
  - forge_llm_router.call_cascade : cortisol > 0.5 -> cascade LOCAL-ONLY.
  - forge_orchestration_gate : cortisol -> escalade cloud bloquee (garde cout).
  - forge_provider_quota.should_skip/filter_chain : ecarte les providers epuises.

L'ECONOME est la SOURCE : a chaque tick homeostatique il lit le cout reel du
jour (forge_token_monitor.daily_report = table token_usage) + la pression quota
(providers cloud epuises) et EMET CORTISOL_QUOTA_CLOUD proportionnellement
(forge_endocrine.release). Emission CONTINUE (vs 1x/jour par daily_report).

Anti-dup : reutilise daily_report (cout), should_skip (quota), endocrine.release
(emission). Ne re-tracke rien.
"""
from __future__ import annotations

import os
from typing import Optional

# Providers cloud tier-0 (free/quota) — pression quota = fraction epuisee.
CLOUD_TIER0 = (
    "groq", "cerebras", "nvidia", "mistral",
    "openrouter", "sambanova", "cohere", "gpt4o_github",
)

# Seuil doc : CORTISOL_QUOTA_CLOUD produite quand cost/daily_budget > 0.8.
RATIO_ONSET = 0.8
DEFAULT_DAILY_BUDGET_USD = 5.0
CORTISOL_TTL_S = 1800  # 30 min : re-emis chaque tick si le stress persiste, decay sinon.


def _daily_cost() -> float:
    """Cout cloud reel du jour ($) — reutilise forge_token_monitor.daily_report."""
    try:
        from nokido_agent.app.forge_token_monitor import daily_report
        return float(daily_report().get("daily_cost_usd", 0.0) or 0.0)
    except Exception:
        return 0.0


def _quota_pressure() -> float:
    """Fraction des providers cloud tier-0 epuises (quota >= 100%)."""
    try:
        from nokido_agent.app.forge_provider_quota import should_skip
    except Exception:
        return 0.0
    n = 0
    exhausted = 0
    for p in CLOUD_TIER0:
        n += 1
        try:
            if should_skip(p):
                exhausted += 1
        except Exception:
            pass
    return (exhausted / n) if n else 0.0


def _stress_level(ratio: float, quota_pressure: float) -> float:
    """Niveau de cortisol [0..1]. Cost-stress des ratio>0.8 ; quota-stress des 50% epuises."""
    cost_stress = 0.0
    if ratio >= RATIO_ONSET:
        cost_stress = min(1.0, 0.5 + (ratio - RATIO_ONSET) * 1.25)  # 0.8->0.5, 1.2->1.0
    quota_stress = 0.0
    if quota_pressure >= 0.5:
        quota_stress = min(1.0, quota_pressure)  # 0.5->0.5, 1.0->1.0
    return max(cost_stress, quota_stress)


def govern_budget(daily_budget: Optional[float] = None, emit: bool = True) -> dict:
    """Gouverne le cout cloud : lit cout+quota reels, emet CORTISOL_QUOTA_CLOUD.

    Retour = snapshot ECONOME. Re-emis chaque tick (source de l'efferent deja cable).
    N'emet PAS de cortisol si stress < 0.5 (laisse decroitre — un 0 raierait l'episode).
    """
    if daily_budget is None:
        try:
            daily_budget = float(os.environ.get("LAFORGE_DAILY_BUDGET_USD", DEFAULT_DAILY_BUDGET_USD))
        except Exception:
            daily_budget = DEFAULT_DAILY_BUDGET_USD

    cost = _daily_cost()
    ratio = (cost / daily_budget) if daily_budget > 0 else 0.0
    qp = _quota_pressure()
    stress = _stress_level(ratio, qp)

    emitted = False
    if emit and stress >= 0.5:
        try:
            from nokido_agent.app.forge_endocrine import release
            release(
                "CORTISOL_QUOTA_CLOUD",
                level=stress,
                ttl_s=CORTISOL_TTL_S,
                source="econome",
                reason=f"cost ${cost:.2f}/{daily_budget:.0f} ratio={ratio:.2f} quota_exhausted={qp:.0%}",
                meta={
                    "cost_usd_today": round(cost, 4),
                    "daily_budget": daily_budget,
                    "ratio": round(ratio, 3),
                    "quota_pressure": round(qp, 3),
                },
            )
            emitted = True
        except Exception:
            pass

    return {
        "ok": True,
        "cost_usd_today": round(cost, 4),
        "daily_budget": daily_budget,
        "ratio": round(ratio, 3),
        "quota_pressure": round(qp, 3),
        "stress": round(stress, 3),
        "cortisol_emitted": emitted,
        "recommendation": "local_first+agy" if stress >= 0.5 else "normal",
    }


def run_cycle() -> dict:
    """Alias homeostatique (convention des organes du tick)."""
    return govern_budget()
