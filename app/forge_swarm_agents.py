# -*- coding: utf-8 -*-
"""forge_swarm_agents.py - Catalogue d Agents specialises par provider+use-case.

Pattern : 1 Agent par modele free-tier joignable (cf. forge_provider_specs +
forge_llm_router.PROVIDERS). Resolution = factory functions qui retournent
un forge_handoff.Agent pre-configure (instructions, mode, provider, model).

Les Agents NE SONT PAS instancies automatiquement au demarrage ni invoques en
boucle : le caller doit les requisitionner explicitement via les helpers
all_specialists() / specialists_for_use_case() / runnable_specialists(),
puis injecter le set dans run_swarm(available_agents=...).

Regle d engagement (memoire feedback_cloud_llm_on_request 2026-05-22) :
les Agents cloud ne tournent que sur demande utilisateur explicite, jamais
en background. Le catalog rend les capacites VISIBLES, pas ACTIVES.

Regle d engagement (memoire feedback_paid_providers 2026-05-22) :
seuls les providers free-tier OU local sont autorises. Pas xAI, pas DeepSeek
API directe (uniquement via github_deepseek_v3 quota free), pas Anthropic.

Cross-ref :
- [[forge_handoff]] : Agent dataclass + run_swarm + dispatch multi-provider
- [[handoff_planning_mode]] : Agent.plan_first() pour gate <think>
- [[forge_provider_specs]] : tier + capabilities source de verite
- [[forge_llm_router]] : USE_CASE_CHAINS + PROVIDERS dict (dispatch reel)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

__FORGE_COLOR__ = "PURPLE"

# Path setup for sibling imports (mirror of forge_handoff._ensure_app_on_path)
_APP = Path(__file__).resolve().parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from nokido_agent.app.forge_handoff import Agent  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Provider key mapping — used by key_present_for() and runnable_specialists()
# ─────────────────────────────────────────────────────────────────────────────
# Source : forge_llm_router.PROVIDERS[name].env_key (mirrored here to avoid
# importing the heavy router module at catalog-read time).

PROVIDER_ENV_KEYS: dict[str, str] = {
    # Local — always "present"
    "ollama_local": "",
    "llamacpp_local": "",
    "lmstudio_native": "",
    # Cloud free-tier
    "groq_fast": "GROQ_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "sambanova_llama_70b": "SAMBANOVA_API_KEY",
    "sambanova_llama_405b": "SAMBANOVA_API_KEY",
    "sambanova": "SAMBANOVA_API_KEY",
    "github_codestral": "GITHUB_TOKEN",
    "github_gpt41_mini": "GITHUB_TOKEN",
    "github_gpt4o_mini": "GITHUB_TOKEN",
    "github_llama_70b": "GITHUB_TOKEN",
    "github_deepseek_v3": "GITHUB_TOKEN",
    "github_phi4_mini": "GITHUB_TOKEN",
    "github_cohere_rp": "GITHUB_TOKEN",
    "gemini_flash": "GEMINI_API_KEY",
    "gemini_flash_lite": "GEMINI_API_KEY",
    "gemini_pro": "GEMINI_API_KEY",
    "openrouter_glm5": "OPENROUTER_API_KEY",
    "openrouter_gpt_oss": "OPENROUTER_API_KEY",
    "openrouter_qwen_coder": "OPENROUTER_API_KEY",
    "openrouter_glm_air": "OPENROUTER_API_KEY",
    "cohere_command_r": "COHERE_API_KEY",
    "cohere_command_r_plus": "COHERE_API_KEY",
    "mistral_small": "MISTRAL_API_KEY",
    "mistral_large": "MISTRAL_API_KEY",
    "nvidia_nim": "NVIDIA_API_KEY",
    "hf_llama": "HF_TOKEN",
    "hf_qwen_coder": "HF_TOKEN",
}


def key_present_for(provider: str) -> bool:
    """Return True if the env var backing this provider is set.

    Local providers (ollama_local, llamacpp_local, lmstudio_native) always
    return True — the assumption is that the user has them running.
    Unknown providers return False (defensive default).
    """
    if provider not in PROVIDER_ENV_KEYS:
        return False
    env_key = PROVIDER_ENV_KEYS[provider]
    if not env_key:  # local
        return True
    return bool(os.environ.get(env_key, "").strip())


# ─────────────────────────────────────────────────────────────────────────────
# Catalog — Cloud free-tier specialists
# ─────────────────────────────────────────────────────────────────────────────


def code_groq() -> Agent:
    """Groq llama-3.3-70b-versatile — ultra-fast code completion."""
    return Agent(
        name="code_groq",
        instructions=(
            "Specialiste code Python/JS/Go/Rust. Reponses concises. "
            "Code complet, pas de demi-snippets. Pas de prose superflue."
        ),
        provider="groq_fast",
        model="code",
        mode="EXECUTE",
        text_handoff=True,
    )


def code_cerebras() -> Agent:
    """Cerebras WSE — ultra-low-latency Llama-70B inference."""
    return Agent(
        name="code_cerebras",
        instructions=("Specialiste code ultra-rapide (Cerebras WSE). Latence minimale, qualite Llama-3-70B."),
        provider="cerebras",
        model="code",
        mode="EXECUTE",
    )


def code_sambanova() -> Agent:
    """SambaNova RDU — heavy code / multi-file refactor with Llama-405B."""
    return Agent(
        name="code_sambanova",
        instructions=(
            "Specialiste code lourd, refactor multi-fichiers. Llama-405B via SambaNova RDU. Plan d abord, edit ensuite."
        ),
        provider="sambanova_llama_405b",
        model="code",
        mode="PLANNING",  # heavy refactor = sensible sink, force planning
    )


def code_codestral() -> Agent:
    """GitHub Models Codestral — code completion + fill-in-middle."""
    return Agent(
        name="code_codestral",
        instructions=("Specialiste completion code, fill-in-middle, refactor leger. Codestral via GitHub Models."),
        provider="github_codestral",
        model="code",
        mode="EXECUTE",
    )


def vision_gemini() -> Agent:
    """Gemini Flash — vision + 1M context multimodal."""
    return Agent(
        name="vision_gemini",
        instructions=(
            "Specialiste vision/multimodal + long context 1M tokens. "
            "Gemini 2.5 Flash. Decris images, parse PDFs longs, analyse video frames."
        ),
        provider="gemini_flash",
        model="context",
        mode="EXECUTE",
    )


def reasoning_glm5() -> Agent:
    """OpenRouter GLM-5 Turbo — logical reasoning free tier."""
    return Agent(
        name="reasoning_glm5",
        instructions=(
            "Specialiste raisonnement logique pas-a-pas. GLM-5 Turbo via OpenRouter free. Chain-of-thought explicite."
        ),
        provider="openrouter_glm5",
        model="reasoning",
        mode="EXECUTE",
    )


def tools_github_gpt4o() -> Agent:
    """GitHub Models gpt-4o-mini — structured tool-calling."""
    return Agent(
        name="tools_github_gpt4o",
        instructions=(
            "Specialiste tool-calling structure JSON. gpt-4o-mini via GitHub Models. Function calling reliable."
        ),
        provider="github_gpt4o_mini",
        model="tool_call",
        mode="EXECUTE",
    )


def rag_cohere_r() -> Agent:
    """Cohere Command-R — retrieval-augmented generation optimized."""
    return Agent(
        name="rag_cohere_r",
        instructions=(
            "Specialiste RAG / retrieval-augmented generation. Command-R. Cite tes sources, marque l incertitude."
        ),
        provider="cohere_command_r",
        model="context",
        mode="EXECUTE",
    )


def french_mistral() -> Agent:
    """Mistral Small — French + EU sovereignty."""
    return Agent(
        name="french_mistral",
        instructions=("Specialiste francais et souverainete EU/RGPD. Mistral Small. Reponses en francais par defaut."),
        provider="mistral_small",
        model="eu",
        mode="EXECUTE",
    )


def vision_nvidia_nim() -> Agent:
    """NVIDIA NIM — hosted NVIDIA models (vision-capable)."""
    return Agent(
        name="vision_nvidia_nim",
        instructions=("Specialiste NVIDIA models hostes (NIM). Bon pour code et vision specialisee."),
        provider="nvidia_nim",
        model="general",
        mode="EXECUTE",
    )


def reasoning_sambanova_70b() -> Agent:
    """SambaNova Llama-70B — reasoning at low latency."""
    return Agent(
        name="reasoning_sambanova_70b",
        instructions=("Specialiste raisonnement rapide. Llama-3.3-70B via SambaNova RDU. Concis, factuel."),
        provider="sambanova_llama_70b",
        model="reasoning",
        mode="EXECUTE",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Catalog — Local specialists (Ollama / llama.cpp)
# ─────────────────────────────────────────────────────────────────────────────


def code_local_qwen() -> Agent:
    """Ollama qwen2.5-coder:7b — sovereign local code."""
    return Agent(
        name="code_local_qwen",
        instructions=(
            "Specialiste code souverain local. qwen2.5-coder:7b q4_K_M via Ollama. Tout reste sur la machine."
        ),
        provider="ollama_local",
        model="qwen2.5-coder:7b-instruct-q4_K_M",
        mode="EXECUTE",
    )


def reasoning_local_deepseek() -> Agent:
    """Ollama deepseek-r1:7b — local reasoning (thinking model)."""
    return Agent(
        name="reasoning_local_deepseek",
        instructions=("Specialiste raisonnement local. deepseek-r1:7b via Ollama. Utilise <think> pour decomposer."),
        provider="ollama_local",
        model="deepseek-r1:7b",
        mode="EXECUTE",
    )


def code_local_llamacpp() -> Agent:
    """llama.cpp native server :8091 — Qwen2.5-Coder-7B with speculative draft."""
    return Agent(
        name="code_local_llamacpp",
        instructions=(
            "Specialiste code ultra-rapide local. llama-server :8091 (Qwen2.5-Coder-7B + speculative 1.5B draft)."
        ),
        provider="llamacpp_local",
        model="laforge-coder",
        mode="EXECUTE",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Use-case routing table — drives specialists_for_use_case()
# ─────────────────────────────────────────────────────────────────────────────

_FACTORY_BY_USE_CASE: dict[str, list] = {
    "code": [code_groq, code_cerebras, code_sambanova, code_codestral, code_local_qwen, code_local_llamacpp],
    "vision": [vision_gemini, vision_nvidia_nim],
    "reasoning": [reasoning_glm5, reasoning_sambanova_70b, reasoning_local_deepseek],
    "rag": [rag_cohere_r, vision_gemini],  # gemini = long-context RAG
    "tools": [tools_github_gpt4o, code_local_qwen],  # qwen tool_call OK
    "french": [french_mistral],
    "eu": [french_mistral],
}

_ALL_FACTORIES: list = [
    # Cloud
    code_groq,
    code_cerebras,
    code_sambanova,
    code_codestral,
    vision_gemini,
    reasoning_glm5,
    tools_github_gpt4o,
    rag_cohere_r,
    french_mistral,
    vision_nvidia_nim,
    reasoning_sambanova_70b,
    # Local
    code_local_qwen,
    reasoning_local_deepseek,
    code_local_llamacpp,
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def all_specialists() -> list[Agent]:
    """Instantiate every specialist Agent in the catalog.

    Cheap call — Agents are pure dataclasses, no I/O. Use this to populate
    the available_agents registry in run_swarm() when you want the full set.
    """
    return [factory() for factory in _ALL_FACTORIES]


def specialists_for_use_case(use_case: str) -> list[Agent]:
    """Filter specialists by domain. Unknown use_case returns [].

    Valid keys : "code", "vision", "reasoning", "rag", "tools", "french", "eu".
    """
    factories = _FACTORY_BY_USE_CASE.get(use_case, [])
    return [factory() for factory in factories]


def runnable_specialists(host_info: Optional[dict] = None) -> list[Agent]:
    """Return only specialists actually reachable on this host.

    Cloud specialist : kept if env_key is present (cf. key_present_for).
    Local specialist : kept if forge_host_capabilities.can_run_locally OK
                       (best-effort — kept by default if module missing).
    """
    try:
        from nokido_agent.app.forge_host_capabilities import can_run_locally  # type: ignore

        _has_host_cap = True
    except Exception:
        _has_host_cap = False
        can_run_locally = None  # type: ignore

    out: list[Agent] = []
    for agent in all_specialists():
        prov = agent.provider or ""
        if prov in ("ollama_local", "llamacpp_local", "lmstudio_native", "ollama_mimo_v2"):
            if _has_host_cap and can_run_locally is not None:
                ok, _reason = can_run_locally(agent.model, host_info)
                if not ok:
                    continue
            out.append(agent)
        else:
            if key_present_for(prov):
                out.append(agent)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Safety assertions — runtime guard against paid-provider drift
# ─────────────────────────────────────────────────────────────────────────────

# Providers explicitly forbidden by memory feedback_paid_providers (2026-05-22).
FORBIDDEN_PROVIDERS = frozenset(
    {
        "xai_grok3",
        "xai_grok3_mini",  # xAI paid
        "deepseek_api",  # DeepSeek paid direct
        "anthropic",
        "anthropic_api",
        "claude_api",  # Anthropic direct paid
    }
)


def _assert_no_forbidden() -> None:
    """Raise if any catalog factory uses a forbidden provider.

    Called automatically at module import time so accidental additions
    fail fast at first import (cheap insurance — runs once).
    """
    bad: list[str] = []
    for factory in _ALL_FACTORIES:
        agent = factory()
        if agent.provider in FORBIDDEN_PROVIDERS:
            bad.append(f"{factory.__name__} -> {agent.provider}")
    if bad:
        raise RuntimeError("forbidden paid provider in swarm catalog (cf. feedback_paid_providers): " + ", ".join(bad))


_assert_no_forbidden()
