"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_context
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
# forge_context.py — Registre central de Nokido
# Point de vérité unique pour tous les singletons.

import sys as _sys
import json as _json
from pathlib import Path as _Path

# ── Singletons ────────────────────────────────────────────────────────────────
rag_engine = None
version_manager = None
settings = None
ssh_manager = None
orchestrator = None
prefect_manager = None
agentic_engine = None
gemini_bridge = None
llm_engine = None  # LlamaCppBridge — moteur local llama-cpp-python
hw_info = None  # dict hardware.json — chargé par forge_hw au boot

# ── Mode orchestration (partagé Claude ↔ Cline via bridge_state.json) ────────
active_mode = "AUTO"  # AUTO | CLINE | CHEF | DEBAT | PING
permissions = "STANDARD"  # STANDARD | FULL

_STATE_PATH = _Path(__file__).resolve().parent.parent / "sandbox" / "bridge_state.json"


# REMOVED 2026-04-16: def get_active_mode(...) — orpheline (0 import, 0 usage)


def set_active_mode(mode: str, reason: str = "") -> None:
    """Écrit le mode dans bridge_state.json — visible par Claude et Cline."""
    global active_mode, permissions
    active_mode = mode
    if mode == "CHEF":
        permissions = "FULL"
    else:
        permissions = "STANDARD"
    try:
        import time

        s = {}
        if _STATE_PATH.exists():
            try:
                s = _json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        s["active_mode"] = mode
        s["permissions"] = permissions
        s["last_switch"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        s["switch_reason"] = reason
        try:
            from nokido_agent.app.forge_hub_storage import atomic_write

            atomic_write(_STATE_PATH, _json.dumps(s, indent=2, ensure_ascii=False))
        except ImportError:
            _STATE_PATH.write_text(_json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(f"set_active_mode: {e}")


# REMOVED 2026-04-16: def update_agent_status(...) — orpheline (0 import, 0 usage)


# REMOVED 2026-04-16: def push_notification(...) — orpheline (0 import, 0 usage)


# REMOVED 2026-04-16: def pop_notifications(...) — orpheline (0 import, 0 usage)


# ── Accesseurs avec fallback __main__ ─────────────────────────────────────────


def get_rag_engine() -> object:
    """Get rag engine."""
    if rag_engine is not None:
        return rag_engine
    m = _sys.modules.get("__main__")
    return getattr(m, "rag_engine", None) if m else None


def get_version_manager() -> object:
    """Get version manager."""
    if version_manager is not None:
        return version_manager
    m = _sys.modules.get("__main__")
    return getattr(m, "version_manager", None) if m else None


def get_settings() -> object:
    """Get settings."""
    if settings is not None:
        return settings
    m = _sys.modules.get("__main__")
    return getattr(m, "settings", None) if m else None


def get_ssh_manager() -> object:
    """Get ssh manager."""
    if ssh_manager is not None:
        return ssh_manager
    m = _sys.modules.get("__main__")
    return getattr(m, "ssh_manager", None) if m else None


def get_orchestrator() -> object:
    """Get orchestrator."""
    if orchestrator is not None:
        return orchestrator
    m = _sys.modules.get("__main__")
    return getattr(m, "_global_orchestrator", None) if m else None


def get_prefect_manager() -> object:
    """Get prefect manager."""
    if prefect_manager is not None:
        return prefect_manager
    m = _sys.modules.get("__main__")
    return getattr(m, "prefect_manager", None) if m else None


def get_agentic_engine() -> object:
    """Get agentic engine."""
    if agentic_engine is not None:
        return agentic_engine
    m = _sys.modules.get("__main__")
    return getattr(m, "agentic_engine", None) if m else None


# REMOVED 2026-04-16: def get_hw(...) — orpheline (0 import, 0 usage)


# REMOVED 2026-04-16: def get_hw_value(...) — orpheline (0 import, 0 usage)


def get_llm_engine() -> object:
    """Retourne le moteur LLM local (LlamaCppBridge) si disponible."""
    if llm_engine is not None:
        return llm_engine
    m = _sys.modules.get("__main__")
    return getattr(m, "llm_engine", None) if m else None


def get_gemini_bridge() -> object:
    """Get gemini bridge."""
    if gemini_bridge is not None:
        return gemini_bridge
    m = _sys.modules.get("__main__")
    return getattr(m, "gemini_bridge", None) if m else None


# ── Helper test-boot ──────────────────────────────────────────────────────────


class _TestContext:
    """Contexte minimal pour --test-boot."""

    def __init__(self) -> None:
        """Init."""
        self.ring = 1
        self.settings = get_settings()
        self.rag_engine = get_rag_engine()


def make_test_context() -> _TestContext:
    """Retourne un contexte de test minimal (ring=1). Utilisé par --test-boot."""
    return _TestContext()
