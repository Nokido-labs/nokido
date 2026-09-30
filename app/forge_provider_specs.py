# -*- coding: utf-8 -*-
"""
forge_provider_specs.py — Catalogue specifications providers Nokido
=====================================================================
Source de verite pour :
- Tier (local / free / subscription_quota / paid_api)
- Quota mensuel/quotidien (post 2026-06-15 Agent SDK quota)
- Specialisation par use_case (code/vision/reasoning/long_context/tool_call)
- Cost per 1M tokens
- Context window

Cascade router (forge_llm_router.USE_CASE_CHAINS) consulte ce catalogue pour :
- Skip provider si quota epuise
- Selectionner provider matchant les capabilities requises
- Prefer free/local quand qualite suffisante

Anonymisation tiktoken : voir forge_token_monitor.count_text_tokens()
+ forge_sovereign_membrane.wrap() pour PII redaction granulaire pre-cloud.

Mise a jour : 2026-05-23 (migration `claude -p` mi-juin 2026).
"""

from __future__ import annotations
from typing import Literal

__FORGE_COLOR__ = "GREEN"

# Raison de peremption partagee par les slots GitHub Models. Meme fait que
# `forge_llm_router._PERIME_GITHUB` : une seule formulation, deux catalogues.
_PERIME_GITHUB_MODELS = (
    "2026-08-18 : backend GitHub Models RETIRE (410 Gone sur models.github.ai) — "
    "hors des chaines du routeur, conserve pour l'historique et le diagnostic"
)

Tier = Literal["local", "free", "subscription_quota", "paid_api"]
Capability = Literal[
    "chat", "code", "reasoning", "vision", "long_context", "tool_call", "agent", "rag", "multimodal", "thinking"
]


# Specs par provider (nom = match Provider.name dans forge_agent_proxy.py)
PROVIDER_SPECS: dict[str, dict] = {
    # =========================================================
    # Tier 0 — LOCAL FREE INFINI (priorite cascade)
    # =========================================================
    "ollama_local": {
        "tier": "local",
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 32000,
        "capabilities": ["chat", "code", "reasoning", "tool_call"],
        "notes": "qwen2.5-coder, deepseek-r1, llama 3.3, multimodels via ollama pull",
    },
    "llamacpp_local": {
        "tier": "local",
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 32000,
        "capabilities": ["chat", "code", "tool_call"],
        "notes": "qwen2.5-coder:7b-q4 :8080 ; --jinja pour tool calling",
    },
    "lmstudio_native": {
        "tier": "local",
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 8192,
        "capabilities": ["chat", "code"],
        "notes": "modeles loades manuellement, OpenAI-compat :1234",
    },
    # =========================================================
    # Tier 1 — CLOUD FREE QUOTA GENEREUX
    # =========================================================
    "groq": {
        "tier": "free",
        "monthly_calls": 30000,
        "daily_calls": 1000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 32768,
        "capabilities": ["chat", "code", "reasoning", "tool_call"],
        "notes": "llama-3.3-70b-versatile ultra-rapide (~0.5s)",
    },
    "gemini_flash": {
        "tier": "free",
        "monthly_calls": 45000,
        "daily_calls": 1500,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 1000000,
        "capabilities": ["chat", "code", "reasoning", "vision", "long_context", "multimodal"],
        "notes": "Google AI Studio free tier ; 1M context window",
    },
    "gemini_flash_lite": {
        "tier": "free",
        "monthly_calls": 100000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 1000000,
        "capabilities": ["chat", "code"],
    },
    "cohere_command_r": {
        "tier": "free",
        "monthly_calls": 1000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 128000,
        "capabilities": ["chat", "rag"],
        "notes": "Cohere trial free 1000 calls/month, RAG-optimise",
    },
    "cohere_command_r_plus": {
        "tier": "free",
        "monthly_calls": 1000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 128000,
        "capabilities": ["chat", "rag", "reasoning"],
    },
    "sambanova": {
        "tier": "free",
        "monthly_calls": 5000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 8192,
        "capabilities": ["chat", "reasoning"],
        "notes": "Llama-3.3-70B Reconfigurable Dataflow, free tier",
    },
    "sambanova_llama_405b": {
        "tier": "free",
        "monthly_calls": 1000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 8192,
        "capabilities": ["reasoning", "chat"],
    },
    # PERIMES le 2026-08-18 — GitHub a RETIRE le backend Models (410 Gone sur
    # https://models.github.ai/inference). `forge_llm_router` le savait deja : ses
    # sept slots `github_*` y portent `"perime": _PERIME_GITHUB` et AUCUN n'apparait
    # dans USE_CASE_CHAINS. Mais ce catalogue-ci, qui alimente `/api/providers` et donc
    # la page `/admin/providers`, les declarait encore `tier: "free"` sans une marque :
    # l'ecran offrait cinq fournisseurs gratuits MORTS depuis douze jours.
    # Deux catalogues du meme fait divergent des que l'un seul est corrige — d'ou le
    # garde `tests/nr/test_provider_catalogue_perime_nr.py`, qui les confronte.
    "github_gpt41_mini": {
        "tier": "free",
        "perime": _PERIME_GITHUB_MODELS,
        "monthly_calls": 1500,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 128000,
        "capabilities": ["chat", "code", "reasoning"],
        "notes": "GitHub Models free avec Copilot subscription",
    },
    "github_gpt4o_mini": {
        "tier": "free",
        "perime": _PERIME_GITHUB_MODELS,
        "monthly_calls": 1500,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 128000,
        "capabilities": ["chat", "code", "reasoning"],
    },
    "github_codestral": {
        "tier": "free",
        "perime": _PERIME_GITHUB_MODELS,
        "monthly_calls": 1500,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 32768,
        "capabilities": ["code"],
    },
    "github_llama_70b": {
        "tier": "free",
        "perime": _PERIME_GITHUB_MODELS,
        "monthly_calls": 1500,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 128000,
        "capabilities": ["chat", "code", "reasoning"],
    },
    "github_deepseek_v3": {
        "tier": "free",
        "perime": _PERIME_GITHUB_MODELS,
        "monthly_calls": 1500,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 64000,
        "capabilities": ["chat", "code", "reasoning"],
    },
    "openrouter_qwen_coder": {
        "tier": "free",
        "monthly_calls": 1000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 32000,
        "capabilities": ["code"],
        "notes": "qwen3-coder:free via OpenRouter",
    },
    "openrouter_gpt_oss": {
        "tier": "free",
        "monthly_calls": 1000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 32000,
        "capabilities": ["chat", "code"],
    },
    "openrouter_glm_air": {
        "tier": "free",
        "monthly_calls": 1000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 128000,
        "capabilities": ["chat", "reasoning"],
    },
    "openrouter_glm5": {
        "tier": "free",
        "monthly_calls": 1000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 128000,
        "capabilities": ["chat", "code", "reasoning", "vision"],
        "notes": "GLM-5 Turbo via OpenRouter free (Z AI, decouvert AA 2026-05-23)",
    },
    "ollama_mimo_v2": {
        "tier": "local",
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 32000,
        "capabilities": ["chat", "vision", "multimodal"],
        "notes": "Xiaomi MiMo v2 Omni multimodal (Ollama local) - DEPRECATED trop lourd VRAM",
    },
    "openrouter_mimo_v2": {
        "tier": "free",
        "monthly_calls": 1000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 32000,
        "capabilities": ["chat", "vision", "multimodal"],
        "notes": "Xiaomi MiMo v2 Omni via OpenRouter free - slug a valider openrouter.ai",
    },
    "cerebras": {
        "tier": "free",
        "monthly_calls": 10000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 8192,
        "capabilities": ["chat", "code"],
        "notes": "Beta free, ultra-rapide hardware",
    },
    "nvidia_nim": {
        "tier": "free",
        "monthly_calls": 1000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 32000,
        "capabilities": ["chat", "code"],
    },
    "hf_llama": {
        "tier": "free",
        "monthly_calls": 1000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 8000,
        "capabilities": ["chat"],
    },
    "kimi_k2": {
        "tier": "free",
        "monthly_calls": 500,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 200000,
        "capabilities": ["chat", "long_context"],
    },
    "kimi_thinking": {
        "tier": "free",
        "monthly_calls": 500,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 200000,
        "capabilities": ["reasoning", "thinking"],
    },
    "glm4": {
        "tier": "free",
        "monthly_calls": 1000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 128000,
        "capabilities": ["chat", "code"],
    },
    "glm5": {
        "tier": "free",
        "monthly_calls": 1000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 128000,
        "capabilities": ["chat", "reasoning"],
    },
    # =========================================================
    # Tier 2 — SUBSCRIPTION QUOTA LIMITE (surveille)
    # Post 2026-06-15 : claude_agent_sdk + claude_cli partagent pool
    # =========================================================
    "claude_agent_sdk": {
        "tier": "subscription_quota",
        "monthly_calls": 500,
        "monthly_tokens": 5_000_000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 200000,
        "capabilities": ["chat", "code", "reasoning", "vision", "long_context", "tool_call", "agent", "multimodal"],
        "notes": "Anthropic recommandation officielle post 2026-06-15 ; quota mensuel separe",
    },
    "claude_cli": {
        "tier": "subscription_quota",
        "monthly_calls": 500,
        "monthly_tokens": 5_000_000,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 200000,
        "capabilities": ["chat", "code", "reasoning", "vision", "long_context", "tool_call", "agent", "multimodal"],
        "notes": "Legacy `claude -p` ; meme pool quota Agent SDK post 2026-06-15",
    },
    "gemini_cli": {
        "tier": "subscription_quota",
        "monthly_calls": 1500,
        "cost_usd_per_1m_in": 0.0,
        "cost_usd_per_1m_out": 0.0,
        "context": 1000000,
        "capabilities": ["chat", "code", "reasoning", "vision", "long_context", "multimodal"],
        "notes": "Google AI Studio quota gratuit ; CLI headless spawn",
    },
    # =========================================================
    # Tier 3 — PAID API ad-hoc (last resort, premium tasks)
    # =========================================================
    "claude": {
        "tier": "paid_api",
        "cost_usd_per_1m_in": 3.0,
        "cost_usd_per_1m_out": 15.0,
        "context": 200000,
        "capabilities": ["chat", "code", "reasoning", "vision", "long_context", "tool_call", "agent", "multimodal"],
        "notes": "Anthropic API direct (sonnet-4) via OpenRouter ou direct",
    },
    "openai": {
        "tier": "paid_api",
        "cost_usd_per_1m_in": 2.5,
        "cost_usd_per_1m_out": 10.0,
        "context": 128000,
        "capabilities": ["chat", "code", "reasoning", "vision", "tool_call"],
    },
    "mistral_large": {
        "tier": "paid_api",
        "cost_usd_per_1m_in": 2.0,
        "cost_usd_per_1m_out": 6.0,
        "context": 128000,
        "capabilities": ["chat", "code", "reasoning"],
    },
    "mistral_small": {
        "tier": "paid_api",
        "cost_usd_per_1m_in": 0.20,
        "cost_usd_per_1m_out": 0.60,
        "context": 128000,
        "capabilities": ["chat", "code"],
    },
    "xai_grok3": {
        "tier": "paid_api",
        "cost_usd_per_1m_in": 5.0,
        "cost_usd_per_1m_out": 15.0,
        "context": 128000,
        "capabilities": ["chat", "reasoning"],
    },
    "xai_grok3_mini": {
        "tier": "paid_api",
        "cost_usd_per_1m_in": 0.30,
        "cost_usd_per_1m_out": 0.50,
        "context": 32000,
        "capabilities": ["chat"],
    },
    "deepseek": {
        "tier": "paid_api",
        "cost_usd_per_1m_in": 0.27,
        "cost_usd_per_1m_out": 1.10,
        "context": 64000,
        "capabilities": ["chat", "code", "reasoning"],
    },
    "perplexity": {
        "tier": "paid_api",
        "cost_usd_per_1m_in": 1.0,
        "cost_usd_per_1m_out": 1.0,
        "context": 128000,
        "capabilities": ["chat", "rag"],
        "notes": "search-augmented chat",
    },
}


# Specialisation par use_case : capacite minimum requise
USE_CASE_SPECIALIZATIONS: dict[str, dict] = {
    "code": {"required": ["code"], "preferred": ["tool_call"]},
    "reasoning": {"required": ["reasoning"], "preferred": ["long_context"]},
    "vision": {"required": ["vision"]},
    "long_doc": {"required": ["long_context"]},
    "agent": {"required": ["tool_call"], "preferred": ["agent"]},
    "rag": {"required": ["rag"], "preferred": ["long_context"]},
    "mermaid": {"required": ["code"]},
    "tool_call": {"required": ["tool_call"]},
    "speed": {"required": ["chat"]},
    "general": {"required": ["chat"]},
    "synthesis": {"required": ["chat"], "preferred": ["reasoning"]},
    "strategy": {"required": ["reasoning"]},
    "sentinel": {"required": ["chat"]},
    "inspect": {"required": ["chat"]},
    "context": {"required": ["chat"], "preferred": ["long_context", "rag"]},
    "debate": {"required": ["chat"], "preferred": ["reasoning"]},
    "collab": {"required": ["chat"]},
    "eu": {"required": ["chat"]},
    "mesh": {"required": ["chat"]},
    "orchestration": {"required": ["tool_call"]},
}


# Seuils alertes quota mensuel (% du quota)
QUOTA_ALERT_THRESHOLDS = [0.5, 0.8, 1.0]


def get_spec(provider_name: str) -> dict:
    """Retourne le spec d'un provider (vide si inconnu)."""
    return PROVIDER_SPECS.get(provider_name, {})


def get_tier(provider_name: str) -> str:
    """Retourne le tier ('local'|'free'|'subscription_quota'|'paid_api')."""
    return get_spec(provider_name).get("tier", "free")


def is_free(provider_name: str) -> bool:
    """True si provider local OR free tier (= jamais payant)."""
    return get_tier(provider_name) in ("local", "free")


def is_subscription_quota(provider_name: str) -> bool:
    """True si subscription mensuel (= surveille via quota tracker)."""
    return get_tier(provider_name) == "subscription_quota"


def is_paid(provider_name: str) -> bool:
    """True si API payante per-token (= last resort)."""
    return get_tier(provider_name) == "paid_api"


def matches_use_case(provider_name: str, use_case: str) -> bool:
    """True si provider satisfait capabilities requises du use_case."""
    spec = get_spec(provider_name)
    caps = set(spec.get("capabilities", []))
    req = USE_CASE_SPECIALIZATIONS.get(use_case, {}).get("required", [])
    return all(c in caps for c in req)


def list_providers_for_use_case(use_case: str, free_only: bool = False) -> list[str]:
    """Liste providers compatibles avec use_case, optionnel free-only."""
    out = []
    for name in PROVIDER_SPECS:
        if not matches_use_case(name, use_case):
            continue
        if free_only and not is_free(name):
            continue
        out.append(name)
    return out


def context_window(provider_name: str) -> int:
    """Context window max tokens (defaut 8000 si inconnu)."""
    return get_spec(provider_name).get("context", 8000)


def monthly_quota(provider_name: str) -> dict:
    """Retourne {'monthly_calls', 'monthly_tokens', 'daily_calls'} ou {} si illimite."""
    spec = get_spec(provider_name)
    out = {}
    for k in ("monthly_calls", "monthly_tokens", "daily_calls"):
        if k in spec:
            out[k] = spec[k]
    return out


def display_summary() -> str:
    """Print human-readable summary pour debug / inventory."""
    lines = []
    tiers_groups = {"local": [], "free": [], "subscription_quota": [], "paid_api": []}
    for name, spec in PROVIDER_SPECS.items():
        tiers_groups[spec["tier"]].append((name, spec))
    for tier_name, items in tiers_groups.items():
        lines.append(f"\n=== Tier: {tier_name} ({len(items)} providers) ===")
        for name, spec in items:
            caps = ",".join(spec.get("capabilities", []))
            quota = ""
            if "monthly_calls" in spec:
                quota = f" quota={spec['monthly_calls']}/mo"
            lines.append(f"  {name:30} ctx={spec.get('context', 0):>7} {quota:<20} caps={caps}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(display_summary())
