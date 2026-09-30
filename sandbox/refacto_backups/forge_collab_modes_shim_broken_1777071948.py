from __future__ import annotations
# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-25 | VER:v_forge_collab_modes_shim
#FORGE:[score:99|agent:gemini-cli|temp:0.00|risk:0.01|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: SHIM de compatibilité ascendante (Phase 3/3)
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:99|agent:gemini-cli|temp:0.00|risk:0.01|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"

# Re-exports massifs depuis le nouveau package modulaire
from .collab_modes import (
    # Core & Session
    CollabSession,
    _get_session_id,
    _log_turn,
    _log_mode,
    _log_end,
    
    # Arbitration & Synchro
    _meta_eval,
    _snap_rag_state,
    _detect_consensus,
    _wait_for_agent,
    
    # Participants & Ask Helpers
    _smart_ask,
    _nokido_ask,
    _ollama_ask,
    _gemini_ask,
    _claude_ask,
    _forge_synthesize,
    
    # Legacy & Sync Wrappers
    ollama_ask_sync,
    gemini_ask_sync,
    
    # Orchestration Modes
    run_mode_auto,
    run_mode_ping,
    run_mode_ping_v2,
    run_mode_chef,
    run_mode_debat,
    run_mode_cline,
    detect_best_model,
    
    # Dispatch
    run_collab
)

# Constantes utilitaires préservées
from .collab_modes.mode_ping import PARTICIPANT_DELAYS, PARTICIPANT_LABELS
