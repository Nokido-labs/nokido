"""
forge_engrid_bridge.py — Pont entre le cycle autonome et l'architecture Engrid
===============================================================================
Remplace les appels LLM directs du cycle (Generator.generate, ollama_call)
par un routage intelligent via SpikeRouter → MetaCognitionGate → Orchestrator.

Usage dans TaskWorker._process :
    # Avant :
    return self._generator.generate(messages, max_tokens)

    # Après :
    from forge_engrid_bridge import engrid_generate
    return engrid_generate(messages, max_tokens, task_type="generate", context=task)

Interface :
    engrid_generate(messages, max_tokens, task_type, context) -> str
    engrid_audit(code, context)                                -> dict
    engrid_analyze(code, context)                              -> dict

Le bridge décide automatiquement du spike_type et de la sévérité
selon le task_type reçu du cycle.

Fallback : si Engrid est indisponible (Ollama down, SpikeRouter absent),
le bridge retombe sur Generator ou ollama_call directement — le cycle
ne se casse jamais.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Mapping task_type → spike_type + severity ──────────────────────────────
_TASK_TO_SPIKE = {
    "generate": ("user_intent", "medium"),
    "stream": ("user_intent", "medium"),
    "audit": ("vuln_discovery", "high"),
    "analyze": ("user_intent", "medium"),
    "surgery": ("pr_mutation", "medium"),
    "locate": ("user_intent", "low"),
}


# ══════════════════════════════════════════════════════════════════════════════
# LAZY INIT — Engrid instancié une seule fois, partagé
# ══════════════════════════════════════════════════════════════════════════════

_wrapper = None
_wrapper_ts: float = 0.0
_REINIT_AFTER = 3600.0  # réinitialise après 1h si inactif


def _get_wrapper():
    """Retourne le ForgeCognitiveWrapper, en l'initialisant si nécessaire."""
    global _wrapper, _wrapper_ts
    if _wrapper is not None:
        return _wrapper
    try:
        import sys

        root = str(Path(__file__).resolve().parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from nokido_agent.app.forge_engrid_engine import ForgeCognitiveWrapper

        _wrapper = ForgeCognitiveWrapper(
            ollama_url="http://127.0.0.1:11434/api/generate",
        )
        _wrapper_ts = time.time()
        logger.info("[EngridBridge] ForgeCognitiveWrapper initialisé")
    except Exception as e:
        logger.warning(f"[EngridBridge] Init impossible: {e} — fallback direct")
    return _wrapper


# ══════════════════════════════════════════════════════════════════════════════
# CONVERTISSEUR messages → prompt
# ══════════════════════════════════════════════════════════════════════════════


def _messages_to_prompt(messages: list[dict]) -> str:
    """
    Convertit la liste de messages (format OpenAI) en un prompt texte.
    Préserve les rôles pour que le contexte soit clair.
    """
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            parts.append(f"[SYSTÈME]\n{content}")
        elif role == "assistant":
            parts.append(f"[ASSISTANT]\n{content}")
        else:
            parts.append(content)
    return "\n\n".join(parts).strip()


# ══════════════════════════════════════════════════════════════════════════════
# INTERFACE PRINCIPALE
# ══════════════════════════════════════════════════════════════════════════════


def engrid_generate(
    messages: list[dict],
    max_tokens: int = 512,
    task_type: str = "generate",
    context: dict | None = None,
    fallback_fn=None,
) -> str:
    """
    Route une génération LLM via l'architecture Engrid.

    Args:
        messages    : liste de messages (format OpenAI)
        max_tokens  : nombre max de tokens à générer
        task_type   : type de tâche ("generate"|"stream"|"surgery"|...)
        context     : métadonnées de la tâche (fichier cible, loop_id, etc.)
        fallback_fn : callable fallback si Engrid indisponible
                      signature: (messages, max_tokens) -> str

    Returns:
        str : réponse générée
    """
    t0 = time.perf_counter()
    prompt = _messages_to_prompt(messages)
    ctx = context or {}

    spike_type, severity = _TASK_TO_SPIKE.get(task_type, ("user_intent", "medium"))

    # Enrichissement du spike avec contexte loop
    target_file = ctx.get("target_file", ctx.get("source", ""))
    loop_id = ctx.get("loop_id", "")
    github_intel = ctx.get("github_intel", "")

    if target_file:
        prompt = f"[CIBLE: {target_file}]\n\n{prompt}"
    if loop_id:
        prompt = f"[LOOP: {loop_id}]\n\n{prompt}"

    wrapper = _get_wrapper()

    if wrapper is not None:
        try:
            report = wrapper.run_mission(
                prompt=prompt,
                target_code=ctx.get("code", ctx.get("source", "")),
                context=github_intel,
                severity=severity,
            )
            if report.get("status") == "COMPLETED" and report.get("vision"):
                elapsed = (time.perf_counter() - t0) * 1000
                sys_used = report.get("telemetry", {}).get("system_used", "?")
                conf = report.get("telemetry", {}).get("confidence", 0)
                logger.info(f"[EngridBridge] {task_type} → {sys_used} conf={conf:.2f} {elapsed:.0f}ms")
                return report["vision"]
        except Exception as e:
            logger.warning(f"[EngridBridge] Engrid erreur: {e} — fallback")

    # Fallback direct
    if fallback_fn is not None:
        try:
            return fallback_fn(messages, max_tokens)
        except Exception as e:
            logger.error(f"[EngridBridge] Fallback aussi échoué: {e}")

    return f"[EngridBridge] Pas de réponse disponible pour task={task_type}"


def engrid_audit(code: str, context: dict | None = None, fallback_fn=None) -> dict:
    """
    Route un audit de code via Engrid (spike vuln_discovery, severity=high).
    Retourne le format attendu par TaskWorker : dict avec clés 'issues', 'score'.
    """
    ctx = context or {}
    wrapper = _get_wrapper()

    prompt = (
        f"AUDIT DE SÉCURITÉ — analyse ce code et liste les vulnérabilités.\n\n"
        f"```python\n{code[:4000]}\n```\n\n"
        "Format de réponse : liste des problèmes avec sévérité (critical/high/medium/low/info)."
    )

    if wrapper is not None:
        try:
            report = wrapper.run_mission(
                prompt=prompt,
                target_code=code,
                severity="high",
            )
            if report.get("status") == "COMPLETED":
                vision = report.get("vision", "")
                # Parser la réponse en dict structuré
                return _parse_audit_response(vision, code)
        except Exception as e:
            logger.warning(f"[EngridBridge] audit Engrid erreur: {e}")

    if fallback_fn:
        return fallback_fn(code)

    # Fallback AST minimal
    return _fallback_ast_audit(code)


def engrid_analyze(code: str, context: dict | None = None, fallback_fn=None) -> dict:
    """
    Route une analyse de code via Engrid (spike user_intent, severity=medium).
    Retourne le format attendu par TaskWorker.
    """
    wrapper = _get_wrapper()
    prompt = (
        f"ANALYSE DE CODE — décris la structure, les dépendances et les points d'amélioration.\n\n"
        f"```python\n{code[:4000]}\n```"
    )

    if wrapper is not None:
        try:
            report = wrapper.run_mission(
                prompt=prompt,
                target_code=code,
                severity="medium",
            )
            if report.get("status") == "COMPLETED":
                return {"analysis": report.get("vision", ""), "engrid": True}
        except Exception as e:
            logger.warning(f"[EngridBridge] analyze Engrid erreur: {e}")

    if fallback_fn:
        return fallback_fn(code)

    return {"analysis": "", "engrid": False, "error": "Engrid indisponible"}


# ══════════════════════════════════════════════════════════════════════════════
# PARSEURS DE RÉPONSE
# ══════════════════════════════════════════════════════════════════════════════


def _parse_audit_response(vision: str, code: str) -> dict:
    """Convertit la réponse Engrid en format audit standard."""
    import re

    issues = []
    severity_map = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
    # Chercher des patterns de vulnérabilités dans le texte
    for line in vision.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for sev in severity_map:
            if sev in line.lower():
                issues.append({"severity": sev, "description": line[:200]})
                break

    score = max(0, 100 - sum(severity_map.get(i["severity"], 0) * 10 for i in issues))
    return {
        "issues": issues,
        "score": score,
        "vision": vision[:500],
        "engrid": True,
    }


def _fallback_ast_audit(code: str) -> dict:
    """Audit AST minimal sans LLM."""
    import ast as _ast

    issues = []
    try:
        tree = _ast.parse(code)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call):
                func = (
                    getattr(node.func, "id", "")
                    or getattr(getattr(node.func, "attr", None), "__class__", type).__name__
                )
                if func in ("eval", "exec", "compile"):
                    issues.append({"severity": "high", "description": f"Appel dangereux: {func}()"})
    except SyntaxError as e:
        issues.append({"severity": "critical", "description": f"SyntaxError: {e}"})
    score = max(0, 100 - len(issues) * 20)
    return {"issues": issues, "score": score, "engrid": False}


# ══════════════════════════════════════════════════════════════════════════════
# PATCH MONKEY — injecte Engrid dans TaskWorker sans modifier brain_worker.py
# ══════════════════════════════════════════════════════════════════════════════


def patch_task_worker(worker) -> bool:
    """
    Monkey-patch un TaskWorker existant pour router ses appels LLM via Engrid.

    Usage dans Nokido.py ou forge_runtime.py :
        from forge_engrid_bridge import patch_task_worker
        patch_task_worker(app._brain_service._worker)

    Retourne True si le patch a réussi.
    """
    try:
        original_process = worker._process

        def _engrid_process(task_type: str, task: dict):
            if task_type in ("generate", "stream"):
                return engrid_generate(
                    messages=task.get("messages", []),
                    max_tokens=task.get("max_tokens", 512),
                    task_type=task_type,
                    context=task,
                    fallback_fn=lambda m, n: original_process("generate", task),
                )
            if task_type == "audit":
                return engrid_audit(
                    code=task.get("code", ""),
                    context=task,
                    fallback_fn=lambda c: original_process("audit", task),
                )
            if task_type == "analyze":
                return engrid_analyze(
                    code=task.get("code", ""),
                    context=task,
                    fallback_fn=lambda c: original_process("analyze", task),
                )
            # Tâches non-LLM (embed, surgery, locate) : chemin original
            return original_process(task_type, task)

        worker._process = _engrid_process
        logger.info("[EngridBridge] TaskWorker patché — LLM routé via Engrid")
        return True
    except Exception as e:
        logger.error(f"[EngridBridge] Patch échoué: {e}")
        return False
