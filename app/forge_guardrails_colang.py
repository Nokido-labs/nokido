# -*- coding: utf-8 -*-
"""
forge_guardrails_colang.py — Couche déclarative Colang-style ADVISORY (shadow-only).
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from nokido_agent.app.forge_prompt_guard import detect_injection

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CO_FILE = ROOT / "config" / "guardrails.co"

def _strip_accents(s: str) -> str:
    """
    Supprime les accents et signes diacritiques d'une chaîne (e.g. 'désactive' -> 'desactive').
    """
    if not s:
        return ""
    nfkd_form = unicodedata.normalize('NFKD', s)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

def parse_guardrails_co() -> tuple[dict[str, list[str]], dict[str, str]]:
    """
    Parse le fichier config/guardrails.co de manière robuste.
    Retourne (intents_dict, actions_dict).
    """
    intents: dict[str, list[str]] = {}
    actions: dict[str, str] = {}
    
    if not CO_FILE.exists():
        return intents, actions

    try:
        content = CO_FILE.read_text("utf-8")
        current_intent = None
        current_action = None
        
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
                
            # Détection des blocs intents
            m_intent = re.match(r"define user intent\s+(\w+)", line)
            if m_intent:
                current_intent = m_intent.group(1)
                intents[current_intent] = []
                current_action = None
                continue
                
            # Détection des blocs actions
            m_action = re.match(r"define bot action\s+(\w+)", line)
            if m_action:
                current_action = m_action.group(1)
                current_intent = None
                continue
                
            # Lecture des phrases d'intent ou d'action
            if current_intent and line.startswith('"') and line.endswith('"'):
                phrase = line.strip('"')
                intents[current_intent].append(phrase)
            elif current_action and line.startswith('"') and line.endswith('"'):
                phrase = line.strip('"')
                actions[current_action] = phrase
    except Exception as e:
        logger.warning(f"Error parsing guardrails.co: {e}")
        
    return intents, actions


def check_guardrails(task: str) -> dict[str, Any]:
    """
    Évalue si la tâche enfreint les rails conversationnels.
    Retourne {"blocked": bool, "intent": str, "response": str}.
    """
    if not task:
        return {"blocked": False, "intent": "", "response": ""}

    intents, actions = parse_guardrails_co()
    refuse_response = actions.get(
        "refuse_subversion", 
        "I cannot comply with this request. It violates the system's alignment invariants and safety policies."
    )

    # 1. Recherche via NeMo Guardrails en subprocess si disponible (optionnel, shadow)
    
    # 2. Fallback pur-Python mirroitant les règles
    # A. Utilisation de forge_prompt_guard.detect_injection
    try:
        res = detect_injection(task)
        if res.detected:
            return {
                "blocked": True,
                "intent": "prompt_injection",
                "response": refuse_response
            }
    except Exception as e:
        logger.warning(f"Error calling detect_injection in guardrails: {e}")

    # B. Match textuel des phrases de guardrails.co (case-insensitive & accent-insensitive)
    task_clean = _strip_accents(task).lower().strip()
    for intent_name, phrases in intents.items():
        for phrase in phrases:
            phrase_clean = _strip_accents(phrase).lower().strip()
            # Si la phrase est une sous-chaîne ou si elle matche une regex simple
            if phrase_clean in task_clean:
                return {
                    "blocked": True,
                    "intent": intent_name,
                    "response": refuse_response
                }

    return {"blocked": False, "intent": "", "response": ""}


def shadow_compare(promptguard_verdict: bool, colang_verdict: dict[str, Any], task: str) -> None:
    """
    Compare le verdict réel (promptguard_verdict) et le verdict Colang (colang_verdict).
    LOG les divergences sans bloquer.
    """
    c_blocked = colang_verdict.get("blocked", False)
    if promptguard_verdict != c_blocked:
        logger.warning(
            f"[SHADOW_GUARDRAILS_DIVERGENCE] Task={task[:100]} | "
            f"PromptGuard={promptguard_verdict} Colang={colang_verdict}"
        )
