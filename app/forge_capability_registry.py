# -*- coding: utf-8 -*-
"""
forge_capability_registry.py — Façade UNIFIÉE des capacités LLM/agents.
================================================================================
Agrège (ne stocke pas) les 3 vues capacités déjà présentes :
- forge_provider_specs.PROVIDER_SPECS : providers cloud/local (capabilities/tier/quota)
- forge_edge_fleet : nœuds distribués (capabilities + models_loaded)
- forge_handoff : agents locaux (Agent.capabilities)

Porte d'entrée unique pour le routeur central ET (futur) Contract-Net.
Anti-dup : zéro nouvelle donnée — pur agrégateur des registres existants.
"""
from __future__ import annotations

__FORGE_COLOR__ = "GREEN"


def capabilities_of(provider: str) -> list[str]:
    """Capabilities d'un provider (depuis forge_provider_specs)."""
    try:
        from nokido_agent.app.forge_provider_specs import get_spec

        return list(get_spec(provider).get("capabilities", []))
    except Exception:
        return []


def has_capability(provider: str, capability: str) -> bool:
    return capability in capabilities_of(provider)


def providers_for(use_case: str, free_only: bool = False, include_edges: bool = False) -> list[str]:
    """Providers compatibles avec un use_case (capabilities requises satisfaites).
    Optionnellement étend aux nœuds edge_fleet exposant le use_case/capability."""
    out: list[str] = []
    try:
        from nokido_agent.app.forge_provider_specs import list_providers_for_use_case

        out = list(list_providers_for_use_case(use_case, free_only=free_only))
    except Exception:
        out = []
    if include_edges:
        try:
            from nokido_agent.app.forge_edge_fleet import list_edges
            from nokido_agent.app.forge_provider_specs import USE_CASE_SPECIALIZATIONS

            req = set(USE_CASE_SPECIALIZATIONS.get(use_case, {}).get("required", []))
            for e in list_edges():
                caps = e.get("capabilities") or {}
                edge_caps = set(caps.get("capabilities", [])) if isinstance(caps, dict) else set()
                if req and req.issubset(edge_caps):
                    out.append(f"edge:{e.get('name', '?')}")
        except Exception:
            pass
    return out


def reachable_providers_for(use_case: str, free_only: bool = False) -> list[str]:
    """providers_for ∩ slots réellement disponibles (best-effort, peut être lent).
    Si l'introspection des slots échoue, retombe sur providers_for (non filtré)."""
    base = providers_for(use_case, free_only=free_only)
    try:
        from nokido_agent.app.forge_llm_router import LLMRouter

        slots = getattr(LLMRouter(), "_slots", {})
        avail = {name for name, s in slots.items() if getattr(s, "is_available", False)}
        filtered = [p for p in base if p in avail]
        return filtered or base
    except Exception:
        return base


def summary() -> dict:
    """Inventaire compact pour debug : nb providers par capability."""
    try:
        from nokido_agent.app.forge_provider_specs import PROVIDER_SPECS
    except Exception:
        return {}
    counts: dict[str, int] = {}
    for spec in PROVIDER_SPECS.values():
        for c in spec.get("capabilities", []):
            counts[c] = counts.get(c, 0) + 1
    return counts
