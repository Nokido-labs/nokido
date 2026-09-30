# -*- coding: utf-8 -*-
"""
Package app.collab_modes - Orchestration de sessions de collaboration multi-agent.

Decompose en 11 modules pour lisibilite et testabilite :
- _core.py          : helpers de logging, session, CollabSession
- _arbitration.py   : meta-eval, consensus, snapshot RAG, wait_for_agent
- _participants.py  : 7 ask helpers (ollama, nokido, gemini, claude)
- legacy.py         : 2 sync wrappers (ollama_ask_sync, gemini_ask_sync)
- mode_auto.py      : mode AUTO
- mode_ping.py      : mode PING + ping_v2 + detect_best_model
- mode_chef.py      : mode CHEF
- mode_debat.py     : mode DEBAT
- mode_cline.py     : mode CLINE
- dispatch.py       : run_collab (entry point)

Voir docs/REFACTO_COLLAB_MODES_SPEC.md pour le plan refacto complet.

BACKWARD COMPAT :
Le shim forge_collab_modes.py wraps ce package pour preserver les imports
existants : `from forge_collab_modes import X` -> `from app.collab_modes import X`.
"""
from __future__ import annotations

# ── Core helpers ──────────────────────────────────────────────────────────────
from ._core import (
    CollabSession,
    _is_dev_mode,
    _spl_log,
    _get_session_id,
    _log_turn,
    _log_mode,
    _log_end,
    _header,
    _turn_header,
)

# ── Arbitration ───────────────────────────────────────────────────────────────
from ._arbitration import (
    _meta_eval,
    _snap_rag_state,
    _detect_consensus,
    _wait_for_agent,
)

# ── Phase 2 : Orchestration Modes
from .mode_auto import run_mode_auto
from .mode_ping import (
    run_mode_ping,
    run_mode_ping_v2,
    detect_best_model,
    PARTICIPANT_DELAYS,
    PARTICIPANT_LABELS,
)
from .mode_chef import run_mode_chef
from .mode_debat import run_mode_debat
from .mode_cline import run_mode_cline

# ── Phase 2 : Dispatcher unique
from .dispatch import run_collab

# ── Participants (ask helpers) ────────────────────────────────────────────────
from ._participants import (
    _smart_ask,
    _gemini_ask,
    _ollama_ask,
    _nokido_ask,
    _claude_ask,
    _forge_synthesize,
    _ask_participant,
)

# ── Legacy sync wrappers ──────────────────────────────────────────────────────
from .legacy import (
    ollama_ask_sync,
    gemini_ask_sync,
)

# Les modes et dispatch seront imports au moment ou ils existeront (phase 2 Gemini)
# et ajoutes a ce __init__.py dans la phase 3.

__all__ = [
    # Public API
    "CollabSession",
    # Core
    "_is_dev_mode",
    "_spl_log",
    "_get_session_id",
    "_log_turn",
    "_log_mode",
    "_log_end",
    "_header",
    "_turn_header",
    # Arbitration
    "_meta_eval",
    "_snap_rag_state",
    "_detect_consensus",
    "_wait_for_agent",
    # Participants
    "_smart_ask",
    "_gemini_ask",
    "_ollama_ask",
    "_nokido_ask",
    "_claude_ask",
    "_forge_synthesize",
    "_ask_participant",
    # Legacy
    "ollama_ask_sync",
    "gemini_ask_sync",
    # Orchestration
    "run_mode_auto",
    "run_mode_ping",
    "run_mode_ping_v2",
    "run_mode_chef",
    "run_mode_debat",
    "run_mode_cline",
    "detect_best_model",
    "run_collab",
    # Constants
    "PARTICIPANT_DELAYS",
    "PARTICIPANT_LABELS",
]
