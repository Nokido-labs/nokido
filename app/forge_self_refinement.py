"""
forge_self_refinement.py — Phase I: Auto-amelioration multi-LLM
Boucle generate→critique→refine entre N LLMs locaux.
thought_interceptor: extrait les etapes de raisonnement.
#FORGE:[score:87|agent:claude-sonnet-4-6|temp:0.00|color:GREEN|attempt:1]
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"
FORGE_ORGAN = "cortex_prefrontal"

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("Nokido.SelfRefinement")

# ─────────────────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RefinementTurn:
    round_n: int
    generator: str
    critic: str
    draft: str
    critique: str
    refined: str
    thoughts: list[str]
    delta_score: float = 0.0  # amelioration estimee vs tour precedent


@dataclass
class RefinementResult:
    task: str
    final_output: str
    rounds: list[RefinementTurn]
    total_rounds: int
    converged: bool
    elapsed_s: float
    best_score: float = 0.0

    def summary(self) -> str:
        return (
            f"SelfRefinement: {self.total_rounds} rounds "
            f"converged={self.converged} score={self.best_score:.0%} "
            f"({self.elapsed_s:.1f}s)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Thought interceptor
# ─────────────────────────────────────────────────────────────────────────────

_THOUGHT_PATTERNS = [
    re.compile(r"<thinking>(.*?)</thinking>", re.S | re.I),
    re.compile(r"<think>(.*?)</think>", re.S | re.I),
    re.compile(r"\*\*Reasoning:\*\*(.*?)(?=\*\*|\Z)", re.S),
    re.compile(r"(?:First|Step \d+|Let me)[,:]?\s*(.{20,200})", re.I),
    re.compile(r"(?:I notice|I see|I think|I'll)[,:]?\s*(.{20,200})", re.I),
]


def thought_interceptor(text: str) -> list[str]:
    """Extrait les etapes de raisonnement d une reponse LLM."""
    thoughts: list[str] = []
    for pat in _THOUGHT_PATTERNS:
        for m in pat.finditer(text):
            t = re.sub(r"\s+", " ", m.group(1)).strip()
            if len(t) > 15:
                thoughts.append(t[:200])
    return list(dict.fromkeys(thoughts))[:8]


# ─────────────────────────────────────────────────────────────────────────────
# LLM adapters (local only — ring 3)
# ─────────────────────────────────────────────────────────────────────────────


async def _llm_generate(provider: str, prompt: str, system: str = "", timeout: float = 25.0) -> str:
    try:
        if provider == "ollama":
            from nokido_agent.app.forge_ollama import ollama_generate

            full = (f"[SYSTEM]\n{system}\n\n" if system else "") + prompt
            return await asyncio.wait_for(
                ollama_generate(full, model="qwen2.5-coder:7b-instruct-q4_K_M", max_tokens=512),
                timeout=timeout,
            )
        elif provider == "lmstudio":
            from nokido_agent.app.forge_lmstudio import lms_call

            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.append({"role": "user", "content": prompt})
            return await asyncio.wait_for(
                lms_call(msgs, max_tokens=512, temperature=0.3),
                timeout=timeout,
            )
    except Exception as e:
        logger.debug(f"{provider} generate failed: {e}")
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Scoring heuristique
# ─────────────────────────────────────────────────────────────────────────────


def _score_response(response: str, task: str) -> float:
    """Score heuristique: longueur, completude, pas d hallucination."""
    if not response:
        return 0.0
    score = 0.0
    # Longueur raisonnable (50-800 chars = bien)
    l = len(response)
    if 50 < l < 800:
        score += 0.3
    elif l >= 800:
        score += 0.15
    # Pas de signal confusion
    confusion = ["i don't know", "je ne sais pas", "impossible", "i cannot"]
    if not any(c in response.lower() for c in confusion):
        score += 0.3
    # Mots-cles de la tache presents
    task_words = set(task.lower().split())
    resp_words = set(response.lower().split())
    overlap = len(task_words & resp_words) / max(1, len(task_words))
    score += min(0.4, overlap * 0.8)
    return round(min(1.0, score), 3)


def _delta_score(prev: str, curr: str) -> float:
    """Estimation d amelioration: nouveau contenu introduit."""
    if not prev:
        return 0.5
    prev_words = set(prev.lower().split())
    curr_words = set(curr.lower().split())
    new_words = curr_words - prev_words
    return round(len(new_words) / max(1, len(curr_words)), 3)


# ─────────────────────────────────────────────────────────────────────────────
# Core refinement loop
# ─────────────────────────────────────────────────────────────────────────────

_CRITIQUE_SYSTEM = """You are a precise technical critic. Review the draft response and identify:
1. Factual errors or inaccuracies
2. Missing important details
3. Unclear or confusing parts
Be concise (max 100 words). End with: SCORE: X/10"""

_REFINE_SYSTEM = """You are a technical writer. Given a draft and its critique, produce an improved version.
Address all critique points. Keep what was good. Be concise and precise."""


async def _run_refinement_loop(
    task: str,
    providers: list[str],
    max_rounds: int,
    convergence_threshold: float,
) -> RefinementResult:
    t0 = time.monotonic()
    turns: list[RefinementTurn] = []
    current_draft = ""
    best_score = 0.0
    converged = False

    # Round 0: generation initiale
    gen_provider = providers[0]
    current_draft = await _llm_generate(gen_provider, task, timeout=25.0)
    if not current_draft:
        return RefinementResult(
            task=task,
            final_output="",
            rounds=[],
            total_rounds=0,
            converged=False,
            elapsed_s=round(time.monotonic() - t0, 2),
        )

    best_score = _score_response(current_draft, task)

    for round_n in range(1, max_rounds + 1):
        critic_provider = providers[round_n % len(providers)]
        gen_provider = providers[(round_n + 1) % len(providers)]

        # Critique
        critique_prompt = f"Task: {task}\n\nDraft:\n{current_draft}\n\nCritique this draft:"
        critique = await _llm_generate(critic_provider, critique_prompt, system=_CRITIQUE_SYSTEM, timeout=20.0)
        if not critique:
            break

        # Raffinage
        refine_prompt = f"Task: {task}\n\nDraft:\n{current_draft}\n\nCritique:\n{critique}\n\nImproved version:"
        refined = await _llm_generate(gen_provider, refine_prompt, system=_REFINE_SYSTEM, timeout=25.0)
        if not refined:
            break

        thoughts = thought_interceptor(critique) + thought_interceptor(refined)
        delta = _delta_score(current_draft, refined)
        new_score = _score_response(refined, task)

        turns.append(
            RefinementTurn(
                round_n=round_n,
                generator=gen_provider,
                critic=critic_provider,
                draft=current_draft[:200],
                critique=critique[:200],
                refined=refined[:200],
                thoughts=thoughts[:4],
                delta_score=delta,
            )
        )

        current_draft = refined
        best_score = max(best_score, new_score)

        # Convergence: delta trop faible = plus rien a ameliorer
        if delta < convergence_threshold:
            converged = True
            logger.info(f"Converged at round {round_n}: delta={delta:.3f}")
            break

    return RefinementResult(
        task=task,
        final_output=current_draft,
        rounds=turns,
        total_rounds=len(turns),
        converged=converged,
        elapsed_s=round(time.monotonic() - t0, 2),
        best_score=best_score,
    )


# ─────────────────────────────────────────────────────────────────────────────
# MCP entry points
# ─────────────────────────────────────────────────────────────────────────────


def forge_self_refine(
    task: str,
    providers: Optional[list[str]] = None,
    max_rounds: int = 3,
    convergence_threshold: float = 0.05,
) -> dict:
    """
    MCP-callable. Boucle generate->critique->refine multi-LLM.
    providers: ["ollama", "lmstudio"] (defaut).
    """
    if not providers:
        providers = ["ollama", "lmstudio"]

    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    result = loop.run_until_complete(_run_refinement_loop(task, providers, max_rounds, convergence_threshold))

    logger.info(result.summary())
    return {
        "final_output": result.final_output,
        "total_rounds": result.total_rounds,
        "converged": result.converged,
        "best_score": result.best_score,
        "elapsed_s": result.elapsed_s,
        "turns": [
            {
                "round": t.round_n,
                "generator": t.generator,
                "critic": t.critic,
                "delta": t.delta_score,
                "thoughts": t.thoughts[:2],
            }
            for t in result.rounds
        ],
    }


def forge_thought_intercept(text: str) -> list[str]:
    """MCP-callable. Extrait les etapes de raisonnement d un texte LLM."""
    return thought_interceptor(text)


if __name__ == "__main__":
    import json

    # Smoke test sans LLM — juste thought_interceptor + scoring
    sample = (
        "<thinking>First I need to analyze the buffer overflow. "
        "Then I'll compute the offset.</thinking>\n"
        "The vulnerability is a classic stack overflow at offset 40."
    )
    thoughts = thought_interceptor(sample)
    print(f"Thoughts: {thoughts}")
    score = _score_response(sample, "analyze buffer overflow")
    print(f"Score: {score}")
    delta = _delta_score("hello world", "hello world and more content here yes")
    print(f"Delta: {delta}")
    assert thoughts, "no thoughts extracted"
    assert score > 0, "score=0"
    print("forge_self_refinement smoke test PASS")
