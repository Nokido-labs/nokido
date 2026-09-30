# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_capabilities
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
forge_capabilities.py — Registre centralisé des capabilities optionnelles
==========================================================================
Remplace les patterns HAS_X dispersés dans tout le codebase.

Usage :
    from forge_capabilities import caps, check, require

    if caps.HAS_SNIF:
        ...

    @require("HAS_ONNX")
    def my_fn():
        ...
"""

import importlib
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("Nokido.Capabilities")


# ── Détection automatique des capabilities ────────────────────────────────
def _probe(module: str) -> bool:
    """Probe.

    Args:
        module: Description.
    """
    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False


@dataclass
class CapabilityRegistry:
    """Registre singleton des capabilities disponibles."""

    # Réseau
    HAS_SNIF: bool = field(default_factory=lambda: _probe("forge_network"))
    HAS_IDS: bool = field(default_factory=lambda: _probe("forge_network"))
    HAS_SWITCH: bool = field(default_factory=lambda: _probe("forge_network"))
    # ML / ONNX
    HAS_ONNX: bool = field(default_factory=lambda: _probe("forge_runtime"))
    HAS_NLU: bool = field(default_factory=lambda: _probe("forge_nlu"))
    HAS_PREDICTIF: bool = field(default_factory=lambda: _probe("forge_nlu"))
    # LLM
    HAS_OLLAMA: bool = True  # toujours tenté
    HAS_GEMINI: bool = field(default_factory=lambda: _probe("forge_gemini_bridge"))
    HAS_LITELLM: bool = field(default_factory=lambda: _probe("forge_litellm_bridge"))
    # Code
    HAS_SANDBOX: bool = field(default_factory=lambda: _probe("forge_code"))
    HAS_TREE_SITTER: bool = field(default_factory=lambda: _probe("tree_sitter"))
    # UI
    HAS_SKILLTREE: bool = field(default_factory=lambda: _probe("skilltree"))
    HAS_GUI_DEBUG: bool = field(default_factory=lambda: _probe("forge_gui_debug"))
    # Infra
    HAS_WEB_SEARCH: bool = field(default_factory=lambda: _probe("forge_web"))
    HAS_SERVICES: bool = field(default_factory=lambda: _probe("forge_services"))
    HAS_MEMORY: bool = field(default_factory=lambda: _probe("forge_memory"))
    HAS_ROUTAGE: bool = field(default_factory=lambda: _probe("forge_agents"))
    HAS_SCORING: bool = field(default_factory=lambda: _probe("forge_agents"))
    HAS_LOOPS: bool = field(default_factory=lambda: _probe("forge_agents"))
    # Scoring / routing
    HAS_DANGER_GUARD: bool = field(default_factory=lambda: _probe("forge_code"))

    def __getitem__(self, key: str) -> bool:
        """Getitem.

        Args:
            key: Description.
        """
        return getattr(self, key, False)


# Singleton
_caps: Optional[CapabilityRegistry] = None


def get_caps() -> CapabilityRegistry:
    """Get caps."""
    global _caps
    if _caps is None:
        _caps = CapabilityRegistry()
        enabled = [k for k, v in _caps.__dict__.items() if v]
        logger.debug(f"[Capabilities] {len(enabled)} actives: {enabled[:6]}...")
    return _caps


def check(cap_name: str) -> bool:
    """Vérifie si une capability est disponible."""
    return get_caps()[cap_name]


# Accès direct
caps = get_caps()
