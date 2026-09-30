"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_agent_hardware
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
forge_agents.py — Intelligence et routage des agents pour La Forge
===================================================================
Fusion de : roles.py · scoring.py · routage.py

Organisation :
  § 1 RÔLES        : AgentRole, system prompts, IntentRouter, RoleOrchestrator
  § 2 SCORING      : ArchitectureProfile, ModelScorer, benchmark dynamique
  § 3 ROUTAGE      : SmartRouter, PromptClassifier, AgentPlanner, OllamaParallelRunner

Les trois modules sont regroupés car ils forment un pipeline cohérent :
  AgentRole → ModelScorer (qui modèle pour ce rôle ?) → SmartRouter (exécution)

Usage dans Nokido.py :
    from forge_agents import (
        AgentRole, RoleOrchestrator, IntentRouter,
        ROLE_META, ROLE_SYSTEM_PROMPTS,
        ModelScorer, ArchitectureProfile,
        SmartRouter, OllamaParallelRunner, PromptClassifier,
        AgentPlanner, PromptCategory, RouteResult,
        init_router, get_router,
    )
"""


import aiohttp
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.core.settings import get_settings as _forge_settings  # noqa: F401

# Les types ci-dessous ont migre vers forge_agents lors du decoupage du module.
# Les commentaires « X importe depuis forge_agents » (plus bas) le DISAIENT deja,
# mais l'import n'avait jamais ete ecrit : le module levait donc NameError des sa
# premiere ligne executable (ROLE_ARCH_BONUS). Mesure et corrige le 2026-09-08,
# verrouille par tests/nr/test_agent_hardware_imports_nr.py.
#
# Pas de `except ImportError: pass` ici, contrairement au patron de app/agents/ :
# ces symboles servent AU NIVEAU MODULE, donc avaler l'echec ne ferait que le
# retransformer en NameError obscur quelques lignes plus bas. Le repli couvre le
# seul cas legitime : le depot lance avec app/ dans sys.path plutot que sa racine.
try:
    from app.forge_agents import (
        AgentRole,
        BenchResult,
        CPUArch,
        Distrib,
        OSFamily,
    )
except ImportError:
    from nokido_agent.app.forge_agents import (  # type: ignore[no-redef]
        AgentRole,
        BenchResult,
        CPUArch,
        Distrib,
        OSFamily,
    )

logger = logging.getLogger(__name__)

# =============================================================================
# ARCHITECTURE CIBLE
# =============================================================================

# OSFamily importé depuis forge_agents

# Distrib importé depuis forge_agents

# CPUArch importé depuis forge_agents

# ContainerRuntime importé depuis forge_agents


# ArchitectureProfile importé depuis forge_agents


# =============================================================================
# DÉTECTEUR D'ARCHITECTURE
# =============================================================================

# ArchitectureDetector importé depuis forge_agents


# =============================================================================
# SCORING ENRICHI — tient compte de l'architecture cible
# =============================================================================

# Pénalités de score appliquées si le modèle est mal adapté à la cible
# Format : (condition_fn(arch), rôles_affectés, pénalité)
ARCH_PENALTIES: List[Tuple] = [
    # Si la cible est Windows, pénaliser les modèles sans profil Windows
    (
        lambda arch: arch.os_family == OSFamily.WINDOWS,
        {AgentRole.LINUX_MGMT, AgentRole.ACTION_EXEC, AgentRole.DEVOPS},
        -2.0,
    ),
    # Si la cible est ARM64, légère pénalité sur les profils trop x86-centrés
    (
        lambda arch: arch.cpu_arch == CPUArch.ARM64,
        {AgentRole.DEVOPS, AgentRole.ACTION_EXEC},
        -0.5,
    ),
    # Alpine → pénalise les suggestions apt/yum
    (
        lambda arch: arch.distrib == Distrib.ALPINE,
        {AgentRole.PATCH_MGMT, AgentRole.LINUX_MGMT},
        -1.0,
    ),
]

# Bonus si profil du modèle inclut une mention spécifique (ex: "adguard", "pihole")
ROLE_ARCH_BONUS: Dict[AgentRole, Dict[Distrib, float]] = {
    AgentRole.DNS_PIHOLE: {Distrib.DEBIAN: 0.5, Distrib.UBUNTU: 0.5},
    AgentRole.LINUX_MGMT: {Distrib.UBUNTU: 0.5, Distrib.DEBIAN: 0.5, Distrib.RHEL: 0.5, Distrib.ARCH: 0.3},
    AgentRole.WINDOWS_MGMT: {Distrib.WINDOWS: 1.5},
    AgentRole.ACTIVE_DIR: {Distrib.WINDOWS: 1.5},
}


# ScoredModel importé depuis forge_agents


# =============================================================================
# BENCHMARK DYNAMIQUE (version allégée, sans dépendances loops.py)
# =============================================================================

BENCH_PROMPT = (
    "Réponds en 3 lignes max. Quels sont les 3 principaux risques de sécurité "
    "dans une config SSH par défaut sur Linux ?"
)


# BenchResult importé depuis forge_agents — le découpage avait retiré la classe
# et LAISSÉ son `@dataclass`, qui s'appliquait donc à _run_bench : le module
# mourait en « 'function' object has no attribute '__mro__' ». Retiré 2026-09-08.


async def _run_bench(ollama_url: str, model: str) -> BenchResult:
    """Benchmark rapide d'un modèle Ollama."""
    result = BenchResult(model=model)
    try:
        t0 = time.perf_counter()
        first_tok_t: Optional[float] = None
        tokens = 0
        reply_parts: List[str] = []

        async with aiohttp.ClientSession() as sess:
            async with sess.post(
                ollama_url,
                json={"model": model, "messages": [{"role": "user", "content": BENCH_PROMPT}], "stream": True},
                timeout=aiohttp.ClientTimeout(total=25, connect=4),
            ) as resp:
                if resp.status != 200:
                    result.available = False
                    return result
                async for raw in resp.content:
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw.decode("utf-8", errors="replace").strip())
                    except Exception:
                        continue
                    tok = data.get("message", {}).get("content", "")
                    if tok:
                        if first_tok_t is None:
                            first_tok_t = time.perf_counter()
                            result.latency_ms = (first_tok_t - t0) * 1000
                        tokens += len(tok.split())
                        reply_parts.append(tok)
                    if data.get("done"):
                        break

        elapsed = time.perf_counter() - t0
        result.tok_per_sec = tokens / max(elapsed, 0.1)
        reply = "".join(reply_parts)
        result.quality = _score_reply(reply)
    except Exception as e:
        logger.debug(f"Bench {model}: {e}")
        result.available = False
    return result


def _score_reply(reply: str) -> float:
    """Score reply.

    Args:
        reply: Description.
    """
    if not reply or len(reply) < 15:
        return 0.0
    s = 3.0
    keywords = [
        "ssh",
        "root",
        "password",
        "clé",
        "key",
        "port",
        "firewall",
        "auth",
        "permission",
        "sudo",
        "fail2ban",
        "brute",
    ]
    s += min(4.0, sum(0.5 for k in keywords if k in reply.lower()))
    if re.search(r"\d+\.", reply):
        s += 1.0
    words = len(reply.split())
    if 15 < words < 200:
        s += 1.0
    if len(reply) < 50:
        s -= 1.0
    return min(10.0, max(0.0, s))


# =============================================================================
# SCOREUR CENTRAL
# =============================================================================

# ModelScorer importé depuis forge_agents


# =============================================================================
