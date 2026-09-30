"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_061812_astdocenri
#FORGE:[score:94|agent:AST-doc-enricher|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns injectés sur fonctions typées
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:94|agent:AST-doc-enricher|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
⚒ La Forge TUI v13 – Orchestration multi-agents, auto-amélioration, web search
"""

__version__ = "0.13.3"  # Bunker-Grade — Proxy-Trigger · MCP-Sentinel · Distillation · RAG-Kernel

# =============================================================================
# PURGE __pycache__ AU DÉMARRAGE
# Évite de charger des .pyc périmés (dossier __pycache__ + .pyc directs).
# =============================================================================
# Env vars Windows AVANT tout import — empêche les spawns multiprocessing
# de sentence_transformers / torch qui causent "No module named __main__"
import os as _os_early

_os_early.environ["TOKENIZERS_PARALLELISM"] = "false"
_os_early.environ.setdefault("OMP_NUM_THREADS", "1")
_os_early.environ.setdefault("MKL_NUM_THREADS", "1")
del _os_early

import sys, shutil as _shutil

# Fix path : ajouter la racine LaForge/ au sys.path pour permettre
# "from app.core.settings import ..." depuis forge_startup.py et consorts.
# Sans ca, ModuleNotFoundError: No module named 'app' quand lance via
# textual-serve (CWD != racine dans certains cas).
from pathlib import Path as _PathBoot

_ROOT_BOOT = _PathBoot(__file__).resolve().parent.parent
if str(_ROOT_BOOT) not in sys.path:
    sys.path.insert(0, str(_ROOT_BOOT))
del _PathBoot, _ROOT_BOOT

# [→ forge_startup.py] _purge_pycache
from nokido_agent.app.forge_orchestrator import OrchestratorManager, get_orchestrator
from nokido_agent.app.forge_startup import _purge_pycache as _ppc
from nokido_agent.app.forge_logging import debug_log  # noqa
from nokido_agent.app.bridge_cmd import dispatch_at as _bridge_dispatch_at  # forge_commands boot  # noqa
from nokido_agent.app.forge_ollama import ollama_call, ollama_stream  # noqa
from nokido_agent.app.forge_startup_logger import boot_step, boot_finalize  # noqa
from nokido_agent.app.forge_mem_watchdog import mem_checkpoint  # noqa

_ppc()
del _ppc, _shutil  # nettoyage namespace (_pathlib conservé)

# ── Répertoires : app/ → racine parent ───────────────────────────────────────
import pathlib as _pl

_APP_DIR = _pl.Path(__file__).resolve().parent  # …/LaForge/app/
_ROOT_DIR = _APP_DIR.parent  # …/LaForge/
_LOGS_DIR = _ROOT_DIR / "logs"
_DATA_DIR = _ROOT_DIR / "data"
for _d in (_LOGS_DIR, _DATA_DIR):
    _d.mkdir(parents=True, exist_ok=True)
del _pl, _d

# =============================================================================
# IMPORTS
# =============================================================================
import asyncio
import aiohttp
import asyncssh
import os
import logging
from logging.handlers import RotatingFileHandler
import json
import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable, Tuple
from pathlib import Path

# ── forge_agents : rôles + scoring + routage (ex-roles/scoring/routage) ─────
try:
    from nokido_agent.app.forge_agents import (
        AgentRole as OpsAgentRole,
        RoleOrchestrator,  # noqa: F401
        IntentRouter,  # noqa: F401
        ROLE_META,  # noqa: F401
        ROLE_SYSTEM_PROMPTS as OPS_PROMPTS,  # noqa: F401
        OPS_ROLES,  # noqa: F401
        CODE_ROLES,  # noqa: F401
        ModelScorer,  # noqa: F401
        ArchitectureProfile,  # noqa: F401
        ArchitectureDetector,  # noqa: F401
    )

    HAS_LOOPS = True
    HAS_SCORING = True
except ImportError:
    HAS_LOOPS = HAS_SCORING = False
finally:
    pass  # imports forge_agents terminés

# ── forge_code : sandbox + auto-amélioration + danger_guard ──────────────────
try:
    from nokido_agent.app.forge_code import (
        ImprovementOrchestrator,  # noqa: F401
        ErrorMemory,  # noqa: F401
        DangerGuard,  # noqa: F401
        DangerLevel,
        DangerCheck,  # noqa: F401
        get_guard,
        danger_confirmation_message,  # noqa: F401
        should_auto_block,  # noqa: F401
        CodeSandbox,  # noqa: F401
        SandboxResult,  # noqa: F401
        get_sandbox,  # noqa: F401
        handle_code_command,  # noqa: F401
        is_dangerous_code,  # noqa: F401
    )

    HAS_DANGER_GUARD = True
    HAS_SANDBOX = True
except ImportError:
    HAS_DANGER_GUARD = HAS_SANDBOX = False

    class DangerLevel:
        """DangerLevel class."""

        pass  # stub minimal


# ── Silencer prints/warnings des imports optionnels (Windows-safe) ──────────
# NE PAS utiliser contextlib.redirect_stderr : ferme sys.stderr sur Windows
# (CPython/Windows : "ValueError: I/O operation on closed file / lost sys.stderr")
# → Sauvegarde/restauration MANUELLE de sys.stdout et sys.stderr
import io as _io, warnings as _warnings, sys as _sys


class _silent:
    """Supprime stdout + stderr + warnings — compatible Windows/Linux/Mac."""

    def __enter__(self) -> object:
        """Enter."""
        self._old_out = _sys.stdout
        self._old_err = _sys.stderr
        _buf = _io.StringIO()
        _sys.stdout = _buf
        _sys.stderr = _buf
        self._wctx = _warnings.catch_warnings()
        self._wctx.__enter__()
        _warnings.simplefilter("ignore")
        return self

    def __exit__(self, *a) -> None:
        # Restaurer stdout/stderr en premier — même si exception
        """Exit."""
        try:
            _sys.stdout = self._old_out
        except Exception:
            pass
        try:
            _sys.stderr = self._old_err
        except Exception:
            pass
        try:
            self._wctx.__exit__(*a)
        except Exception:
            pass


# ── Recherche Web (web.py v2 — Ollama natif, sans OpenAI) ───────────────────
try:
    with _silent():
        from nokido_agent.app.forge_web import WebSearchEngine, get_web_engine, web_search as _web_search_fn
    HAS_WEB_SEARCH = True
except ImportError:
    HAS_WEB_SEARCH = False
    """Web search fn."""

    def _web_search_fn(*a, **kw) -> list:
        """Web search fn."""
        return []

    """Get web engine."""

    def get_web_engine(*a, **kw) -> None:
        """Get web engine."""
        return None

    class WebSearchEngine:
        """Should search."""

        def should_search(self, *a, **kw) -> bool:
            """Should search."""
            return False

        """Search."""

        async def search(self, *a, **kw) -> list:
            """Search."""
            return []


# ── Routage intelligent multi-agents (routage.py) ────────────────────────────
try:
    with _silent():
        from nokido_agent.app.forge_agents import (
            SmartRouter,
            OllamaParallelRunner,  # noqa: F401
            PromptClassifier,  # noqa: F401
            AgentPlanner,  # noqa: F401
            PromptCategory,  # noqa: F401
            RouteResult,  # noqa: F401
            AgentContrib,  # noqa: F401
            AGENT_BY_KEY,
            init_router,  # noqa: F401
            get_router,
        )
    HAS_ROUTAGE = True
except ImportError:
    HAS_ROUTAGE = False
    AGENT_BY_KEY = {}

# ── Sandbox de code (codesandbox.py) ─────────────────────────────────────────
try:
    with _silent():
        HAS_SANDBOX = True  # déjà importé via forge_code
except ImportError:
    HAS_SANDBOX = False

# ── Moteur NLU predictif adaptatif (predictif.py) ────────────────────────────
try:
    with _silent():
        from nokido_agent.app.forge_nlu import (
            PredictiveRouter,  # noqa: F401
            IntentVote,  # noqa: F401
            load_router as _pred_load_router,  # noqa: F401
            get_router_if_ready as _pred_get_router,  # noqa: F401
            hybrid_classify,  # noqa: F401
        )
    HAS_PREDICTIF = True
except ImportError:
    HAS_PREDICTIF = False

# ── Service Registry (routage réseau modulaire) ─────────────────────────
HAS_SERVICES = False
try:
    from nokido_agent.app.forge_services import (
        init_registry,
        get_registry,
        ServiceType,  # noqa: F401
        ServiceStatus,  # noqa: F401
        get_llm_endpoint,  # noqa: F401
        get_rag_endpoint,  # noqa: F401
        get_sidecar_endpoint,  # noqa: F401
        get_ssh_endpoints,  # noqa: F401
        ServiceEndpoint,  # noqa: F401
        Protocol,  # noqa: F401
    )

    HAS_SERVICES = True
except ImportError:
    HAS_SERVICES = False
    """Get registry."""

    def get_registry() -> None:
        """Get registry."""
        return None

    """Init registry.

    Args:
        p: Description.
    """

    def init_registry(p: object) -> None:
        """Init registry."""
        return None


HAS_MEMORY = False
try:
    from nokido_agent.app.forge_memory import mem_monitor, mem_profiler, mem_optimizer

    HAS_MEMORY = True
except ImportError:
    mem_monitor = mem_profiler = mem_optimizer = None

# ── Arbre de competences hierarchique ────────────────────────────────────────
HAS_SKILLTREE = False
_skill_learner = None
try:
    from nokido_agent.app.forge_gui_debug import GuiDebugOverlay, gui_debug_log, patch_app_for_debug

    HAS_GUI_DEBUG = True
except Exception:
    HAS_GUI_DEBUG = False
    """Gui debug log."""

    def gui_debug_log(*a, **k) -> None:
        """Gui debug log."""
        pass

    """Patch app for debug."""

    def patch_app_for_debug(*a, **k) -> None:
        """Patch app for debug."""
        pass

    GuiDebugOverlay = None  # pas un widget — ne pas yield
try:
    from nokido_agent.app.skilltree import SkillLearner, SkillTree as SkillTreeWidget

    HAS_SKILLTREE = True
except Exception as _e_st:
    # Catch large : Textual lève parfois RuntimeError/AttributeError hors event loop
    import logging as _lg_st

    _lg_st.getLogger(__name__).warning(f"[boot] skilltree import échoué ({type(_e_st).__name__}) : {_e_st}")

# ── Backend ONNX + Sidecar ML (embeddings MiniLM + génération Phi-3.5 + tree-sitter)
try:
    from nokido_agent.app.forge_runtime import (
        init_onnx_backend,
        get_embedder,
        get_generator,
        get_brain,
        onnx_get_embeddings,
        onnx_call,
        onnx_stream,
        onnx_status,
        shutdown_onnx_backend,
        ts_audit,
        ts_surgery,
        ts_locate,
        HAS_TREE_SITTER,
        _TS_ERROR,
    )

    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False
    HAS_TREE_SITTER = False
    _TS_ERROR = ""
    """Init onnx backend."""

    def init_onnx_backend(**kw) -> dict:
        """Init onnx backend."""
        return {"embedder": False, "generator": False, "tree_sitter": False}

    """Get embedder."""

    def get_embedder() -> None:
        """Get embedder."""
        return None

    """Get generator."""

    def get_generator() -> None:
        """Get generator."""
        return None

    """Get brain."""

    def get_brain() -> None:
        """Get brain."""
        return None

    """Onnx get embeddings.

    Args:
        texts: Description.
    """

    async def onnx_get_embeddings(texts: object) -> None:
        """Onnx get embeddings."""
        return None

    """Onnx call.

    Args:
        messages: Description.
    """

    async def onnx_call(messages: list, **kw) -> None:
        """Onnx call."""
        raise RuntimeError("ONNX non disponible")

    """Onnx stream.

    Args:
        messages: Description.
        on_token: Description.
        on_done: Description.
    """

    async def onnx_stream(messages: list, on_token: object, on_done: object, **kw) -> None:
        """Onnx stream."""
        raise RuntimeError("ONNX non disponible")

    """Onnx status."""

    def onnx_status() -> str:
        """Onnx status."""
        return "❌ onnx_backend.py non trouvé"

    """Shutdown onnx backend."""

    def shutdown_onnx_backend() -> None:
        """Shutdown onnx backend."""
        pass

    """Ts audit.

    Args:
        code: Description.
    """

    def ts_audit(code: object) -> dict:
        """Ts audit."""
        return {"safe": True, "message": "sidecar absent", "violations": []}

    """Ts surgery.

    Args:
        source: Description.
        target_name: Description.
        new_code: Description.
    """

    def ts_surgery(source: object, target_name: object, new_code: object) -> dict:
        """Ts surgery."""
        return {"success": False, "message": "sidecar absent"}

    """Ts locate.

    Args:
        source: Description.
        target_name: Description.
    """

    def ts_locate(source: object, target_name: object) -> None:
        """Ts locate."""
        return None


# ── Découverte réseau (snif.py) ──────────────────────────────────────────────
try:
    with _silent():
        from nokido_agent.app.forge_network import NetworkDiscovery, Device as NetDevice  # noqa: F401
    HAS_SNIF = True
except (ImportError, Exception):
    HAS_SNIF = False

# ── IDS réseau (scapyshark.py) ────────────────────────────────────────────────
try:
    with _silent():
        from nokido_agent.app.forge_network import MiniIDSAgent  # noqa: F401
    HAS_IDS = True
except (ImportError, Exception):
    HAS_IDS = False

# ── Récupération config switches/routeurs (boitaswitch.py) ──────────────────
try:
    with _silent():
        from nokido_agent.app.forge_network import NetworkRecoveryAgent, SwitchResult  # noqa: F401
    HAS_SWITCH = True
except (ImportError, Exception):
    HAS_SWITCH = False

del _io, _warnings, _sys  # nettoyage imports silencing

# =============================================================================
# CONFIGURATION — stdlib pure, compatible Python 3.8→3.14+, zéro dépendance
# pydantic-settings est utilisé si disponible pour la validation étendue,
# sinon fallback vers un lecteur .env maison parfaitement fonctionnel.
# =============================================================================
# [→ forge_startup.py] _read_env_file

from nokido_agent.app.forge_startup import _read_env_file as _ref

_ref("Nokido.env")  # chargé avant tout le reste
del _ref

try:
    from pydantic_settings import BaseSettings as _BaseSettings  # type: ignore
    from pydantic import Field, field_validator, ConfigDict  # type: ignore

    HAS_PYDANTIC_SETTINGS = True
    # BaseSettings v2 lit déjà le .env via model_config
    _BaseClass = _BaseSettings
except ImportError:
    HAS_PYDANTIC_SETTINGS = False

    # ── Fallback : dataclass-like maison, zéro dépendance externe ──────────
    # Utilise uniquement os.environ (déjà chargé par _read_env_file ci-dessus)
    class _BaseClass:  # type: ignore
        """Remplacement minimal de BaseSettings — stdlib seulement."""

        pass

    # Stubs pour que le code Settings() compile sans pydantic
    class _FieldInfo:
        """FieldInfo class."""

        def __init__(self, default: object, alias: object = None, **_) -> None:
            """Init.

            Args:
                default: Description.
                alias: Description.
            """
            self.default = default
            self.alias = alias

    def Field(default: object = None, *, validation_alias=None, **_) -> object:  # type: ignore
        """Field.

        Args:
            default: Description.
        """
        return _FieldInfo(default, alias=validation_alias)

    def field_validator(*_, **__) -> object:  # type: ignore
        """Deco.

        Args:
            fn: Description.
        """
        """Field validator."""

        def _deco(fn: object) -> object:
            """Deco."""
            return fn

        return _deco

    class ConfigDict(dict):
        """ConfigDict class."""

        pass  # type: ignore


# Prefect (optionnel)
try:
    from prefect import flow, task
    from prefect.task_runners import ConcurrentTaskRunner
    from prefect.client.orchestration import get_client

    HAS_PREFECT = True
except ImportError:
    HAS_PREFECT = False

    # stubs
    def flow(*a, **kw) -> object:
        """Flow."""

        def dec(f: object) -> object:
            """Dec.

            Args:
                f: Description.
            """
            return f

        return dec

    def task(*a, **kw) -> object:
        """Task."""

        def dec(f: object) -> object:
            """Dec.

            Args:
                f: Description.
            """
            return f

        return dec

    class ConcurrentTaskRunner:
        """Init."""

        def __init__(self, **kw) -> None:
            """Initialise l'instance."""
            pass

    """Get client."""

    def get_client() -> None:
        """Get client."""
        return None


# Textual
try:
    from textual.app import App, ComposeResult
    from textual.containers import Vertical, Horizontal
    from textual.widgets import Header, Footer, Static, Input, Button, ListView, ListItem, Label, RichLog, ProgressBar
    from textual.widget import Widget
    from textual.reactive import reactive
    from textual.binding import Binding
    from textual.screen import ModalScreen
    from textual import events
    from rich.text import Text  # noqa: F401
    from rich.panel import Panel
    from rich.markup import escape
    from rich.table import Table  # noqa: F401

    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False

# FAISS/BM25 (optionnel)
try:
    import faiss  # noqa: F401

    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False

try:
    from rank_bm25 import BM25Okapi  # noqa: F401

    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False


# Répertoires (définis dans le bloc d'init ci-dessus, récupérés ici proprement)
# Noms dynamiques par session
_DEBUG_SESSION_ID = __import__("uuid").uuid4().hex[:8]
DEBUG_LOG_PATH = _LOGS_DIR / f"debug-{_DEBUG_SESSION_ID}.log"
DEBUG_ROUTE_PATH = _LOGS_DIR / f"debug-routing-{_DEBUG_SESSION_ID}.log"

# [→ forge_logging.py] debug_log


# File handles persistants pour debug_log (ouverts une seule fois)
_debug_main_handle = None
_debug_route_handle = None


def _debug_main_fh() -> object:
    """Debug main fh."""
    global _debug_main_handle
    if _debug_main_handle is None or _debug_main_handle.closed:
        _debug_main_handle = open(DEBUG_LOG_PATH, "a", encoding="utf-8", buffering=4096)
    return _debug_main_handle


def _debug_route_fh() -> object:
    """Debug route fh."""
    global _debug_route_handle
    if _debug_route_handle is None or _debug_route_handle.closed:
        _debug_route_handle = open(DEBUG_ROUTE_PATH, "a", encoding="utf-8", buffering=4096)
    return _debug_route_handle


# =============================================================================
# LOGGING — Non-bloquant via QueueHandler + JSONL
# =============================================================================
# Un fichier log par session : nokido_YYYYMMDD_HHMMSS.log  (texte lisible)
#                              nokido_YYYYMMDD_HHMMSS.jsonl (structuré, parseable)
#
# Architecture :
#   logger.info(msg)  →  QueueHandler (enfile, ne bloque JAMAIS)
#                              ↓
#                     QueueListener (thread daemon)
#                        ├─→ FileHandler  (.log texte)
#                        └─→ JSONLHandler (.jsonl structuré)
#
# L'event-loop Textual n'est plus bloqué par l'I/O fichier.

import datetime as _dt
import logging.handlers as _lh
import queue as _log_queue

_SESSION_TS = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
_SESSION_LOG = _LOGS_DIR / f"nokido_{_SESSION_TS}.log"
_SESSION_JSONL = _LOGS_DIR / f"nokido_{_SESSION_TS}.jsonl"


from nokido_agent.app.forge_core_models import (  # noqa — doit être avant L422
    _JSONLHandler,
    AgentType,
    TaskPriority,
    TTLCache,
    ErrorManager,
    SSHManager,
    SkillEntry,
    SupervisorAnalysis,
    ActionResult,
    RoutingPlan,
    OrchestratorState,
    OrchestratorManager,
    SessionContext,
    PrefectManager,
    ForgeSaveOrchestrator,
    VersionManager,
    IntentClassifier,
    OllamaMemoryManager,
)
from nokido_agent.app.forge_agentic_engine import (
    AgenticEngine,
    EvolutionOrchestrator,
    ENTROPY_THRESHOLDS,
)
from nokido_agent.app.forge_agents_reasoning import (
    SupervisorAgent,
    ActionAgent,
    RAGAgent,
    DialogueAgent,
    SupervisorAnalysis,
    RoutingPlan,
    ActionResult,
)
from nokido_agent.app.forge_ui_autocomplete import AutocompleteEngine
from nokido_agent.app.forge_code_surgery import (
    CodeSurgeon,
    SurgeryResult,
)
# [_JSONLHandler → forge_core_models.py]


# ── File d'attente partagée ───────────────────────────────────────────────────
_log_q = _log_queue.Queue(-1)

# ── Handler texte (lisible, comme avant) ─────────────────────────────────────
_text_handler = RotatingFileHandler(str(_SESSION_LOG), mode="w", encoding="utf-8", maxBytes=10485760, backupCount=5)
_text_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )
)

# ── Handler JSONL (structuré, parseable) ─────────────────────────────────────
_jsonl_handler = _JSONLHandler(_SESSION_JSONL)
_jsonl_handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d", datefmt="%H:%M:%S"))

# ── #4 roadmap hermes : RedactingFormatter — secrets/PII jamais écrits sur disque ──
# Enveloppe les formatters des handlers qui ÉCRIVENT (réutilise le redactor souverain
# forge_semantic_firewall.redact_for_log, pas de regex réinventé). Fail-soft : le
# logging ne doit jamais casser. cf tools/forge_log_redact.py.
try:
    import sys as _sys_r, os as _os_r
    _tools_r = _os_r.path.join(_os_r.path.dirname(_os_r.path.dirname(_os_r.path.abspath(__file__))), "tools")
    if _tools_r not in _sys_r.path:
        _sys_r.path.insert(0, _tools_r)
    from nokido_agent.tools import forge_log_redact as _flr
    for _h_r in (_text_handler, _jsonl_handler):
        _f_r = _h_r.formatter
        _h_r.setFormatter(_flr.RedactingFormatter(getattr(_f_r, "_fmt", None), getattr(_f_r, "datefmt", None)))
except Exception:
    pass

# ── QueueHandler (non-bloquant — enfile et retourne immédiatement) ───────────
_queue_handler = _lh.QueueHandler(_log_q)

# ── QueueListener (thread daemon — consomme la queue, écrit les deux fichiers)
_queue_listener = _lh.QueueListener(
    _log_q,
    _text_handler,
    _jsonl_handler,
    respect_handler_level=True,
)
if not os.environ.get("LAFORGE_ROBOT"):
    _queue_listener.start()

# ── Configuration du logger racine ───────────────────────────────────────────
logging.root.setLevel(logging.DEBUG)
logging.root.handlers.clear()
logging.root.addHandler(_queue_handler)

logger = logging.getLogger(__name__)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("asyncssh").setLevel(logging.WARNING)
logging.getLogger("pdfminer").setLevel(logging.WARNING)
logging.getLogger("pdfminer.psparser").setLevel(logging.ERROR)
logging.getLogger("pdfminer.pdfdocument").setLevel(logging.ERROR)
logging.getLogger("pdfminer.pdfpage").setLevel(logging.ERROR)
logging.getLogger("surya").setLevel(logging.WARNING)
logging.getLogger("marker").setLevel(logging.WARNING)
logger.info(f"[SESSION] log = {_SESSION_LOG}")
logger.info(f"[SESSION] jsonl = {_SESSION_JSONL}")

# Garder un symlink/copie "nokido_latest.log" pour accès rapide
try:
    _latest = _LOGS_DIR / "nokido_latest.log"
    if _latest.exists() or _latest.is_symlink():
        _latest.unlink()
    _latest.symlink_to(_SESSION_LOG.name)
except Exception:
    pass  # symlink non supporté sur certains Windows

# Purge automatique : garder les 20 dernières sessions (.log + .jsonl)
try:
    for _ext in ("nokido_????????_??????.log", "nokido_????????_??????.jsonl"):
        _old_logs = sorted(_LOGS_DIR.glob(_ext), key=lambda p: p.stat().st_mtime)
        for _old in _old_logs[:-20]:
            _old.unlink(missing_ok=True)
except Exception:
    pass

# =============================================================================
# CONFIGURATION AVEC PYDANTIC V2
# =============================================================================
# ---------------------------------------------------------------------------
# TABLE de correspondance env_var → (attr, type, default)
# ---------------------------------------------------------------------------
_SETTINGS_FIELDS = [
    # (attr_name,            env_key,                    type_,  default)
    ("ssh_host", "SSH_HOST", str, ""),  # wizard si vide
    ("ssh_port", "SSH_PORT", int, 22),
    ("ssh_user", "SSH_USER", str, ""),  # wizard si vide
    ("private_key_path", "PRIVATE_KEY_PATH", Path, ""),  # wizard si vide
    ("ollama_model_default", "OLLAMA_MODEL_DEFAULT", str, ""),  # vide = l'orchestrateur décide
    ("ollama_url", "OLLAMA_URL", str, "http://localhost:11434/api/chat"),
    ("ollama_tags_url", "OLLAMA_TAGS_URL", str, "http://localhost:11434/api/tags"),
    ("ollama_embeddings_url", "OLLAMA_EMBEDDINGS_URL", str, "http://localhost:11434/api/embed"),
    ("ollama_embeddings_model", "OLLAMA_EMBEDDINGS_MODEL", str, "bge-m3"),
    ("verbose", "VERBOSE", bool, False),
    ("max_concurrent_tasks", "MAX_CONCURRENT_OLLAMA", int, 4),
    ("chunk_overlap_words", "CHUNK_OVERLAP_WORDS", int, 30),
    ("embed_batch_size", "EMBED_BATCH_SIZE", int, 16),
    ("use_rag", "USE_RAG", bool, True),
    ("rag_docs_topk", "RAG_DOCS_TOPK", int, 5),
    ("rag_dir", "RAG_DIR", Path, ""),  # vide = _DATA_DIR / "rag_files"
    ("max_command_retries", "MAX_COMMAND_RETRIES", int, 2),
    ("command_retry_delay", "COMMAND_RETRY_DELAY", int, 2),
    ("auto_switch_agent", "AUTO_SWITCH_AGENT", bool, True),
    ("slack_webhook_url", "SLACK_WEBHOOK_URL", str, None),
    # @loop automerge : fusionner automatiquement si le cycle améliore le code
    # Seuils configurables — False = toujours demander à l'utilisateur
    ("loop_automerge", "LOOP_AUTOMERGE", bool, False),
    ("loop_automerge_min_delta", "LOOP_AUTOMERGE_MIN_DELTA", int, 1),  # erreurs éliminées minimum
    ("loop_automerge_min_quality", "LOOP_AUTOMERGE_MIN_QUALITY", int, 60),  # score qualité minimum
]

_REQUIRED = object()  # sentinel : champ obligatoire


def _cast(value: str, type_: object) -> Any:
    """Convertit une string env vers le type Python cible."""
    if type_ is bool:
        return value.lower() in ("1", "true", "yes", "oui", "on")
    if type_ is int:
        return int(value)
    if type_ is Path:
        return Path(value)
    return value  # str


# Settings → forge_settings.py (source unique)
from nokido_agent.app.forge_settings import Settings, create_settings  # noqa
# forge_core_* importés plus haut


# =============================================================================
# ASSISTANT DE CONFIGURATION SSH — lancé si variables SSH absentes
# =============================================================================

# [EXTRAIT → forge_ssh.py] _ssh_setup_wizard


def create_settings() -> Settings:  # noqa: F811
    """Create settings."""
    try:
        # ── Si SSH non configuré, Settings() accepte ssh_host="" ────────────
        # La TUI affichera SSHWizardScreen au démarrage pour compléter.
        # Le wizard console (_ssh_setup_wizard) reste disponible en fallback
        # si lancement sans Textual (--no-window, mode script, etc.)
        _ssh_vars = ("SSH_HOST", "SSH_USER", "PRIVATE_KEY_PATH")
        from nokido_agent.app.forge_settings import _valeur_de_reglage as _val_ssh

        _missing_ssh = [k for k in _ssh_vars if not (_val_ssh(k) or "").strip()]
        if _missing_ssh and not __import__("sys").stdin.isatty():
            # Contexte non-interactif sans Textual → wizard console
            from nokido_agent.app.forge_ssh import handle_ssh_setup_wizard as _wiz

            _wiz()

        settings = Settings()
        errors = settings.validate_all()
        if errors:
            logger.warning("Problèmes de configuration détectés:")
            for error in errors:
                logger.warning(f"  - {error}")
        return settings
    except Exception as e:
        print(f"\n❌ Erreur de configuration : {e}")
        print("Vérifiez Nokido.env (SSH_HOST, SSH_USER, PRIVATE_KEY_PATH)")
        sys.exit(1)


settings = create_settings()

# =============================================================================
# GESTIONNAIRE D'ERREURS AVEC RETRY
# =============================================================================
# [ErrorManager → forge_core_models.py]

# =============================================================================
# CONSTANTES ET ÉNUMÉRATIONS
# =============================================================================
# [AgentType → forge_core_models.py]

AGENT_META = {
    AgentType.CHAT: {"icon": "💬", "color": "#58a6ff", "label": "Chat"},
    AgentType.ACTION: {"icon": "⚡", "color": "#f0883e", "label": "Action"},
    AgentType.RAG: {"icon": "🗄", "color": "#3fb950", "label": "RAG"},
}

# [TaskPriority → forge_core_models.py]

failure_stats = {"total_commands": 0, "failed_commands": 0}

# =============================================================================
# CACHE (TTL)
# =============================================================================
# [TTLCache → forge_core_models.py]

diag_cache = TTLCache(ttl=30, maxsize=50)
command_exists_cache = TTLCache(ttl=300, maxsize=200)

# =============================================================================
# GESTIONNAIRE SSH (AVEC ERROR MANAGER)
# =============================================================================
# [SSHManager → forge_core_models.py]

ssh_manager = SSHManager()


async def run_ssh(command: str, sudo: bool = False, timeout: int = 30) -> Tuple[str, str, int]:
    """Run ssh.

    Args:
        command: Description.
        sudo: Description.
        timeout: Description.
    """
    return await ssh_manager.run(command, sudo, timeout)


# =============================================================================
# GESTIONNAIRE PTY (TERMINAL INTERACTIF)
# =============================================================================
def _strip_ssh_output(raw: str) -> str:
    """Nettoie stdout SSH : séquences ANSI, \r, espaces parasites."""
    import re as _re

    clean = _re.sub(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", raw)
    result = clean.replace("\r", "").strip().split("\n")[0].strip()
    logger.debug(f"[_strip_ssh_output] {raw!r} → {result!r}")
    return result


if HAS_TEXTUAL:
    import pyte

    class PTYTerminal(Widget):
        """Terminal interactif basé sur pyte et asyncssh."""

        # Touches réservées à l'App — PTY ne les consomme pas
        _APP_RESERVED: frozenset = frozenset(
            {
                "ctrl+l",
                "ctrl+c",
                "ctrl+v",
                "ctrl+z",
                "ctrl+shift+c",
                "ctrl+shift+v",
                "f1",
                "f2",
                "f3",
                "f4",
                "f5",
                "ctrl+q",
                "ctrl+p",
                "ctrl+t",  # focus terminal — géré par l'App binding, pas le PTY
                "ctrl+e",  # focus input — idem
            }
        )

        # PTYTerminal doit être focusable pour recevoir les keystrokes
        can_focus = True

        def __init__(self) -> None:
            """Init."""
            super().__init__()
            self._cols = 80
            self._rows = 24
            # HistoryScreen garde les lignes qui scrollent hors écran
            try:
                self._screen = pyte.HistoryScreen(self._cols, self._rows, history=500)
            except AttributeError:
                self._screen = pyte.Screen(self._cols, self._rows)
            self._stream = pyte.Stream(self._screen)
            self._input_queue = asyncio.Queue()
            self._connection = None
            self._channel = None
            self._connected = False
            self._read_task = None
            self._write_task = None
            self._log = None
            self._cursor_timer = None
            self._cursor_visible = True  # toggle pour clignotement

        # [→ forge_handlers.py] compose

        def compose(self) -> ComposeResult:
            """Compose."""
            yield RichLog(id="pty-log", highlight=False, markup=True, wrap=False, classes="pty-log")

        async def on_mount(self) -> None:
            """On mount."""
            self._log = self.query_one("#pty-log", RichLog)
            self._sync_size()
            # Timer de refresh pour le curseur (visible même quand idle)
            self._cursor_timer = self.set_interval(0.6, self._cursor_refresh)

        def _cursor_refresh(self) -> None:
            """Toggle clignotement curseur + refresh."""
            if self._connected:
                self._cursor_visible = not self._cursor_visible
                self._refresh()

        def _sync_size(self) -> None:
            """Sync size."""
            try:
                w, h = self.size.width, self.size.height
                nc = max(40, w)  # width complete sans offset
                nr = max(8, h - 1)
                if nc != self._cols or nr != self._rows:
                    self._cols = nc
                    self._rows = nr
                    self._screen.resize(nr, nc)
                    if self._connected and self._channel:
                        try:
                            self._channel.change_terminal_size(nc, nr)
                        except Exception:
                            pass
            except Exception:
                pass

            # ── forge_context : injection finale (toutes vars disponibles) ──
            try:
                from nokido_agent.app import forge_context as _fc_boot

                _fc_boot.version_manager = version_manager
                _fc_boot.settings = settings
                _fc_boot.ssh_manager = ssh_manager
                _fc_boot.prefect_manager = prefect_manager
                # Orchestrateur — forcer init et injection
                try:
                    from nokido_agent.app.forge_orchestrator import get_orchestrator as _get_orc

                    _fc_boot.orchestrator = _get_orc()
                    logger.info(f"[boot] orchestrator: {type(_fc_boot.orchestrator).__name__}")
                except Exception as _oe:
                    logger.warning(f"[boot] orchestrator init: {_oe}")
                # Gemini bridge — lazy init
                try:
                    from nokido_agent.app.forge_gemini_bridge import GeminiBridge

                    _fc_boot.gemini_bridge = GeminiBridge()
                    logger.info("[boot] GeminiBridge initialisé")
                    # llama-cpp-python engine
                    try:
                        from nokido_agent.app.forge_llamacpp import get_llamacpp_bridge as _glc

                        _lc = _glc()
                        _fc_boot.llm_engine = _lc
                        if _lc.enabled:
                            import threading as _th

                            _th.Thread(target=_lc.warmup, daemon=True, name="LlamaCpp-Warmup").start()
                            logger.info(f"[boot] llama-cpp-python: {_lc.model}")
                    except Exception as _lce:
                        logger.debug(f"[boot] llamacpp skip: {_lce}")
                except Exception as _ge:
                    logger.warning(f"[boot] GeminiBridge non disponible: {_ge}")
            except Exception:
                pass

        async def on_resize(self, _: object) -> None:
            """On resize.

            Args:
                _: Description.
            """
            self._sync_size()
            self._refresh_log()

        def watch_size(self, size: int) -> None:
            """Watcher réactif — déclenché sur TOUT changement de taille (splitter, fenêtre)."""
            self._sync_size()
            self._refresh_log()

        def _refresh_log(self) -> None:
            """Force le RichLog à recalculer sa largeur d'affichage."""
            try:
                log = self.query_one("#pty-log", RichLog)
                log.refresh(layout=True)
                log._max_width = max(40, self.size.width)
            except Exception:
                pass

        async def connect(self) -> bool:
            """Connect."""
            if self._connected:
                return True
            try:
                self._connection = await asyncssh.connect(
                    settings.ssh_host,
                    port=settings.ssh_port,
                    username=settings.ssh_user,
                    client_keys=[str(settings.private_key_path)],
                    known_hosts=None,
                )
                self._channel = await self._connection.create_process(
                    term_type="xterm-256color", term_size=(self._cols, self._rows), request_pty=True
                )
                self._connected = True
                self._sync_size()  # adapter au layout courant dès la connexion
                self._read_task = asyncio.create_task(self._read_loop())
                self._write_task = asyncio.create_task(self._write_loop())
                return True
            except Exception as e:
                if self._log:
                    self._log.write(f"[PTY] Connexion échouée: {e}")
                return False

        async def _read_loop(self) -> None:
            """Read loop."""
            try:
                while self._connected:
                    try:
                        data = await asyncio.wait_for(self._channel.stdout.read(4096), timeout=0.05)
                        if data:
                            self._stream.feed(data)
                            self._refresh()
                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break
                    except Exception as e:
                        self._connected = False
                        if self._log:
                            self._log.write(f"[PTY déconnecté: {e}]")
                        break
            except asyncio.CancelledError:
                pass

        async def _write_loop(self) -> None:
            """Write loop."""
            try:
                while self._connected:
                    try:
                        data = await asyncio.wait_for(self._input_queue.get(), timeout=1.0)
                        if self._channel and not self._channel.stdin.is_closing():
                            self._channel.stdin.write(data)
                            await self._channel.stdin.drain()
                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        break
                    except Exception as e:
                        logger.error(f"PTY write: {e}")
                        break
            except asyncio.CancelledError:
                pass

        def _refresh(self) -> None:
            """Refresh."""
            if not self._log:
                return
            try:
                from rich.text import Text

                self._log.clear()
                w = self._cols
                cursor_y = self._screen.cursor.y
                cursor_x = self._screen.cursor.x

                # Historique scroll-back (lignes qui ont scrollé hors écran)
                if hasattr(self._screen, "history") and hasattr(self._screen.history, "top"):
                    for hist_line in self._screen.history.top:
                        # hist_line est un dict {col: pyte.Char} — reconstruire le texte
                        if isinstance(hist_line, dict):
                            chars = []
                            for col in range(w):
                                c = hist_line.get(col)
                                chars.append(c.data if c else " ")
                            self._log.write("".join(chars))
                        else:
                            self._log.write(str(hist_line)[:w])

                # Écran courant pyte avec curseur
                for row_idx, line in enumerate(self._screen.display):
                    if len(line) < w:
                        padded = line + " " * (w - len(line))
                    elif len(line) > w:
                        padded = line[:w]
                    else:
                        padded = line
                    # Curseur bloc clignotant
                    if row_idx == cursor_y and 0 <= cursor_x < len(padded) and self._cursor_visible:
                        t = Text(padded)
                        t.stylize("reverse bold", cursor_x, cursor_x + 1)
                        self._log.write(t)
                    else:
                        self._log.write(padded)
            except Exception:
                pass

        KEY_MAP = {
            "enter": "\r",
            "backspace": "\x7f",
            "tab": "\t",
            "escape": "\x1b",
            "space": " ",
            "up": "\x1b[A",
            "down": "\x1b[B",
            "right": "\x1b[C",
            "left": "\x1b[D",
            "home": "\x1b[H",
            "end": "\x1b[F",
            "delete": "\x1b[3~",
            "insert": "\x1b[2~",
            "pageup": "\x1b[5~",
            "pagedown": "\x1b[6~",
            "f1": "\x1bOP",
            "f2": "\x1bOQ",
            "f3": "\x1bOR",
            "f4": "\x1bOS",
        }

        def on_click(self, event: object) -> None:
            """Clic PTY → PTYTerminal prend le focus (pour recevoir les keystrokes)."""
            try:
                event.stop()
                self.focus()  # focus sur le Widget, pas le RichLog interne
            except Exception:
                pass

        def on_mouse_down(self, event: object) -> None:
            """Mousedown PTY — capture pour éviter crash Textual."""
            try:
                event.stop()
            except Exception:
                pass

        async def on_key(self, event: events.Key) -> None:
            """On key.

            Args:
                event: Description.
            """
            if not self._connected:
                return
            # Laisser l'App gérer ses bindings prioritaires (clipboard, focus, agents)
            if event.key in self._APP_RESERVED:
                return
            key = event.key
            if key in self.KEY_MAP:
                await self._input_queue.put(self.KEY_MAP[key])
                event.stop()
                return
            if key.startswith("ctrl+"):
                c = key[5:]
                if len(c) == 1 and c.isalpha():
                    await self._input_queue.put(chr(ord(c.lower()) - 96))
                    event.stop()
                    return
            char = getattr(event, "character", None)
            if char and len(char) == 1 and char.isprintable():
                await self._input_queue.put(char)
                event.stop()
                return
            if len(key) == 1 and key.isprintable():
                await self._input_queue.put(key)
                event.stop()

        async def inject(self, cmd: str, echo: bool = True) -> None:
            """
            Envoie une commande au shell SSH.
            echo=True : affiche immédiatement la commande dans le RichLog
            avant de recevoir la réponse du serveur (pour les commandes
            interactives comme top, vim, htop qui ne font pas d'écho local).


            Args:
                cmd (str): Cmd.
                echo (bool (optional)): Echo.
            """
            if not self._connected:
                if self._log:
                    self._log.write(f"[non connecté] {cmd}")
                return
            # Écho local immédiat — évite le blanc avant réponse serveur
            if echo and self._log and cmd.strip():
                try:
                    self._log.write(f"$ {cmd}")
                except Exception:
                    pass
            await self._input_queue.put(cmd + "\r")

        async def disconnect(self) -> None:
            """Disconnect."""
            self._connected = False
            for task in (self._read_task, self._write_task):
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(*(t for t in (self._read_task, self._write_task) if t), return_exceptions=True)
            if self._channel:
                try:
                    self._channel.stdin.write_eof()
                except Exception:
                    pass
            if self._connection:
                self._connection.close()
                await self._connection.wait_closed()


# =============================================================================
# MOTEUR RAG
# =============================================================================
# ── RAGEngine — importé depuis forge_rag_engine (refacto v0.13.4) ──────────────
# La classe était dupliquée inline — désormais source unique dans forge_rag_engine.py
# _save_embeddings() de forge_rag_engine écrit dans RAG/embeddings.db (SQLite WAL)
# plus embeddings.arrow (PyArrow) via le double-write patché.
from nokido_agent.app.forge_rag_engine import RAGEngine  # noqa: E402

rag_engine: "RAGEngine | None" = None  # singleton global — initialisé dans on_mount

# [SkillEntry → forge_core_models.py]


# [AgenticEngine → forge_core_agents.py]


# Instance globale (initialisée après TUI)
agentic_engine: Optional[AgenticEngine] = None


# =============================================================================
# EVOLUTION ORCHESTRATOR — Cycle auto-apprentissage RAG
# =============================================================================
# Inspiré de RagIntelligent.py — adapté à l'architecture La Forge (Ollama local,
# sans OpenAI, avec le VersionManager intégré et le sandbox forge_code).
#
# Cycle complet :
#   @disco → collecte de nouvelle connaissance
#   @audit → génère un patch de code + tests unitaires via LLM
#   sandbox → valide le patch en isolation
#   régression → vérifie que l'ancien code n'est pas cassé
#   benchmark → s'assure que la qualité RAG ne régressse pas (-5% tolérance)
#   merge → fusionne dans workspace, ré-ingère le code dans le RAG
# =============================================================================

# [EvolutionOrchestrator → forge_core_agents.py]


# =============================================================================
# CLASSES D'ORCHESTRATION MULTI-AGENTS
# =============================================================================
# [SupervisorAnalysis → forge_core_models.py]

# [ActionResult → forge_core_models.py]

# [RoutingPlan → forge_core_models.py]

# [OrchestratorState → forge_core_models.py]

# [SupervisorAgent → forge_core_agents.py]

# [ActionAgent → forge_core_agents.py]

# [RAGAgent → forge_core_agents.py]

# [DialogueAgent → forge_core_agents.py]

# [OrchestratorManager → forge_core_models.py]

# Singleton global — créé une seule fois, jamais recréé dans _dispatch_ai
orchestrator_state = OrchestratorState()
_global_orchestrator: Optional[OrchestratorManager] = None


def get_orchestrator() -> OrchestratorManager:  # noqa: F811
    """Retourne le singleton OrchestratorManager, le crée si nécessaire."""
    global _global_orchestrator
    if _global_orchestrator is None:
        _global_orchestrator = OrchestratorManager()
        try:
            from nokido_agent.app import forge_context as _fc_orc

            _fc_orc.orchestrator = _global_orchestrator
        except Exception:
            pass
    return _global_orchestrator


# =============================================================================
# CONTEXTE DE SESSION
# =============================================================================
# [SessionContext → forge_core_models.py]

# =============================================================================
# GESTIONNAIRE PREFECT (WORKFLOWS)
# =============================================================================
# [PrefectManager → forge_core_models.py]

prefect_manager = PrefectManager()  # settings injecté dans on_mount via update()


# =============================================================================
# AUTOCOMPLÉTION
# =============================================================================
# [AutocompleteEngine → forge_core_agents.py]


# =============================================================================
# GESTIONNAIRE DE VERSIONS (PROTECTION DU SOURCE)
# =============================================================================
# =============================================================================
# GESTIONNAIRE DE VERSIONS — TRONC PRINCIPAL + BRANCHES LOOP
# =============================================================================


# =============================================================================
# CODE SURGEON — Patch chirurgical via AST
# =============================================================================
# Workflow :
#   Parse → Locate (ancre) → Transform (NodeTransformer) → Codegen (unparse)
#
# Avantages vs remplacement de fichier entier :
#   - Résilient au déplacement de classes/fonctions dans le fichier
#   - Patch minimal = diff minimal = rollback précis
#   - Validation AST AVANT écriture (rejet immédiat si syntaxe invalide)
#   - Chaque nœud SkillTree lié à un node_name unique dans l'AST
# =============================================================================


# [SurgeryResult → forge_core_agents.py]


# [_NodeLocator → forge_core_agents.py]


# [_NodeReplacer → forge_core_agents.py]


# [CodeSurgeon → forge_core_agents.py]


# =============================================================================
# FORGE SAVE ORCHESTRATOR — Double Porte atomique
# =============================================================================
#
# Flux de sécurité :
#   Snapshot → Staging → Sandbox → @audit → Commit/Rollback
#
# Répertoires (tous relatifs au dossier Nokido.py) :
#   staging/   ← code expérimental en cours de test
#   backups/   ← checkpoints horodatés (rotation GFS max 10)
#   workspace/ ← production stable (géré par VersionManager)
#
# Ne jamais écrire directement dans workspace/ depuis AgenticEngine.
# Toujours passer par : staging → validate → commit_to_prod.
# =============================================================================

# [ForgeSaveOrchestrator → forge_core_models.py]


# Instance globale — initialisée avec VersionManager dans main()
save_orchestrator: Optional[ForgeSaveOrchestrator] = None

# [VersionManager → forge_core_models.py]

version_manager = VersionManager()
save_orchestrator = ForgeSaveOrchestrator()

# =============================================================================
# CONSTANTES PARTAGÉES — UN SEUL ENDROIT, PAS DE DUPLICATION
# =============================================================================
SHELL_COMMANDS: frozenset = frozenset(
    {
        "ls",
        "cd",
        "cat",
        "grep",
        "ps",
        "kill",
        "systemctl",
        "service",
        "apt",
        "apt-get",
        "yum",
        "dnf",
        "docker",
        "kubectl",
        "ssh",
        "scp",
        "rsync",
        "chmod",
        "chown",
        "mv",
        "cp",
        "rm",
        "mkdir",
        "rmdir",
        "touch",
        "echo",
        "export",
        "alias",
        "source",
        "sudo",
        "su",
        "crontab",
        "journalctl",
        "tail",
        "head",
        "less",
        "more",
        "nano",
        "vim",
        "vi",
        "ifconfig",
        "ip",
        "netstat",
        "ss",
        "ping",
        "traceroute",
        "nmap",
        "curl",
        "wget",
        "git",
        "make",
        "python",
        "python3",
        "pip",
        "pip3",
        "reboot",
        "shutdown",
        "halt",
        "poweroff",
        "init",
        "find",
        "awk",
        "sed",
        "tar",
        "zip",
        "unzip",
        "mount",
        "umount",
        "df",
        "du",
        "top",
        "htop",
        "free",
        "uname",
        "whoami",
        "which",
        "env",
        "printenv",
        "hostname",
    }
)
SHELL_SPECIAL_CHARS: frozenset = frozenset(
    # NB : "?", "[", "]", "(", ")", "{", "}" retirés — apparaissent dans les phrases
    # françaises normales et causaient des faux-positifs ACTION massifs.
    {"|", ">", "<", "&", ";", "$", "`", "\\", "*"}
)
RAG_KEYWORDS: List[str] = [
    "document",
    "doc",
    "manuel",
    "guide",
    "tutorial",
    "howto",
    "documentation",
    "exemple",
    "example",
]


def looks_like_shell_command(text: str) -> bool:
    """Looks like shell command.

    Args:
        text: Description.
    """
    text = text.strip()
    if not text:
        return False
    first = text.split()[0].lower()
    if first in SHELL_COMMANDS:
        return True
    return any(c in text for c in SHELL_SPECIAL_CHARS)


# =============================================================================
# CLASSIFICATION D'INTENTION — NLU français naturel v3
# =============================================================================

# Patterns NLU ACTION — formulations naturelles françaises
# Ordre : du plus spécifique au plus général
_NLU_ACTION_PATTERNS: List[Tuple[re.Pattern, Optional[int]]] = [
    # "passe la commande top", "lance la commande ps aux" → groupe 3 = commande
    (re.compile(r"\b(passe|lance|exécute?|run|fais?|fait|joue)\s+(la\s+)?commande\s+(.+)", re.I), 3),
    # "passe X dans/sur le terminal/shell" — injection terminale
    (
        re.compile(
            r"\b(passe|lance|mets?|tape|injecte)\s+(.+?)\s+(dans|sur|via)\s+(le\s+)?(terminal|shell|bash|ssh)\b", re.I
        ),
        None,
    ),
    # "dans/sur/via le terminal/shell" seul → ACTION
    (re.compile(r"\b(dans|sur|via)\s+(le\s+)?(terminal|shell|bash|ssh)\b", re.I), None),
    # "montre/affiche le top/ps/df/logs/…" — outils système précis
    (
        re.compile(
            r"\b(montre|affiche|donne|montre.moi|donne.moi)\s+(moi\s+)?(le\s+|les\s+|la\s+)?"
            r"(top|ps|df|free|uptime|journaux?|logs?|proc|service|port|netstat|mémoire|cpu|disque|ram|swap)\b",
            re.I,
        ),
        4,
    ),
    # "interroge/vérifie/monitore le serveur"
    (
        re.compile(
            r"\b(interroge|connecte.toi|check|vérifie|inspecte|sonde|monitore)\s+(mon\s+|le\s+|ma\s+)?(serveur|server|machine|host|vm|poste|hôte)\b",
            re.I,
        ),
        None,
    ),
    # "donne moi la conf/config/status/contenu de X"
    (
        re.compile(
            r"\b(donne.moi|montre.moi|récupère|obtiens?|lis|lit|affiche)\s+(la\s+|le\s+)?(conf|config|configuration|settings?|status|état|contenu|fichier)\s+(de\s+|d[e\']?\s*)?\S+",
            re.I,
        ),
        None,
    ),
    # "lit/lis/cat le fichier X", "affiche le fichier X"
    (
        re.compile(r"\b(lit|lis|cat|affiche|montre)\s+(le\s+|la\s+|les\s+|ce\s+)?(fichier|file|contenu)\s+\S+", re.I),
        None,
    ),
    # "peux-tu redémarrer/arrêter/…" — verbe action après demande polie
    (
        re.compile(
            r"(?:\btu\s+(?:peux|dois|devrais)|\bpeux.tu\b|\bpouvez.vous\b|\bpeux tu\b)\s*"
            r"(redémarre[rz]?|arrête[rz]?|stoppe[rz]?|restart(?:er)?|stop(?:per)?|start(?:er)?"
            r"|reload(?:er)?|enable[rz]?|disable[rz]?|démarre[rz]?)\s+"
            r"(?!pas\b|plus\b|jamais\b|tout\b|seul\b)",
            re.I | re.MULTILINE,
        ),
        None,
    ),
    # Verbe action en tout début de phrase : "redémarre nginx", "arrête apache"
    (
        re.compile(
            r"^\s*(redémarre|arrête|stoppe|restart|stop|start|reload|enable|disable|démarre)\s+"
            r"(?!pas\b|plus\b|jamais\b|tout\b|seul\b)"
            r"(le\s+|la\s+|les\s+)?(\w+)",
            re.I | re.MULTILINE,
        ),
        None,
    ),
    # "installe/désinstalle/update/upgrade X"
    (re.compile(r"^\s*(installe|désinstalle|update|upgrade|purge|remove|supprime|déploie)\s+\w+", re.I), None),
    # "scan le réseau/les ports"
    (
        re.compile(
            r"\b(scan|scanne|analyse)\s+(le\s+|les\s+|mon\s+|la\s+)?(réseau|network|ports?|services?|hôtes?|machines?)\b",
            re.I,
        ),
        None,
    ),
    # "backup/sauvegarde X"
    (re.compile(r"\b(backup|sauvegarde[rz]?|archive[rz]?)\s+(le\s+|la\s+|les\s+)?\S+", re.I), None),
    # "optimise/refactorise/corrige/debug X"
    (
        re.compile(
            r"^\s*(optimise[rz]?|refactorise[rz]?|corrige[rz]?|répare[rz]?|améliore[rz]?|fixe[rz]?|debug(?:gue)?[rz]?)\s+\S+",
            re.I,
        ),
        None,
    ),
    # "liste/lister les fichiers/processus/services/ports dans/de X"
    (
        re.compile(
            r"^\s*(liste|lister|montre|affiche|donne)\s+(les?|des?)\s+"
            r"(fichiers?|dossiers?|processus|services?|ports?|connexions?|interfaces?|disques?|partitions?|logs?)"
            r"(\s+(dans|de|sur|sous|en|du|des?)\s+\S+)?",
            re.I,
        ),
        None,
    ),
    # "quel est l'état/l'espace/la charge/la mémoire/le statut de X"
    (
        re.compile(
            r"\b(quel\s+(est|sont)|quelle\s+est)\s+(l[ae\'\u2019\u2018\x27]\s*|le\s+|la\s+)?"
            r"(état|espace|charge|mémoire|ram|cpu|disque|swap|statut|status|version|uptime|température)\b",
            re.I,
        ),
        None,
    ),
]

# Pattern d'extraction de commande depuis "passe la commande X"
_CMD_EXTRACT = re.compile(r"\b(?:passe|lance|exécute?|run|fais?|fait)\s+(?:la\s+)?commande\s+(.+)", re.I)

# Patterns NLU RAG — recherche documentaire
_NLU_RAG_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(qu['\s]?est.ce que|c['\s]?est quoi|explique.?moi|définition de|parle.moi de|kesako)\b", re.I),
    re.compile(r"\b(comment (faire|configurer|installer|utiliser|setup))\b", re.I),
    re.compile(r"\b(documentation|doc|manuel|guide|tuto|tutoriel)\s+(de|sur|pour|d[eu])\b", re.I),
    re.compile(r"\b(cherche|recherche|trouve.moi)\s+(des?\s+)?(doc|info|article|tuto)\b", re.I),
    re.compile(r"\b(c'est quoi|c est quoi|qu'est ce|cest quoi)\b", re.I),
    # Recherche dans le code source
    re.compile(
        r"\b(cherche|trouve|recherche|localise|o[u\u00f9]\s+est)\s+(dans\s+(le\s+)?code|la\s+fonction|la\s+classe|le\s+fichier)\b",
        re.I,
    ),
    re.compile(r"\b(dans\s+(le\s+)?code|dans\s+(le\s+)?source|dans\s+(le\s+)?projet)\b", re.I),
]


# [IntentClassifier → forge_core_models.py]


intent_classifier = IntentClassifier()


def looks_like_shell_command(text: str) -> bool:  # noqa: F811
    """Looks like shell command.

    Args:
        text: Description.
    """
    text = text.strip()
    if not text:
        return False
    first = text.split()[0].lower()
    if first in SHELL_COMMANDS:
        return True
    if any(c in text for c in SHELL_SPECIAL_CHARS):
        return True
    for pat, _ in _NLU_ACTION_PATTERNS:
        if pat.search(text):
            return True
    return False


# =============================================================================
# OLLAMA STREAMING
# =============================================================================
# ── Sémaphore global Ollama — limite les appels concurrents ─────────────────
_ollama_semaphore: Optional[asyncio.Semaphore] = None


def _get_ollama_semaphore() -> asyncio.Semaphore:
    """Retourne (ou crée) le sémaphore de concurrence Ollama."""
    global _ollama_semaphore
    if _ollama_semaphore is None:
        _ollama_semaphore = asyncio.Semaphore(settings.max_concurrent_tasks)
    return _ollama_semaphore


# [EXTRAIT → forge_ollama.py] ollama_call — import via forge_ollama


async def ollama_parallel(calls: List[Dict]) -> List[str]:
    """
    Lance N appels Ollama en parallèle via asyncio.gather + sémaphore.
    Chaque call = {"model": str, "messages": list, "system"?: str, "max_tokens"?: int}
    Retourne les réponses dans le même ordre.


    Args:
        calls (List[Dict]): Calls.

    Returns:
        List[str]: Résultat.
    """
    from nokido_agent.app.forge_llm import ollama_call as _oc  # tombeau

    tasks = [
        _oc(
            model=c["model"],
            messages=c["messages"],
            system=c.get("system"),
            max_tokens=c.get("max_tokens", 512),
        )
        for c in calls
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r if isinstance(r, str) else f"[Erreur: {r}]" for r in results]


# =============================================================================
# GESTIONNAIRE MEMOIRE OLLAMA
# =============================================================================

# [OllamaMemoryManager → forge_core_models.py]


_mem_mgr: "OllamaMemoryManager" = None  # type: ignore


def get_mem_mgr() -> "OllamaMemoryManager":
    """Get mem mgr."""
    return _mem_mgr


# [EXTRAIT → forge_ollama.py] ollama_stream

# =============================================================================
# WIDGETS TEXTUAL
# =============================================================================
if HAS_TEXTUAL:

    class AutocompleteInput(Input):
        """
        Champ de saisie chat avec autocomplétion intelligente :
        - Texte commence par "@" → ↑/↓ cycle les @ commandes
        - Texte normal           → ↑/↓ navigue l'historique des messages chat
        - Tab                    → complète la @ commande unique (si 1 match)
        - Shift+Enter            → saut de ligne (multiligne jusqu'à 6 lignes)
        - Enter                  → envoie le message
        - Esc                    → réinitialise la navigation

        Le terminal PTY reçoit ses suggestions via push_terminal_suggestion()
        appelé dans _dispatch_ai — totalement séparé du chat input.
        """

        _engine = AutocompleteEngine()
        _sugg_idx: int = -1

        def on_key(self, event: events.Key) -> None:
            """On key.

            Args:
                event: Description.
            """
            key = event.key
            current = self.value.rstrip()

            if key == "up":
                if current.startswith("@"):
                    # Mode @ : cycle les commandes
                    sugg = self._engine.suggest_cmd(current)
                    if not sugg:
                        return
                    self._sugg_idx = max(0, (self._sugg_idx - 1) if self._sugg_idx >= 0 else len(sugg) - 1)
                    self._sugg_idx = min(max(self._sugg_idx, 0), len(sugg) - 1)
                    self.value = sugg[self._sugg_idx] + " "
                else:
                    # Mode historique chat
                    prev = self._engine.history_up(current)
                    if prev:
                        self.value = prev
                self.cursor_position = len(self.value)
                event.stop()
                event.prevent_default()

            elif key == "down":
                if current.startswith("@"):
                    sugg = self._engine.suggest_cmd(current)
                    if not sugg:
                        return
                    self._sugg_idx = min(len(sugg) - 1, self._sugg_idx + 1)
                    self._sugg_idx = min(max(self._sugg_idx, 0), len(sugg) - 1)
                    self.value = sugg[self._sugg_idx] + " "
                else:
                    self.value = self._engine.history_down()
                self.cursor_position = len(self.value)
                event.stop()
                event.prevent_default()

            elif key == "tab":
                if current.startswith("@"):
                    sugg = self._engine.suggest_cmd(current)
                    if len(sugg) == 1:
                        self.value = sugg[0] + " "
                        self.cursor_position = len(self.value)
                        event.stop()
                        event.prevent_default()

            elif key == "escape":
                self._sugg_idx = -1
                self._engine._hist_idx = -1
                # Ne stop pas — Esc peut fermer une modale

            elif key == "shift+enter":
                # Shift+Enter = saut de ligne (multiligne)
                cur = self.value
                pos = self.cursor_position
                self.value = cur[:pos] + "\n" + cur[pos:]
                self.cursor_position = pos + 1
                event.stop()
                event.prevent_default()

            else:
                # Toute autre frappe réinitialise l'index de navigation
                self._sugg_idx = -1

        def on_input_changed(self, event: object) -> None:
            """Suggestion en temps réel sur chaque frappe — y compris la dernière."""
            val = self.value
            if not val.startswith("@"):
                self.placeholder = "Message… (@help | numéro suggestion)"
                return
            sugg = self._engine.suggest_cmd(val)
            if len(sugg) == 1 and sugg[0] != val.rstrip():
                try:
                    self.placeholder = f"{sugg[0]}  (Tab pour compléter)"
                except Exception:
                    pass
            elif len(sugg) > 1:
                self.placeholder = "  |  ".join(sugg[:3])
            else:
                self.placeholder = "Message… (@help | numéro suggestion)"

        def on_mouse_right_click(self, event: object) -> None:
            """Clic droit = coller depuis clipboard."""
            try:
                import pyperclip as _pc

                text = _pc.paste()
                if text:
                    pos = self.cursor_position
                    self.value = self.value[:pos] + text + self.value[pos:]
                    self.cursor_position = pos + len(text)
                    event.stop()
            except Exception:
                pass

    class AgentSelector(Static):
        """AgentSelector class."""

        current = reactive(AgentType.CHAT)

        def render(self) -> Panel:
            """Render."""
            lines = []
            for agent, meta in AGENT_META.items():
                selected = agent == self.current
                style = f"bold {meta['color']}" if selected else "dim"
                prefix = "▶ " if selected else "  "
                lines.append(f"[{style}]{prefix}{meta['icon']} {meta['label']}[/]")
            return Panel("\n".join(lines), title="[bold]Agents[/]", border_style="#30363d")

        def set_agent(self, agent: AgentType) -> None:
            """Set agent.

            Args:
                agent: Description.
            """
            self.current = agent
            self.refresh()

    class MetricsPanel(Static):
        """MetricsPanel class."""

        rag_time = reactive(0.0)
        rag_tok = reactive(0)
        llm_time = reactive(0.0)
        llm_tok = reactive(0)
        req_count = reactive(0)
        last_agent = reactive("—")
        last_model = reactive("—")

        def render(self) -> Panel:
            """Render."""
            rag_line = f"RAG:  {self.rag_time:.2f}s  ({self.rag_tok} tok)"
            llm_line = f"LLM:  {self.llm_time:.2f}s  ({self.llm_tok} tok)"
            req_line = f"reqs: {self.req_count}"
            try:
                agent = AgentType(self.last_agent)
                meta = AGENT_META.get(agent, AGENT_META[AgentType.CHAT])
                agent_line = f"{meta['icon']} {meta['label']}  {self.last_model[:12]}"
            except ValueError:
                agent_line = f"?  {self.last_model[:12]}"
            content = f"{rag_line}\n{llm_line}\n{req_line}\n[dim]{agent_line}[/]"
            return Panel(content, title="[bold #58a6ff]📊 Métriques[/]", border_style="#30363d")

        def update(
            self,
            rd: object = 0.0,
            rt: object = 0,
            ld: object = 0.0,
            lt: object = 0,
            agent: str = AgentType.CHAT,
            model: str = "",
        ) -> None:
            """Update.

            Args:
                rd: Description.
                rt: Description.
                ld: Description.
                lt: Description.
                agent: Description.
                model: Description.
            """
            self.rag_time = rd
            self.rag_tok = rt
            self.llm_time = ld
            self.llm_tok = lt
            self.req_count += 1
            self.last_agent = agent.value
            self.last_model = model
            self.refresh()

    class SkillNode(Static):
        """
        Nœud de compétence dans l'arbre des habiletés.
        Change de couleur et d'icône selon le statut.
        """

        status = reactive("waiting")

        ICONS = {"waiting": "⚪", "searching": "🔍", "learning": "🧪", "mastered": "✅", "verified": "🏆"}
        COLORS = {
            "waiting": "#484f58",
            "searching": "#388bfd",
            "learning": "#d29922",
            "mastered": "#3fb950",
            "verified": "#a371f7",
        }

        def __init__(self, label: str, **kwargs):
            """Init.

            Args:
                label: Description.
            """
            super().__init__(**kwargs)
            self._label = label  # nom stocké explicitement (pas dans .renderable)

        def render(self) -> object:
            """Render."""
            from rich.text import Text

            icon = self.ICONS.get(self.status, "⚪")
            color = self.COLORS.get(self.status, "#484f58")
            return Text.from_markup(f"[{color}]{icon} {self._label[:16]}[/]")

    class EntropyGauge(Static):
        """
        Jauge d'entropie RAG — sidebar.
        Pure Static SANS compose() pour éviter le double widget (bug Textual).
        """

        DEFAULT_CSS = """
        EntropyGauge {
            height: 4; border: solid #21262d;
            background: #0d1117; padding: 0 1;
        }
        """
        _BAR_W = 18

        def __init__(self, **kwargs) -> None:
            """Init."""
            _bar0 = "\u2591" * 18
            _txt = (
                "\U0001f9e0 Sant\u00e9 RAG  [green]Saine[/]\n"
                + "[dim]"
                + _bar0
                + "[/]  [bold #3fb950]0%[/]\n"
                + "[dim]vert<20% \u00b7 orange<50% \u00b7 rouge>80%[/]"
            )
            # Static attend le contenu en 1er arg positionnel, pas en kwarg
            super().__init__(_txt, **kwargs)
            self._entropy = 0.0

        def refresh_entropy(self, level: float, color: str) -> None:
            """Refresh entropy.

            Args:
                level: Description.
                color: Description.
            """
            self._entropy = level
            pct = int(level * 100)
            filled = int(round(level * self._BAR_W))
            empty = self._BAR_W - filled
            bar = "[" + color + "]" + "\u2588" * filled + "[/]" + "[dim]" + "\u2591" * empty + "[/]"
            if level <= ENTROPY_THRESHOLDS["green"]:
                label = "[green]Saine[/]"
            elif level <= ENTROPY_THRESHOLDS["orange"]:
                label = "[yellow]Maintenance[/]"
            else:
                label = "[bold red]Critique \U0001f6a8[/]"
            self.update(
                "\U0001f9e0 Sant\u00e9 RAG  "
                + label
                + "\n"
                + bar
                + "  [bold "
                + color
                + "]"
                + str(pct)
                + "%[/]\n"
                + "[dim]vert<20% \u00b7 orange<50% \u00b7 rouge>80%[/]"
            )

    class SkillTreePanel(Static):
        """Panneau lateral : arbre de competences hierarchique."""

        DEFAULT_CSS = """
        SkillTreePanel {
            height: auto; min-height: 3; max-height: 20;
            border: solid #21262d; background: #0d1117;
            padding: 0 1; overflow-y: auto;
        }
        """

        def __init__(self, *args, **kwargs) -> None:
            """Init."""
            super().__init__(*args, **kwargs)
            self._skill_nodes: Dict[str, Any] = {}
            self._tree_widget = None

        def compose(self) -> ComposeResult:
            """Compose."""
            yield Static("[bold #a371f7]-- Competences[/]", id="skill-title")
            # _skill_learner est None ici (compose avant on_mount)
            # bootstrap_tree() est appelé depuis on_mount après init
            if HAS_SKILLTREE and _skill_learner:
                self._tree_widget = SkillTreeWidget(learner=_skill_learner, id="skill-tree-hier")
                yield self._tree_widget
            else:
                yield Static("[dim]  Chargement...[/]", id="skill-placeholder")

        def bootstrap_tree(self) -> None:
            """Appele depuis on_mount() apres init _skill_learner.
            Remplace le placeholder par le vrai SkillTree widget.
            """
            if not HAS_SKILLTREE or not _skill_learner:
                try:
                    self.query_one("#skill-placeholder").update("[dim]  skilltree.py absent[/]")
                except Exception:
                    pass
                return
            if self._tree_widget is not None:
                return  # déjà initialisé
            try:
                self.query_one("#skill-placeholder").remove()
            except Exception:
                pass
            try:
                self._tree_widget = SkillTreeWidget(learner=_skill_learner, id="skill-tree-hier")
                self.mount(self._tree_widget)
                gui_debug_log("SkillTree", "bootstrap OK", level="ok")
            except Exception as _bte:
                gui_debug_log("SkillTree", f"bootstrap erreur : {_bte}", level="error")

        def add_or_update(self, name: str, status: str) -> None:
            """Add or update.

            Args:
                name: Description.
                status: Description.
            """
            if self._tree_widget and hasattr(self._tree_widget, "add_or_update_skill"):
                self._tree_widget.add_or_update_skill(name, status)
            # Fallback nodes
            elif name in self._skill_nodes:
                self._skill_nodes[name].status = status
            else:
                import re as _re_sk

                _sk_id = _re_sk.sub(r"[^a-zA-Z0-9_-]", "_", name)
                node = SkillNode(name, id=f"sk_{_sk_id}")
                node.status = status
                self._skill_nodes[name] = node
                try:
                    self.mount(node)
                except Exception:
                    pass

        def clear_skills(self) -> None:
            """Clear skills."""
            if self._tree_widget and hasattr(self._tree_widget, "refresh_all"):
                self._tree_widget.refresh_all()
            for node in list(self._skill_nodes.values()):
                try:
                    node.remove()
                except Exception:
                    pass
            self._skill_nodes.clear()

        def render_summary(self, skills: List[Dict]) -> None:
            """Render summary.

            Args:
                skills: Description.
            """
            for s in skills:
                self.add_or_update(s["name"], s["status"])

    class RAGInfoPanel(Static):
        """RAGInfoPanel class."""

        chunks = reactive(0)
        faiss_ok = reactive(False)
        bm25_ok = reactive(False)
        via_hub = reactive("")  # etat du RAG du hub ; vide = RAG local

        def render(self) -> Panel:
            """Render."""
            if self.via_hub:
                # Jamais « 0 chunks » pour un RAG qui vit dans le hub : ce serait lire
                # « base vide » la ou l'on ne sait simplement pas compter d'ici.
                dot = "[yellow]●[/]" if self.via_hub.startswith("refuse") else "[green]●[/]"
                return Panel(f"{dot} [bold]RAG du hub[/] — {self.via_hub}",
                             title="[bold #3fb950]🗄 RAG[/]", border_style="#30363d")
            status = "[green]●[/]" if self.chunks > 0 else "[red]●[/]"
            faiss = "[green]F[/]" if self.faiss_ok else "[dim]F[/]"
            bm25 = "[green]B[/]" if self.bm25_ok else "[dim]B[/]"
            return Panel(
                f"{status} [bold]{self.chunks}[/] chunks  {faiss}/{bm25}",
                title="[bold #3fb950]🗄 RAG[/]",
                border_style="#30363d",
            )

        def sync(self) -> None:
            """Sync."""
            if rag_engine:
                self.chunks = len(rag_engine.chunks)
                self.faiss_ok = rag_engine.faiss_index is not None
                self.bm25_ok = rag_engine.bm25_index is not None
                self.via_hub = rag_engine.etat() if getattr(rag_engine, "via_hub", False) else ""
            self.refresh()

    # =========================================================================
    # ÉCRAN WIZARD SSH — lancé au démarrage si SSH non configuré
    # =========================================================================
    class SSHWizardScreen(ModalScreen):
        """
        Interface de configuration SSH, cohérente avec le style La Forge.
        Lancée depuis on_mount() si SSH_HOST / SSH_USER / PRIVATE_KEY_PATH
        sont absents. Propose session temporaire ou enregistrement Nokido.env.
        """

        CSS = """
        SSHWizardScreen {
            align: center middle;
            background: rgba(0,0,0,0.85);
        }
        #wizard-box {
            width: 64;
            background: #161b22;
            border: solid #58a6ff;
            padding: 1 2;
        }
        #wizard-title {
            color: #58a6ff;
            text-style: bold;
            text-align: center;
            height: 1;
            margin-bottom: 1;
        }
        #wizard-subtitle {
            color: #8b949e;
            text-align: center;
            height: 1;
            margin-bottom: 1;
        }
        .wiz-label {
            color: #8b949e;
            height: 1;
            margin-top: 1;
        }
        .wiz-input {
            background: #0d1117;
            color: #c9d1d9;
            border: solid #30363d;
            height: 1;
        }
        .wiz-input:focus { border: solid #58a6ff; }
        #wizard-error {
            color: #ff7b72;
            height: 1;
            margin-top: 1;
        }
        #wizard-sep {
            color: #30363d;
            margin-top: 1;
            height: 1;
        }
        #wizard-save-label {
            color: #c9d1d9;
            height: 1;
            margin-top: 1;
        }
        #btn-session {
            background: #0d2137;
            color: #58a6ff;
            border: none;
            width: 1fr;
            margin-top: 1;
        }
        #btn-session:hover { background: #1a3a5c; color: #ffffff; }
        #btn-save {
            background: #0d2010;
            color: #56d364;
            border: none;
            width: 1fr;
            margin-top: 0;
        }
        #btn-save:hover { background: #1a3d18; color: #ffffff; }
        #btn-cancel {
            background: #1a1a1a;
            color: #8b949e;
            border: none;
            width: 1fr;
            margin-top: 0;
        }
        #btn-cancel:hover { background: #30363d; color: #c9d1d9; }
        """

        def __init__(self, on_done: Callable):
            """Init.

            Args:
                on_done: Description.
            """
            super().__init__()
            self._on_done = on_done  # callback(saved: bool) appelé après config

        def compose(self) -> ComposeResult:
            """Compose."""
            with Vertical(id="wizard-box"):
                yield Static("⚒  La Forge — Connexion SSH", id="wizard-title")
                yield Static("Aucune cible SSH configurée dans Nokido.env", id="wizard-subtitle")
                yield Static("─" * 58, id="wizard-sep")

                yield Static("Adresse IP ou hostname  (SSH_HOST)", classes="wiz-label")
                yield Input(placeholder="192.168.1.x  ou  mon-serveur.local", id="wiz-host", classes="wiz-input")

                with Horizontal():
                    with Vertical():
                        yield Static("Utilisateur  (SSH_USER)", classes="wiz-label")
                        yield Input(placeholder="root  /  admin  /  pi", id="wiz-user", classes="wiz-input")
                    with Vertical():
                        yield Static("Port  (SSH_PORT)", classes="wiz-label")
                        yield Input(placeholder="22", value="22", id="wiz-port", classes="wiz-input")

                yield Static("Chemin clé privée  (PRIVATE_KEY_PATH)", classes="wiz-label")
                yield Input(placeholder=r"C:\Users\…\id_rsa   ou   ~/.ssh/id_rsa", id="wiz-key", classes="wiz-input")

                yield Static("", id="wizard-error")
                yield Static("─" * 58, id="wizard-sep2", classes="wiz-label")
                yield Static(
                    "[dim]Session[/] = actif jusqu'à la fermeture  ·  [dim]Enregistrer[/] = écrit dans Nokido.env",
                    id="wizard-save-label",
                )

                with Horizontal():
                    yield Button("🔌  Session uniquement", id="btn-session")
                with Horizontal():
                    yield Button("💾  Enregistrer dans Nokido.env", id="btn-save")
                with Horizontal():
                    yield Button("✕  Annuler", id="btn-cancel")

        def _get_values(self) -> object:
            """Get values."""
            host = self.query_one("#wiz-host", Input).value.strip()
            user = self.query_one("#wiz-user", Input).value.strip()
            key = self.query_one("#wiz-key", Input).value.strip()
            port_raw = self.query_one("#wiz-port", Input).value.strip()
            try:
                port = int(port_raw) if port_raw else 22
            except ValueError:
                port = 22
            return host, user, port, key

        def _show_error(self, msg: str) -> None:
            """Show error.

            Args:
                msg: Description.
            """
            try:
                self.query_one("#wizard-error", Static).update(f"[red]⚠ {msg}[/]")
            except Exception:
                pass

        def _apply(self, host: str, user: str, port: int, key: str) -> bool:
            """Valide et injecte dans os.environ + settings."""
            if not host:
                self._show_error("SSH_HOST obligatoire")
                return False
            if not user:
                self._show_error("SSH_USER obligatoire")
                return False
            if not key:
                self._show_error("PRIVATE_KEY_PATH obligatoire")
                return False
            if not Path(key).exists():
                self._show_error(f"Fichier introuvable : {key}")
                return False

            # Injecter dans os.environ et settings
            os.environ["SSH_HOST"] = host
            os.environ["SSH_USER"] = user
            os.environ["SSH_PORT"] = str(port)
            os.environ["PRIVATE_KEY_PATH"] = key
            settings.ssh_host = host
            settings.ssh_user = user
            settings.ssh_port = port
            settings.private_key_path = Path(key)
            return True

        def _write_env(self, host: str, user: str, port: int, key: str) -> None:
            """Enregistre les acces SSH au COFFRE (DPAPI machine), jamais en clair dans Nokido.env.

            Owner 2026-09-25 : pas d'acces en dur dans une version distribuee. Un coffre indisponible
            est DIT : l'acces reste valable pour la session, rien n'est ecrit en clair."""
            try:
                from nokido_agent.app.forge_secrets import set_secret

                echecs = [k for k, v in (("SSH_HOST", host), ("SSH_PORT", str(port)), ("SSH_USER", user),
                                         ("PRIVATE_KEY_PATH", key)) if not set_secret(k, v)]
            except Exception as e:  # noqa: BLE001 - un coffre absent se DIT, jamais un repli en clair
                echecs = [f"coffre indisponible ({type(e).__name__})"]
            if echecs:
                self._show_error(f"Coffre : non enregistré ({', '.join(echecs)}) — accès valable pour cette session")
                return False
            return True

        def on_button_pressed(self, event: Button.Pressed) -> None:
            """On button pressed.

            Args:
                event: Description.
            """
            bid = event.button.id

            if bid == "btn-cancel":
                self._on_done(False)
                self.dismiss()
                return

            host, user, port, key = self._get_values()

            if bid == "btn-session":
                if self._apply(host, user, port, key):
                    self._on_done(True)
                    self.dismiss()

            elif bid == "btn-save":
                if self._apply(host, user, port, key):
                    saved = self._write_env(host, user, port, key)
                    if saved:
                        self._on_done(True)
                        self.dismiss()
                    # si erreur écriture, _show_error déjà appelé, on reste ouvert

        def on_key(self, event: events.Key) -> None:
            """On key.

            Args:
                event: Description.
            """
            if event.key == "escape":
                self._on_done(False)
                self.dismiss()

    class ConfirmScreen(ModalScreen):
        """ConfirmScreen class."""

        def __init__(self, message: str, callback: Callable):
            """Init.

            Args:
                message: Description.
                callback: Description.
            """
            super().__init__()
            self.message = message
            self.callback = callback

        def compose(self) -> ComposeResult:
            """Compose."""
            with Vertical(id="confirm-box"):
                yield Static(self.message, id="confirm-message")
                yield Static("Appuyez sur [bold]y[/] pour confirmer, [bold]n[/] pour annuler")

        def on_key(self, event: events.Key) -> None:
            """On key.

            Args:
                event: Description.
            """
            if event.key.lower() == "y":
                self.callback(True)
                self.dismiss()
            elif event.key.lower() == "n":
                self.callback(False)
                self.dismiss()

    class ModelScreen(ModalScreen):
        """ModelScreen class."""

        CSS = """
        ModelScreen { align: center middle; background: rgba(0,0,0,0.75); }
        #model-box { width: 64; max-height: 30; background: #0d1117;
                     border: solid #388bfd; padding: 1 2; overflow-y: auto; }
        #model-title { color: #58a6ff; text-style: bold; margin-bottom: 1; }
        #model-hint { color: #8b949e; margin-bottom: 1; }
        .model-item {
            color: #e6edf3;
            background: #161b22;
            height: 1;
            padding: 0 1;
            margin: 0;
            width: 100%;
        }
        .model-item:hover { background: #21262d; color: #ffffff; }
        .model-item.-selected { color: #79c0ff; background: #1f3a5f; text-style: bold; }
        .model-item.-close { color: #8b949e; margin-top: 1; }
        .model-item.-close:hover { color: #e6edf3; background: #21262d; }
        """

        def __init__(self, models: List[str], current: str, callback: Callable):
            """Init.

            Args:
                models: Description.
                current: Description.
                callback: Description.
            """
            super().__init__()
            self.models = models
            self.current = current
            self.callback = callback

        def compose(self) -> ComposeResult:
            """Compose."""
            with Vertical(id="model-box"):
                yield Static("🤖 Choisissez un modèle", id="model-title")
                yield Static("Cliquez · Échap pour annuler", id="model-hint")
                for i, m in enumerate(self.models):
                    parts = m.split(":")
                    tag = f" [{parts[1]}]" if len(parts) > 1 else ""
                    is_cur = m == self.current
                    marker = "▶ " if is_cur else "  "
                    classes = "model-item -selected" if is_cur else "model-item"
                    yield Static(f"{marker}{parts[0]}{tag}", id=f"m{i}", classes=classes)
                yield Static("✕ Fermer", id="model-close", classes="model-item -close")

        def on_click(self, event: object) -> None:
            """On click.

            Args:
                event: Description.
            """
            node = event.widget
            nid = getattr(node, "id", "")
            if nid == "model-close":
                self.dismiss()
                return
            for i, m in enumerate(self.models):
                if nid == f"m{i}":
                    self.callback(m)
                    self.dismiss()
                    return

        def on_key(self, event: events.Key) -> None:
            """On key.

            Args:
                event: Description.
            """
            if event.key == "escape":
                self.dismiss()

    class NotificationScreen(ModalScreen):
        """NotificationScreen class."""

        CSS = """
        NotificationScreen { align: center middle; background: rgba(0,0,0,0.7); }
        #notification-box { width: 54; background: #161b22; border: solid #58a6ff; padding: 1 2; }
        #notification-message { margin-bottom: 1; color: #c9d1d9; }
        """

        def __init__(self, message: str):
            """Init.

            Args:
                message: Description.
            """
            super().__init__()
            self.message = message

        def compose(self) -> ComposeResult:
            """Compose."""
            with Vertical(id="notification-box"):
                yield Static(self.message, id="notification-message")
                yield Button("OK", id="notification-ok", variant="primary")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            """On button pressed.

            Args:
                event: Description.
            """
            if event.button.id == "notification-ok":
                self.dismiss()

        def on_key(self, event: events.Key) -> None:
            """On key.

            Args:
                event: Description.
            """
            if event.key == "escape":
                self.dismiss()

    # =========================================================================
    # PANNEAU RÔLES ACTIFS (bandeau gauche — s'allume en live)
    # =========================================================================
    class RoleLightPanel(Static):
        """
        Affiche les 12 rôles ops comme des LEDs.
        Appelé par l'orchestrateur pour allumer/éteindre chaque rôle
        en fonction du flux de traitement en cours.
        """

        ROLES_DISPLAY = [
            ("🔍", "analyste", "Analyste", "#58a6ff"),
            ("🐛", "debugger", "Debugger", "#f0883e"),
            ("📋", "planner", "Planner", "#58a6ff"),
            ("🗺", "discovery", "Discovery", "#3fb950"),
            ("⚙", "devops", "DevOps", "#f0883e"),
            ("🌐", "network", "Network", "#79c0ff"),
            ("🔐", "security", "Security", "#ff7b72"),
            ("📊", "log_analysis", "Log Analysis", "#ffa657"),
            ("🗄", "rag", "RAG", "#56d364"),
            ("⚡", "action_exec", "Action/Exec", "#f0883e"),
            ("🧠", "memory", "Memory", "#d2a8ff"),
            ("📈", "monitoring", "Monitoring", "#3fb950"),
        ]

        def __init__(self) -> None:
            """Init."""
            super().__init__()
            self._active: set = set()
            self._rag_active: bool = False

        def render(self) -> Panel:
            """Render."""
            lines = []
            for icon, key, label, color in self.ROLES_DISPLAY:
                active = key in self._active or (key == "rag" and self._rag_active)
                padded_label = f"{label:<14}"
                if active:
                    lines.append(f"[bold {color}]{icon} {padded_label}[/] ◀")
                else:
                    lines.append(f"[dim]{icon} {padded_label}[/]")
            return Panel(
                "\n".join(lines),
                title="[bold #8b949e]Rôles[/]",
                border_style="#21262d",
                padding=(0, 1),
            )

        def activate(self, *roles: str) -> None:
            """Activate."""
            for r in roles:
                self._active.add(r)
            self.refresh()

        def deactivate(self, *roles: str) -> None:
            """Deactivate."""
            for r in roles:
                self._active.discard(r)
            self.refresh()

        def set_rag(self, active: bool) -> None:
            """Set rag.

            Args:
                active: Description.
            """
            self._rag_active = active
            self.refresh()

        def reset(self) -> None:
            """Reset."""
            self._active.clear()
            self._rag_active = False
            self.refresh()

    # =========================================================================
    # APPLICATION PRINCIPALE AVEC ORCHESTRATION

    # =========================================================================
    class VSplitter(Widget):
        """Séparateur vertical draggable entre le chat et le terminal.
        Glisse avec la souris pour ajuster la largeur de chaque panneau.
        """

        DEFAULT_CSS = """
        VSplitter {
            width: 1; background: #21262d;
        }
        VSplitter:hover { background: #388bfd40; }
        """
        _dragging: bool = False
        _drag_start_x: int = 0
        _chat_start_w: int = 0
        _term_start_w: int = 0

        def on_mouse_down(self, event: object) -> None:
            """On mouse down.

            Args:
                event: Description.
            """
            self._dragging = True
            self._drag_start_x = event.screen_x
            try:
                chat_p = self.app.query_one("#chat-panel")
                term_p = self.app.query_one("#terminal-panel")
                self._chat_start_w = chat_p.size.width
                self._term_start_w = term_p.size.width
            except Exception:
                pass
            self.capture_mouse()

        def on_mouse_move(self, event: object) -> None:
            """On mouse move.

            Args:
                event: Description.
            """
            if not self._dragging:
                return
            delta = event.screen_x - self._drag_start_x
            new_chat = max(20, self._chat_start_w + delta)
            new_term = max(15, self._term_start_w - delta)
            try:
                self.app.query_one("#chat-panel").styles.width = new_chat
                self.app.query_one("#terminal-panel").styles.width = new_term
            except Exception:
                pass

        def on_mouse_up(self, event: object) -> None:
            """On mouse up.

            Args:
                event: Description.
            """
            self._dragging = False
            self.release_mouse()

        def render(self) -> object:
            """Pas de texte visible — le séparateur est purement visuel."""
            from rich.text import Text

            return Text("")

    # =========================================================================
    class DevOpsApp(App):
        """DevOpsApp class."""

        CSS_PATH = "Nokido.tcss"

        # ── Titre fenêtre Windows ── version centralisée dans forge_version ──
        # forge_version.full_label() = "v0.13.3 [main] (stable)" ou "v0.13.3 [dev] (alpha)"
        try:
            from nokido_agent.app.forge_version import full_label as _fl

            TITLE = f"⚒ La Forge {_fl()}"
        except Exception:
            TITLE = f"⚒ La Forge v{__version__}"
        SUB_TITLE = ""  # mis à jour dynamiquement dans on_mount via full_label(vm)

        BINDINGS = [
            Binding("ctrl+t", "focus_term", "Terminal", show=True),
            Binding("ctrl+b", "toggle_sidebar", "Sidebar", show=False),
            # Alternatives F2/F3/F4/F6 (mesure 2026-09-25, Textual 8.2.5, octets reels) : un
            # terminal classique -- dont le xterm.js du bridge :7440 -- envoie « 1 » pour Ctrl+1,
            # NUL (ctrl+@) pour Ctrl+2, ESC pour Ctrl+3, \x01 (ctrl+a) pour Ctrl+Maj+A : ces
            # raccourcis n'arrivaient JAMAIS. Les combinaisons d'origine restent (une console
            # native pourrait les transmettre, non mesure). NR test_tui_raccourcis_atteignables_nr.
            Binding("ctrl+shift+a,f6", "copy_all_log", "Tout copier", show=False),
            Binding("ctrl+e", "focus_input", "Input", show=True),
            Binding("ctrl+1,f2", "agent_chat", "Chat", show=False),
            Binding("ctrl+2,f3", "agent_action", "Action", show=False),
            Binding("ctrl+3,f4", "agent_rag", "RAG", show=False),
            # ── Presse-papier ── priority=True surclasse le quit Ctrl+C de Textual
            Binding("ctrl+c", "copy_last_reply", "📋 Copier", show=True, priority=True),
            Binding("ctrl+l", "copy_full_log", "📜 Log", show=True, priority=True),
            Binding("ctrl+d", "toggle_debug", "🐛 Debug", show=False),
        ]

        def __init__(
            self,
            model_chat: str,
            model_action: str,
            model_rag: str,
            session_name: str,
            scorer: object = None,  # ModelScorer | None
            arch: object = None,  # ArchitectureProfile | None
        ):
            """Init.

            Args:
                model_chat: Description.
                model_action: Description.
                model_rag: Description.
                session_name: Description.
                scorer: Description.
                arch: Description.
            """
            super().__init__()
            self.model_chat = model_chat
            self.model_action = model_action
            self.model_rag = model_rag
            self.session_name = session_name
            # Scoring & architecture cible
            self.scorer = scorer
            self.arch = arch
            # Danger guard (protection commandes dangereuses)
            self.guard = get_guard() if HAS_DANGER_GUARD else None
            # UI widgets
            self.context: Optional[SessionContext] = None
            self.terminal = PTYTerminal()
            self.metrics = MetricsPanel()
            self.rag_info = RAGInfoPanel()
            self.agent_selector = AgentSelector()
            self.current_agent = AgentType.CHAT
            self.ai_busy = False
            self.ai_task: Optional[asyncio.Task] = None
            self.bashrc_buffer: List[str] = []
            self.autocomplete = AutocompleteEngine()
            self.last_audit_suggestions = []
            self._rag_pending_confirm: Dict[str, str] = {}  # confirmation purge RAG
            self._last_input: str = ""  # anti-debounce
            self._last_input_ts: float = 0.0
            self.role_panel = RoleLightPanel()
            self.skill_panel = SkillTreePanel()
            self._collab_mode = "autonome"  # mode orchestrateur par défaut
            self._sudo_unlocked = False  # sudo verrouillé par défaut (sécurité)
            self._ssh_connected = False  # terminal SSH actif
            self._last_ai_reply: str = ""
            self._pending_hostname: str = ""  # hostname reçu avant mount
            self._chat_log_buffer: list = []  # buffer Ctrl+L
            # SmartRouter — initialisé dans main(), récupéré ici
            self._smart_router: Optional["SmartRouter"] = get_router() if HAS_ROUTAGE else None
            self._update_sidebar_title()

        def _clipboard_status(self, msg: str, duration: float = 2.0) -> None:
            """Affiche un message flash dans #ai-status."""
            try:
                self.query_one("#ai-status", Static).update(msg)
                self.set_timer(duration, lambda: self.query_one("#ai-status", Static).update(""))
            except Exception:
                pass

        def action_copy_last_reply(self) -> None:
            """Ctrl+C — copie la dernière réponse IA dans le presse-papier."""
            reply = getattr(self, "_last_ai_reply", "").strip()
            if not reply:
                self._clipboard_status("[dim]Rien à copier[/]")
                return
            try:
                import pyperclip as _pc

                _pc.copy(reply)
                preview = reply[:40].replace("\n", " ")
                self._clipboard_status(f"[green]📋 Copié : {preview}…[/]")
            except ImportError:
                self._clipboard_status("[yellow]⚠ pip install pyperclip[/]", 4.0)
            except Exception as e:
                self._clipboard_status(f"[red]Erreur clipboard : {e}[/]")

        def _setup_chat_buffer(self) -> object:
            """Monkey-patch RichLog.write pour accumuler le texte brut dans _chat_log_buffer.
            Évite export_text() qui freeze l'UI sur les gros logs (Textual ≥ 0.49).


            Returns:
                object: Résultat.
            """
            import re as _re_strip

            _ansi = _re_strip.compile(r"\x1b\[[0-9;]*m|\[/?[a-z_]+[^\]]*\]", _re_strip.I)
            try:
                _log = self._chat_log()
                _orig = _log.write
                _buf = self._chat_log_buffer

                def _patched_write(msg: str, *a, **kw) -> object:
                    """Patched write.

                    Args:
                        msg: Description.
                    """
                    try:
                        _buf.append(_ansi.sub("", str(msg)))
                        if len(_buf) > 2000:  # garder 2000 dernières lignes max
                            del _buf[:500]
                    except Exception:
                        pass
                    return _orig(msg, *a, **kw)

                _log.write = _patched_write  # type: ignore
            except Exception as _e:
                logger.debug(f"_setup_chat_buffer: {_e}")

        def action_copy_full_log(self) -> None:
            """Ctrl+L — copie le log chat via _chat_log_buffer."""
            try:
                import pyperclip as _pc
            except ImportError:
                self._clipboard_status("[yellow]⚠ pip install pyperclip[/]", 4.0)
                return
            try:
                buf = getattr(self, "_chat_log_buffer", [])
                text = "\n".join(buf) if buf else (getattr(self, "_last_ai_reply", "").strip() or "(log vide)")
                _pc.copy(text)
                nb = text.count("\n") + 1
                logger.info(f"[CLIPBOARD Ctrl+L] {nb} lignes / {len(text)} chars")
                self._clipboard_status(f"[green]📜 {nb} lignes copiées[/]")
            except Exception as e:
                logger.debug(f"copy_full_log: {e}")
                self._clipboard_status(f"[red]Erreur clipboard : {e}[/]", 4.0)

        def on_label_clicked(self, event: object) -> None:
            """Clic souris sur les icônes 📋/📜 dans la barre titre."""
            wid = getattr(event.widget, "id", "") or ""
            if wid == "btn-copy-reply":
                self.action_copy_last_reply()
            elif wid == "btn-copy-log":
                self.action_copy_full_log()

        def compose(self) -> ComposeResult:
            """Compose."""
            yield Header(show_clock=True)
            with Horizontal(id="main-layout"):
                with Vertical(id="sidebar"):
                    # ── Orchestrateur + version ───────────────────────────────
                    yield Static("[bold #58a6ff]⚒ La Forge[/]", id="orc-title")
                    yield Static(
                        f"[dim]v{version_manager.current_version} · {self.session_name[:12]}[/]", id="orc-version"
                    )
                    # ── Modes orchestrateur ───────────────────────────────────
                    yield Button("🤖 Auto", id="btn-mode-autonome", classes="mode-btn -active")
                    yield Button("🏓 Ping", id="btn-mode-ping", classes="mode-btn")
                    yield Button("🎯 Chef", id="btn-mode-chef", classes="mode-btn")
                    yield Button("⚔ Débat", id="btn-mode-debat", classes="mode-btn")
                    yield Button("🔗 Cline", id="btn-mode-cline", classes="mode-btn")
                    # ── Sudo toggle ──────────────────────────────────────────
                    yield Button("🔒 Sudo OFF", id="btn-sudo-toggle", classes="mode-btn")
                    # ── Séparateur ────────────────────────────────────────────
                    yield Static("─" * 20, classes="sb-sep")
                    # ── Panneau des rôles (LEDs) ──────────────────────────────
                    yield self.role_panel
                    # ── Séparateur ────────────────────────────────────────────
                    yield Static("─" * 20, classes="sb-sep")
                    # ── RAG status ────────────────────────────────────────────
                    yield self.rag_info
                    # ── SkillTree Agentic ────────────────────────────────────
                    yield Static("─" * 20, classes="sb-sep")
                    yield EntropyGauge(id="entropy-gauge")
                    yield Static("", id="staging-indicator")
                    yield self.skill_panel
                    # ── Métriques ─────────────────────────────────────────────
                    yield self.metrics
                    # ── Sessions ──────────────────────────────────────────────
                    yield Static("[dim]Sessions:[/]", id="sess-label")
                    yield ListView(
                        *[ListItem(Label(f"📁 {s}"), id=f"session_{s}") for s in self._saved_sessions()],
                        id="session-list",
                    )
                    yield Button("📂 RAG dir", id="btn-rag-open", classes="sb-btn")
                    yield Static("", id="prog-label")
                    yield ProgressBar(total=100, show_eta=False, id="rag-prog")

                with Horizontal(id="center-layout"):
                    with Vertical(id="chat-panel"):
                        with Horizontal(id="chat-title-bar"):
                            yield Static(
                                " [bold #58a6ff]⚒ La Forge[/]  [dim]@help · @run · @rag · @audit · @estim[/]",
                                id="chat-title",
                            )
                            yield Label("📋", id="btn-copy-reply", classes="copy-btn")
                            yield Label("📜", id="btn-copy-log", classes="copy-btn")
                        yield RichLog(id="chat-log", wrap=True, markup=True, auto_scroll=True)
                        yield Static("", id="ai-status")
                        yield Static("", id="no-ssh-banner")
                        with Vertical(id="input-bar"):
                            yield AutocompleteInput(placeholder="Message… (@help | numéro suggestion)", id="chat-input")
                    yield VSplitter(id="v-splitter", classes="hidden")
                    with Vertical(id="terminal-panel"):
                        yield Static(" [bold #3fb950]🖥 SSH[/]  [dim]Ctrl+T · focus[/]", id="term-title")
                        yield self.terminal
            yield Footer()
            if HAS_GUI_DEBUG and GuiDebugOverlay is not None:
                yield GuiDebugOverlay()

        def _set_ssh_mode(self, connected: bool, hostname: str = "") -> None:
            """
            Bascule le layout selon l'état SSH.
            connected=False → terminal masqué, chat pleine largeur
            connected=True  → terminal visible, splitter actif
            hostname        → vrai nom machine (pas l'IP) pour le titre terminal


            Args:
                connected (bool): Connected.
                hostname (str (optional)): Hostname.
            """
            logger.debug(f"[_set_ssh_mode] connected={connected} hostname={hostname!r}")
            self._ssh_connected = connected
            if hostname:
                self._pending_hostname = hostname
            try:
                term = self.query_one("#terminal-panel")
                split = self.query_one("#v-splitter")
                title = self.query_one("#term-title")
                chat = self.query_one("#chat-panel")
                banner = self.query_one("#no-ssh-banner")

                if connected:
                    _host = hostname or self._pending_hostname or settings.ssh_host or "SSH"
                    title.update(f" [bold #3fb950]🖥 {_host}[/]  [dim]Ctrl+T · focus[/]")
                    logger.info(f"[_set_ssh_mode] titre mis à jour → {_host!r}")
                    # display=True en premier → Textual alloue l'espace avant remove_class
                    term.display = True
                    split.display = True
                    title.display = True
                    term.remove_class("hidden")
                    split.remove_class("hidden")
                    title.remove_class("hidden")
                    chat.remove_class("expanded")
                    banner.remove_class("visible")
                    chat.styles.width = "1fr"
                    term.styles.width = "1fr"
                    self.refresh(layout=True)
                else:
                    term.add_class("hidden")
                    split.add_class("hidden")
                    title.add_class("hidden")
                    chat.add_class("expanded")
                    banner.add_class("visible")
                    banner.update("[dim]Pas de SSH · [bold]@ssh <host>[/] pour ouvrir le terminal[/]")
            except Exception as _e:
                logger.debug(f"[_set_ssh_mode] exception={_e!r}, call_later → _apply_pending_ssh_mode")
                self.call_later(self._apply_pending_ssh_mode)

        def _apply_pending_ssh_mode(self) -> None:
            """Applique l'état SSH différé (appelé après mount des widgets)."""
            if self._ssh_connected and self._pending_hostname:
                logger.debug(f"[_apply_pending_ssh_mode] hostname={self._pending_hostname!r}")
                self._set_ssh_mode(True, hostname=self._pending_hostname)

        def _chat_log(self) -> RichLog:
            """Chat log."""
            return self.query_one("#chat-log", RichLog)

        def _drain_m2m_nokido(self) -> None:
            """Draine la mailbox M2M agt_nokido -> chat (miroir client du [HOOK:INBOX]).

            Nokido TUI n'est PAS un client HTTP du hub : hub_lifecycle_hooks.post_dispatch
            surface l'INBOX aux CLI clients-HTTP (codex/claude/gemini) mais ne peut PAS
            atteindre une app in-process. On lit donc agent_messages en direct et on
            MARQUE read (sinon re-spam a chaque intervalle ; contrairement au hook qui
            lit en read-only et re-surface). Sync + court (SQLite local) : ne bloque pas
            l'event loop Textual.
            """
            import sqlite3 as _sq
            import json as _j
            from pathlib import Path as _P
            try:
                from nokido_agent.app.forge_db_path import m2m_path as _m2m_path   # scission M2M : suit l'interrupteur
                _db = _P(_m2m_path())
                if not _db.exists():
                    return
                _c = _sq.connect(str(_db), timeout=3.0)
                _c.execute("PRAGMA busy_timeout=3000")
                _rows = _c.execute(
                    "SELECT id, from_agent, payload FROM agent_messages "
                    "WHERE to_agent IN ('agt_nokido','nokido') AND status='unread' "
                    "ORDER BY rowid ASC LIMIT 10").fetchall()
                for _id, _frm, _pl in _rows:
                    try:
                        _txt = _j.loads(_pl).get("text", _pl)
                    except Exception:
                        _txt = _pl
                    self._chat_log().write(
                        f"[bold #58a6ff]M2M[/] [dim]de {_frm}[/]: {_txt}")
                    _c.execute(
                        "UPDATE agent_messages SET status='read' WHERE id=?", (_id,))
                if _rows:
                    _c.commit()
                _c.close()
            except Exception as _e:
                logger.debug(f"[m2m drain] {type(_e).__name__}: {_e}")

        def _refresh_version_display(self) -> None:
            """Met à jour sub_title + sidebar après un @apply."""
            try:
                v = version_manager.current_version
                _hn = getattr(self, "_pending_hostname", "") or settings.ssh_host or ""
                self.sub_title = f"v{__version__} · {_hn}" if _hn else f"v{__version__}"
                orc_ver = self.query_one("#orc-version", Static)
                orc_ver.update(f"[dim]v{v} · {self.session_name[:12]}[/]")
                logger.info(f"[version display] mis à jour → v{v}")
            except Exception as _e:
                logger.debug(f"[_refresh_version_display] {_e}")

        def _set_staging_indicator(self, state: str) -> None:
            """Set staging indicator.

            Args:
                state: Description.
            """
            icons = {
                "staging": "[bold blue]💾 Staging…[/]",
                "commit": "[bold green]💾 Commit ✓[/]",
                "rollback": "[bold red]⏪ Rollback[/]",
                "": "",
            }
            try:
                self.query_one("#staging-indicator", Static).update(icons.get(state, ""))
            except Exception:
                pass

        def _set_status(self, msg: str) -> None:
            """Set status.

            Args:
                msg: Description.
            """
            try:
                self.query_one("#ai-status", Static).update(msg)
            except Exception:
                pass

        def _current_model(self) -> str:
            """Current model."""
            if self.current_agent == AgentType.CHAT:
                return self.model_chat
            if self.current_agent == AgentType.ACTION:
                return self.model_action
            return self.model_rag

        def _set_agent(self, agent: AgentType, _from_user: bool = True) -> None:
            """
            Change l'agent courant affiché dans l'UI.
            NE DOIT ÊTRE APPELÉ QUE DEPUIS UNE ACTION EXPLICITE UTILISATEUR
            (Ctrl+1/2/3 ou F2/F3/F4, boutons). Jamais depuis l'orchestrateur interne.
            _from_user=False est réservé pour les tests.


            Args:
                agent (AgentType): Agent.
                _from_user (bool (optional)):  from user.
            """
            if not _from_user:
                return  # protection anti-boucle orchestrateur
            from nokido_agent.app.forge_gui_debug import debug_log as _dl  # tombeau

            _dl(
                hypothesis_id="H1",
                location="DevOpsApp._set_agent",
                message="Changement d'agent courant",
                data={
                    "from": self.current_agent.value if hasattr(self, "current_agent") and self.current_agent else None,
                    "to": agent.value,
                },
            )
            self.current_agent = agent
            self.agent_selector.set_agent(agent)
            meta = AGENT_META[agent]
            self._set_status(f"[{meta['color']}]{meta['icon']} {meta['label']}[/] actif")
            try:
                self.query_one("#chat-title", Static).update(
                    f" [bold {meta['color']}]{meta['icon']} {meta['label']}[/]  "
                    f"[dim]@help · @run · @rag · @audit · @estim[/]"
                )
            except Exception:
                pass
            try:
                self.query_one("#btn-model", Button).label = f"🤖 {self._current_model()[:18]}"
            except Exception:
                pass
            self._update_sidebar_title()

        def _update_sidebar_title(self) -> None:
            """Update sidebar title."""
            try:
                ver = version_manager.current_version
                self.query_one("#orc-title", Static).update("[bold #58a6ff]⚒ La Forge[/]")
                self.query_one("#orc-version", Static).update(f"[dim]v{ver} · {self.session_name[:12]}[/]")
            except Exception:
                pass

        def _update_mode_buttons(self) -> None:
            """Met à jour visuellement les boutons de mode orchestrateur."""
            try:
                for mode_id in ("autonome", "ping", "chef", "debat", "cline"):
                    btn = self.query_one(f"#btn-mode-{mode_id}", Button)
                    if mode_id == self._collab_mode:
                        btn.add_class("-active")
                    else:
                        btn.remove_class("-active")
            except Exception:
                pass

        def _saved_sessions(self) -> List[str]:
            """Saved sessions."""
            sessions = []
            for f in _DATA_DIR.glob("session_*.json"):
                sessions.append((f.stat().st_mtime, f.stem[8:]))
            sessions.sort(reverse=True)
            return [name for _, name in sessions]

        async def on_mount(self) -> None:
            """On mount."""
            global rag_engine, orchestrator_state
            boot_step("on_mount", ok=True, detail=f"v{__version__}")
            # M2M : draine la mailbox agt_nokido -> chat toutes les 20 s
            # (miroir client du [HOOK:INBOX] ; la TUI n'est PAS cliente HTTP du hub,
            #  donc post_dispatch ne la sert pas — on lit la mailbox directement).
            self.set_interval(20.0, self._drain_m2m_nokido)
            # Injecter singletons top-level dans forge_context des le debut
            # Résoudre settings + ssh_manager en tête de on_mount
            from nokido_agent.app.forge_app_context import get_settings as _gset

            settings = getattr(self, "settings", None) or _gset()
            # ssh_manager : utiliser le global du module ou créer si absent
            import sys as _sys_sm

            ssh_manager = None
            for _mn in ("__main__", "Nokido", "app.Nokido"):
                _m = _sys_sm.modules.get(_mn)
                if _m and getattr(_m, "ssh_manager", None) is not None:
                    ssh_manager = _m.ssh_manager
                    break
            if ssh_manager is None:
                from nokido_agent.app.forge_core_models import SSHManager as _SSHM

                ssh_manager = _SSHM()
            # ══ CANARI DÉMARRAGE — vérifie les imports critiques ══════════
            _canary_errors = []
            _canary_checks = [
                ("forge_handlers", ["_handle_rag", "_handle_nr", "classify_with_cmd"]),
                ("forge_hub_handlers", ["handle_ci", "handle_workflow"]),
                ("forge_at_dispatch", ["AT_DISPATCH"]),
                ("forge_ollama", ["ollama_call", "ollama_stream"]),
                ("forge_rag_warmup", ["rag_self_warmup"]),
                ("forge_startup", ["main", "_read_env_file", "_init_onnx_bg"]),
                ("forge_compose", ["compose"]),
                ("forge_capabilities", ["get_caps"]),
            ]
            for _mod, _fns in _canary_checks:
                try:
                    import importlib as _il

                    _m = _il.import_module(_mod)
                    for _fn in _fns:
                        if not hasattr(_m, _fn):
                            _canary_errors.append(f"❌ {_mod}.{_fn} manquant")
                except Exception as _ce:
                    _canary_errors.append(f"❌ import {_mod}: {_ce}")
            if _canary_errors:
                for _err in _canary_errors:
                    logger.error(f"[CANARI] {_err}")
                    try:
                        self._chat_log().write(f"[bold red][CANARI] {_err}[/]")
                    except Exception:
                        pass
                try:
                    from nokido_agent.app.forge_self_correction import anchor_error as _ae

                    _ae(error="\n".join(_canary_errors), context="on_mount canari", solution="Vérifier imports tombeau")
                except Exception:
                    pass
            else:
                logger.info("[CANARI] ✅ tous les imports critiques OK")
            # ══ FIN CANARI ════════════════════════════════════════════════
            if HAS_GUI_DEBUG:
                try:
                    patch_app_for_debug(self)
                except Exception as _dbe:
                    logger.debug(f"[gui-debug] patch: {_dbe}")
            self.sub_title = f"v{__version__}"
            logger.info(f"[on_mount START] __version__={__version__!r}  workspace={version_manager.current_version!r}")
            logger.info(f"[on_mount] ROOT={_ROOT_DIR}  LOGS={_LOGS_DIR}")
            try:
                _bak_dir = _APP_DIR / "backups"
                _bak_dir.mkdir(exist_ok=True)
                _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                _dst = _bak_dir / f"auto_boot_{_ts}.py"
                if (_APP_DIR / "Nokido.py").exists():
                    import shutil as _sb

                    _sb.copy2(_APP_DIR / "Nokido.py", _dst)
                    for _o in sorted(_bak_dir.glob("auto_boot_*.py"), key=lambda p: p.stat().st_mtime, reverse=True)[
                        10:
                    ]:
                        try:
                            _o.unlink()
                        except Exception:
                            pass
                    logger.info(f"[boot] Auto-backup -> {_dst.name}")
            except Exception as _be:
                logger.debug(f"[boot] backup: {_be}")
                boot_step("backup", ok=False, error=str(_be)[:60])
            else:
                boot_step("backup", ok=True)
            _rag_warmup_done = None  # defini avant le bloc conditionnel RAG
            if settings.use_rag and rag_engine is None:
                # Decision owner 1 du 25/09 : le RAG passe par le HUB. `RAGEngine()` ici
                # parcourait TOUTES les lignes actives de rag_chunks dans la boucle de
                # l'interface (pile faulthandler : ecran gele > 45 s, Go de RAM, lecteur long
                # sur la base de 45 Go a chaque ouverture). Le local reste un opt-in explicite.
                import os as _os_rag

                if _os_rag.environ.get("LAFORGE_TUI_RAG_LOCAL") == "1":
                    rag_engine = RAGEngine()
                else:
                    from nokido_agent.app.forge_rag_via_hub import RAGViaHub

                    rag_engine = RAGViaHub()
                asyncio.create_task(rag_engine.index_pending())
                from nokido_agent.app import forge_context as _fc

                _fc.rag_engine = rag_engine
                _fc.version_manager = version_manager
                boot_step("rag_engine", ok=True, detail="RAGEngine init")
                mem_checkpoint("after_rag_init")
                # ── RAG warmup : conscience de soi ───────────────────────────
                _rag_warmup_done = asyncio.Event()  # signal — deja defini avant

                async def _warmup_with_signal() -> None:
                    """Warmup with signal."""
                    try:
                        await self._rag_self_warmup(_done_event=_rag_warmup_done)
                    finally:
                        if _rag_warmup_done is not None and not _rag_warmup_done.is_set():
                            _rag_warmup_done.set()
                            logger.debug("[MemMgr] _rag_warmup_done.set() (finally)")

                if not os.environ.get("LAFORGE_ROBOT"):
                    asyncio.create_task(_warmup_with_signal())
                else:
                    if _rag_warmup_done:
                        _rag_warmup_done.set()

            # ── Gérer la perte de focus (minimize / fenêtre par-dessus) ──────
            # Textual peut "geler" l'affichage quand l'app perd le focus terminal.
            # On s'abonne à SIGWINCH pour forcer un refresh quand le terminal
            # est redimensionné ou restauré.
            import signal as _sig

            def _on_winch(*_) -> None:
                """On winch."""
                try:
                    self.refresh(layout=True)
                    self.call_later(self.refresh, layout=True)
                except Exception:
                    pass

            try:
                _sig.signal(_sig.SIGWINCH, _on_winch)
            except (OSError, ValueError, AttributeError):
                pass  # SIGWINCH indisponible (Windows)

            self.context = SessionContext(self.session_name)
            orchestrator_state = OrchestratorState()

            # ── Si SSH non configuré → ouvrir le wizard TUI ─────────────
            if not settings.ssh_host:

                async def _after_wizard(configured: bool) -> None:
                    """After wizard.

                    Args:
                        configured: Description.
                    """
                    if not configured:
                        self._set_ssh_mode(False)
                        self._chat_log().write(
                            "[yellow]⚠ Mode local — pas de connexion SSH.[/]\n"
                            "  [dim]Le terminal est masqué. Tapez [bold]@ssh <host>[/] pour vous connecter.[/]"
                        )
                        return
                    # Connexion avec les valeurs saisies dans le wizard
                    try:
                        await ssh_manager.connect()
                        _hn = settings.ssh_host
                        try:
                            _o, _, _ = await run_ssh("hostname -f 2>/dev/null || hostname")
                            _hn = _strip_ssh_output(_o)
                        except Exception:
                            pass
                        _kern = ""
                        try:
                            _o2, _, _ = await run_ssh("uname -r")
                            _kern = _strip_ssh_output(_o2)
                        except Exception:
                            pass
                        _ks = f" · [dim]kernel {_kern}[/]" if _kern else ""
                        self._set_ssh_mode(True, hostname=_hn or settings.ssh_host)
                        self._chat_log().write(
                            f"[green]✅ SSH[/] [bold]{_hn}[/] "
                            f"[dim]({settings.ssh_host}:{settings.ssh_port})[/] "
                            f"{ssh_manager.os_type} privilege={'[green]' + ssh_manager.privilege_method + '[/]' if ssh_manager.sudo_available else '[yellow]none[/]'}"
                            f"{_ks}"
                        )
                    except Exception as _e:
                        self._set_ssh_mode(False)
                        self._chat_log().write(f"[red]❌ SSH: {_e}[/]")

                self.push_screen(SSHWizardScreen(lambda ok: asyncio.create_task(_after_wizard(ok))))
            else:
                try:
                    await ssh_manager.connect()
                    # Récupérer hostname + kernel pour affichage au démarrage
                    _hn, _kern = "", ""
                    try:
                        _hn_out, _, _ = await run_ssh("hostname -f 2>/dev/null || hostname")
                        _hn = _strip_ssh_output(_hn_out)
                    except Exception:
                        _hn = settings.ssh_host
                    try:
                        _kern_out, _, _ = await run_ssh("uname -r")
                        _kern = _strip_ssh_output(_kern_out)
                    except Exception:
                        pass
                    _kern_str = f" · [dim]kernel {_kern}[/]" if _kern else ""
                    self._set_ssh_mode(True, hostname=_hn or settings.ssh_host)
                    self._chat_log().write(
                        f"[green]✅ SSH[/] [bold]{_hn or settings.ssh_host}[/] "
                        f"[dim]({settings.ssh_host}:{settings.ssh_port})[/] "
                        f"{ssh_manager.os_type} privilege={'[green]' + ssh_manager.privilege_method + '[/]' if ssh_manager.sudo_available else '[yellow]none[/]'}"
                        f"{_kern_str}"
                    )
                except Exception as e:
                    self._set_ssh_mode(False)
                    self._chat_log().write(f"[red]❌ SSH: {e}[/]")

            ok = await self.terminal.connect()
            self._chat_log().write("[green]✅ Terminal PTY prêt[/]" if ok else "[yellow]⚠ Terminal non disponible[/]")
            logger.info(f"[boot] Terminal PTY : {'OK' if ok else 'non disponible'}")
            boot_step("terminal_pty", ok=ok, detail="PTY prêt" if ok else "non disponible")

            boot_step("onnx", ok=HAS_ONNX, detail="sidecar actif" if HAS_ONNX else "forge_runtime absent")
            if HAS_ONNX:
                # [→ forge_startup.py] _init_onnx_bg

                asyncio.create_task(_init_onnx_bg())
            else:
                self._chat_log().write("[dim]⚡ Sidecar [yellow]⚠ forge_runtime.py manquant dans app/[/][/]")
                logger.warning("[boot] Sidecar : forge_runtime.py manquant")

            try:
                await self._check_ollama_models()
            except Exception as _ome:
                logger.warning(f"[boot] Ollama check skipped: {_ome}")

            if prefect_manager is not None:
                await prefect_manager.start()

            if rag_engine:
                asyncio.create_task(self._update_rag_info())

            _arch_summary = self.arch.summary() if self.arch else settings.ssh_host or "SSH"
            self._chat_log().write(
                f"[bold #58a6ff]⚒ La Forge v{version_manager.current_version}[/] · 🖥 {_arch_summary} · @help"
            )
            boot_step("boot_complete", ok=True, detail=f"v{version_manager.current_version}")
            boot_finalize(
                ring=int(getattr(self.guard, "active_ring", None) or getattr(self.guard, "ring", 1))
                if self.guard
                else 1
            )
            logger.info(f"[boot] La Forge v{version_manager.current_version} | {_arch_summary}")

            # ── Service Registry (routage réseau modulaire) ───────────────
            if HAS_SERVICES:
                _svc_path = _DATA_DIR / "services.json"
                _reg = init_registry(_svc_path)
                _n = len(_reg.all()) if _reg else 0
                logger.info(f"[boot] Services : {_n} endpoints enregistrés")
                boot_step("services", ok=True, detail=f"{_n} endpoints")

            # ── Initialiser l'AgenticEngine avec callback vers SkillTree ─
            global agentic_engine, _skill_learner
            # SkillLearner (arbre hierarchique)
            if HAS_SKILLTREE:
                _skill_learner = SkillLearner(registry_path=_DATA_DIR / "skill_registry.json")
                _skill_learner.on_update(
                    lambda name, status: self.call_from_thread(self.skill_panel.add_or_update, name, status)
                )
                # Bootstrap : remplacer placeholder par vrai SkillTree
                self.call_after_refresh(self.skill_panel.bootstrap_tree)
            agentic_engine = AgenticEngine(
                ui_callback=lambda name, status: self.call_from_thread(self.skill_panel.add_or_update, name, status),
                log_fn=lambda m: self._chat_log().write(m),
            )
            # Charger les compétences existantes dans le panneau
            if agentic_engine._skills:
                self.skill_panel.render_summary(agentic_engine.get_skill_summary())

            # ── Apprentissage autonome en background ─────────────────────
            # Injecter agentic_engine dans forge_context
            from nokido_agent.app import forge_context as _fc_ae

            _fc_ae.agentic_engine = agentic_engine
            if HAS_SKILLTREE and _skill_learner and agentic_engine:

                async def _auto_learn() -> None:
                    """Auto learn."""
                    await _skill_learner.run_autonomous(
                        discover_fn=agentic_engine._discover_and_ingest,
                        check_fn=agentic_engine.check_competence,
                        log_fn=lambda m: self._chat_log().write(m),
                    )

                asyncio.create_task(_auto_learn())

            self._update_mode_buttons()
            self._setup_chat_buffer()  # patch RichLog.write → buffer
            self.query_one("#chat-input", AutocompleteInput).focus()

        async def _check_ollama_models(self) -> object:
            """Check ollama models."""
            from nokido_agent.app.forge_handlers import _check_ollama_models as _fh

            return await _fh(self)

        async def _open_model_screen(self, args: str = "") -> None:
            """Ouvre ModelScreen — appele par _cmd_model via app._open_model_screen."""
            import aiohttp

            try:
                async with aiohttp.ClientSession() as _s:
                    async with _s.get(settings.ollama_tags_url, timeout=aiohttp.ClientTimeout(total=5)) as _r:
                        _data = await _r.json()
                        models = [m["name"] for m in _data.get("models", []) if "embed" not in m["name"].lower()]
                if not models:
                    self._chat_log().write("[yellow]⚠ Aucun modèle — ollama serve ?[/]")
                    return

                def cb(selected: object) -> None:
                    """Cb.

                    Args:
                        selected: Description.
                    """
                    if not selected:
                        return
                    if self.current_agent == AgentType.CHAT:
                        self.model_chat = selected
                    elif self.current_agent == AgentType.ACTION:
                        self.model_action = selected
                    else:
                        self.model_rag = selected
                    self._set_agent(self.current_agent)
                    self._update_sidebar_title()
                    save_last_assignment(self.model_chat, self.model_action, self.model_rag)
                    self._chat_log().write(f"[green]✅ Modèle [bold]{selected}[/] sélectionné[/]")

                self.push_screen(ModelScreen(models, self._current_model(), cb))
            except Exception as _e:
                self._chat_log().write(f"[red]❌ @model: {_e}[/]")

        async def _update_rag_info(self) -> None:
            """Update rag info."""
            while True:
                if rag_engine:
                    self.rag_info.sync()
                await asyncio.sleep(5)

        async def _rag_self_warmup(self, _done_event: object = None) -> None:
            """Rag self warmup.

            Args:
                _done_event: Description.
            """
            from nokido_agent.app.forge_rag_warmup import rag_self_warmup as _rsw

            await _rsw(self, _rag_warmup_done=_done_event)

        async def on_unmount(self) -> object:
            """On unmount."""
            from nokido_agent.app.forge_handlers import on_unmount as _fh

            return await _fh(self)

        def action_focus_term(self) -> None:
            """Action focus term."""
            try:
                tp = self.query_one("#terminal-panel")
                if "hidden" in tp.classes:
                    tp.remove_class("hidden")
                if self.terminal:
                    self.terminal.focus()
            except Exception as _e_t:
                import logging

                logging.getLogger("Nokido").warning(f"[PTY] focus err: {_e_t}")

        def action_toggle_sidebar(self) -> None:
            """Ctrl+B : masquer/afficher la sidebar pour agrandir le chat."""
            try:
                sb = self.query_one("#sidebar")
                if "hidden-sidebar" in sb.classes:
                    sb.remove_class("hidden-sidebar")
                    self._clipboard_status("[dim]Sidebar visible[/]")
                else:
                    sb.add_class("hidden-sidebar")
                    self._clipboard_status("[dim]Sidebar masquée — Ctrl+B pour réafficher[/]")
            except Exception:
                pass

        def action_copy_all_log(self) -> None:
            """Ctrl+Shift+A ou F6 : copie tout le log chat."""
            try:
                import pyperclip as _pc

                buf = getattr(self, "_chat_log_buffer", [])
                if not buf:
                    self._clipboard_status("[dim]Log vide[/]")
                    return
                _pc.copy("\n".join(buf))
                self._clipboard_status(f"[green]Tout copié ({len(buf)} lignes)[/]")
            except ImportError:
                self._clipboard_status("[yellow]⚠ pip install pyperclip[/]", 4.0)
            except Exception as e:
                self._clipboard_status(f"[red]Erreur : {e}[/]")

        def action_focus_input(self) -> None:
            """Action focus input."""
            self.query_one("#chat-input", AutocompleteInput).focus()

        def on_focus(self) -> None:
            """App reprend le focus — forcer un refresh complet."""
            self.refresh(layout=True)

        def on_screen_resume(self) -> None:
            """Écran Textual restauré (après minimize ou fenêtre par-dessus)."""
            self.refresh(layout=True)
            try:
                self.call_later(self.refresh, layout=True)
            except Exception:
                pass

        def on_error(self, error: Exception) -> None:
            """Intercepte les erreurs Textual — les redirige vers le logger, pas l'UI."""
            logger.error(f"Textual error: {error}", exc_info=False)
            # Ne pas propager → évite l'affichage dans le Footer/bas de page

        def action_toggle_debug(self) -> None:
            """Ctrl+D — afficher/cacher le panneau debug GUI."""
            if HAS_GUI_DEBUG:
                try:
                    self.query_one(GuiDebugOverlay).toggle_visibility()
                except Exception:
                    pass

        def handle_exception(self, error: Exception) -> None:
            """Override Textual App.handle_exception pour bloquer le traceback UI."""
            logger.error(f"App exception: {error}", exc_info=True)

        async def on_button_pressed(self, event: Button.Pressed) -> None:
            """On button pressed.

            Args:
                event: Description.
            """
            bid = event.button.id or ""
            # ── Mode orchestrateur ────────────────────────────────────────────
            if bid in ("btn-mode-autonome", "btn-mode-ping", "btn-mode-chef", "btn-mode-debat", "btn-mode-cline"):
                mode = bid.replace("btn-mode-", "")
                self._collab_mode = mode
                self._update_mode_buttons()
                _MC = {
                    "autonome": "#79c0ff",
                    "ping": "#56d364",
                    "chef": "#ffa657",
                    "debat": "#d2a8ff",
                    "cline": "#ff7b72",
                }
                _MI = {"autonome": "🤖", "ping": "🏓", "chef": "🎯", "debat": "⚔", "cline": "🔗"}
                self._chat_log().write(
                    f"[bold #8b949e]Mode → [/][bold {_MC.get(mode, '#8b949e')}]{_MI.get(mode, '')} {mode}[/]"
                )
                return
            # ── Sudo toggle ─────────────────────────────────────────────────
            if bid == "btn-sudo-toggle":
                self._sudo_unlocked = not self._sudo_unlocked
                btn = event.button
                if self._sudo_unlocked:
                    btn.label = "🔓 Sudo ON"
                    btn.styles.background = "#5c1a1a"
                    btn.styles.color = "#ff6b6b"
                    self._chat_log().write(
                        "[bold red]🔓 Sudo DÉVERROUILLÉ[/] — les commandes sudo seront injectées dans le terminal.\n"
                        "[dim]  ⚠ Attention : les commandes dangereuses restent bloquées (rm -rf, mkfs, dd…)[/]"
                    )
                else:
                    btn.label = "🔒 Sudo OFF"
                    btn.styles.background = "#0d1f33"
                    btn.styles.color = "#79c0ff"
                    self._chat_log().write(
                        "[green]🔒 Sudo verrouillé[/] — les commandes sudo ne seront plus injectées."
                    )
                return
            elif bid == "btn-model":
                await self._select_model()
            elif bid == "btn-rag-open":
                path = Path(settings.rag_dir)
                if sys.platform == "win32":
                    os.startfile(path)
                elif sys.platform == "darwin":
                    os.system(f"open {path}")
                else:
                    os.system(f"xdg-open {path}")
                self._chat_log().write(f"[dim]📁 Ouverture de {path}[/]")

        async def on_list_view_selected(self, event: ListView.Selected) -> None:
            """On list view selected.

            Args:
                event: Description.
            """
            try:
                item_id = event.item.id
                if not item_id or not item_id.startswith("session_"):
                    return
                name = item_id[8:]
                if not name:
                    return

                if self.context:
                    self.context.unregister()
                self.session_name = name
                self.context = SessionContext(name)
                # Réinitialise le contexte de conversation de l'orchestrateur
                orc = get_orchestrator()
                orc.state.current_session = name
                asyncio.create_task(orc.reset_context())
                self._update_sidebar_title()
                self._chat_log().write(
                    f"[dim]📂[/] Session [bold #58a6ff]{name}[/] chargée ([dim]{len(self.context.messages)} msg[/])"
                )
            except Exception as e:
                logger.error(f"Erreur session: {e}")
                self._chat_log().write(f"[red]❌ Erreur chargement session: {e}[/]")

        async def on_input_submitted(self, event: Input.Submitted) -> None:
            """Gère la soumission avec orchestration."""
            txt = event.value.strip()
            if not txt:
                return
            event.input.value = ""

            # Commandes d'urgence
            if txt == "@reset":
                if self.ai_task and not self.ai_task.done():
                    self.ai_task.cancel()
                self.ai_busy = False
                self._set_status("")
                self._chat_log().write("[yellow]⟳ IA réinitialisée.[/]")
                return

            if txt == "@status":
                meta = AGENT_META[self.current_agent]
                self._chat_log().write(
                    f"Agent : [bold {meta['color']}]{meta['icon']} {meta['label']}[/] · "
                    f"Modèle : [bold]{self._current_model()}[/] · "
                    f"IA : {'[red]occupée[/]' if self.ai_busy else '[green]libre[/]'}"
                )
                return

            # Utilisation de l'orchestrateur pour le routage intelligent
            if settings.auto_switch_agent and not txt.startswith("@"):
                await self._handle_orchestrated_input(txt)
            else:
                # Traitement direct pour les commandes @
                await self._handle_orchestrated_input(txt)

        async def _handle_orchestrated_input(self, user_input: str) -> None:
            """Gère les entrées via orchestrateur."""
            chat = self._chat_log()

            # ── Enregistrer dans l'historique chat (pour autocomplete ↑/↓) ──
            # On enregistre AVANT tout autre traitement
            _ac_engine = getattr(self, "_autocomplete_engine", None)
            if _ac_engine is None:
                # Récupérer l'engine depuis le widget input ou en créer un partagé
                try:
                    _ac_engine = self.query_one("#chat-input", AutocompleteInput)._engine
                    self._autocomplete_engine = _ac_engine
                except Exception:
                    self._autocomplete_engine = AutocompleteEngine()
                    _ac_engine = self._autocomplete_engine
            _ac_engine.add_to_history(user_input)

            # ── Sélection de suggestion d'audit par numéro ou "t" ───────────
            # Si l'utilisateur tape "1", "2"... ou "t" après un @audit
            if self.last_audit_suggestions:
                stripped = user_input.strip().lower()
                if stripped == "t":
                    # Tout appliquer — skip les suspectes, les signaler
                    chat.write(f"[bold #79c0ff]▸[/] {escape(user_input)}")
                    _ok_count, _skip_count = 0, 0
                    for sugg in self.last_audit_suggestions:
                        if not sugg.get("validated", True):
                            _iss = " · ".join(sugg.get("issues", [])[:2])
                            _msg = f"[yellow]⏭ Suggestion {sugg['num']} ignorée (suspecte) : {_iss}[/]"
                            chat.write(_msg)
                            chat.write(f"[dim]  → Tape [bold]{sugg['num']}[/] pour forcer l'application.[/]")
                            _skip_count += 1
                            continue
                        if await self._apply_suggestion(sugg, _ask_restart=False):
                            _ok_count += 1
                    _vf = version_manager.current_version
                    chat.write(
                        f"[bold green]✅ {_ok_count}/{len(self.last_audit_suggestions)} suggestions appliquées → v{_vf}[/]"
                    )
                    if _skip_count:
                        chat.write(
                            f"[yellow]⚠ {_skip_count} suspecte(s) ignorée(s) — [bold]v[/] = validées seulement · numéro = forcer[/]"
                        )
                    if _ok_count > 0:
                        self._propose_restart(f"{_ok_count} suggestions → v{_vf}")
                    return

                if stripped == "v":
                    # Appliquer uniquement les suggestions validées
                    chat.write(f"[bold #79c0ff]▸[/] {escape(user_input)}")
                    valid_suggs = [s for s in self.last_audit_suggestions if s.get("validated", True)]
                    if not valid_suggs:
                        chat.write("[dim]Aucune suggestion validée disponible.[/]")
                        return
                    _ok_count = 0
                    for sugg in valid_suggs:
                        if await self._apply_suggestion(sugg, _ask_restart=False):
                            _ok_count += 1
                    _vf = version_manager.current_version
                    chat.write(f"[bold green]✅ {_ok_count}/{len(valid_suggs)} validées appliquées → v{_vf}[/]")
                    if _ok_count > 0:
                        self._propose_restart(f"{_ok_count} validées → v{_vf}")
                    return
                if stripped.isdigit():
                    num = int(stripped)
                    sugg = next((s for s in self.last_audit_suggestions if s["num"] == num), None)
                    if sugg:
                        chat.write(f"[bold #79c0ff]▸[/] {escape(user_input)}")
                        if await self._apply_suggestion(sugg, _ask_restart=False):
                            self._propose_restart(f"suggestion {num} → v{version_manager.current_version}")
                        return

            # Affichage initial
            chat.write(f"[bold #79c0ff]▸[/] {escape(user_input)}")

            if user_input.startswith("@"):
                # Commandes spéciales (@help, @run, etc.) - traitement normal
                await self._handle_at(user_input)
            else:
                # ── Log dev:llm (mode DEV) ───────────────────────────────
                try:
                    import os as _os_dlm

                    if _os_dlm.environ.get("LAFORGE_ENV", "") == "dev":
                        from nokido_agent.app.forge_conv_sanitizer import log_secure as _ls

                        _sid = getattr(self, "session_name", "") or "default"
                        _ls(_sid, "human:tui", user_input, role="user", mode="dev:llm", is_private=1)
                except Exception:
                    pass
                # Utilisation de l'orchestrateur pour le traitement intelligent
                self.run_worker(self._dispatch_ai(user_input), exclusive=False, thread=False)

        async def _handle_at(self, cmd_line: str) -> None:
            """Dispatcher @cmd — forge_commands est l'unique point d'entree."""
            parts = cmd_line.strip().split()
            cmd = parts[0].lower() if parts else ""
            chat = self._chat_log()
            # 1. AT_DISPATCH (reseau/infra)
            from nokido_agent.app.forge_at_dispatch import AT_DISPATCH as _AT

            if cmd in _AT:
                await _AT[cmd](self, cmd_line, parts, cmd)
                return
            # 2. forge_commands (tous les autres @)
            from nokido_agent.app.forge_commands import dispatch_at as _dat

            if await _dat(self, cmd_line):
                return

        async def _reboot_cb(self, confirmed: bool) -> None:
            """Reboot cb.

            Args:
                confirmed: Description.
            """
            if confirmed:
                self._chat_log().write("[dim]⏳ Redémarrage…[/]")
                try:
                    await prefect_manager.run_ssh_command("reboot", sudo=True)
                except Exception as e:
                    self._chat_log().write(f"[red]❌ {e}[/]")
                self.push_screen(NotificationScreen("⚠️ Redémarrage lancé !"))

        async def _select_model(self) -> None:
            """Select model."""
            async with aiohttp.ClientSession() as s:
                try:
                    async with s.get(settings.ollama_tags_url, timeout=5) as resp:
                        data = await resp.json()
                        models = [m["name"] for m in data.get("models", []) if "embed" not in m["name"]]
                except Exception:
                    models = [m for m in [settings.ollama_model_default] if m]
            if not models:
                self._chat_log().write("[red]❌ Aucun modèle disponible[/]")
                return

            def cb(selected: str) -> None:
                """Cb.

                Args:
                    selected: Description.
                """
                if self.current_agent == AgentType.CHAT:
                    self.model_chat = selected
                elif self.current_agent == AgentType.ACTION:
                    self.model_action = selected
                else:
                    self.model_rag = selected
                self._set_agent(self.current_agent)
                self._update_sidebar_title()
                save_last_assignment(self.model_chat, self.model_action, self.model_rag)
                self._chat_log().write(
                    f"[green]✅ Modèle [bold]{selected}[/] → {AGENT_META[self.current_agent]['icon']}[/]"
                )

            self.push_screen(ModelScreen(models, self._current_model(), cb))

        async def _handle_rag(self, args: str) -> None:
            """Handle rag.

            Args:
                args: Description.
            """
            from nokido_agent.app.forge_handlers import _handle_rag as _fh

            await _fh(self, args)

        async def _handle_disco(self, args: str) -> None:
            """@disco <competence> — decouverte et ingestion dans le RAG."""
            try:
                from nokido_agent.app.forge_disco import handle_disco as _hd

                # handle_disco attend cmd_line complet style '@disco <args>'
                await _hd(self, f"@disco {args}")
            except Exception as e:
                self._chat_log().write(f"[red]❌ @disco: {e}[/]")

        async def _handle_proxy(self, args: str) -> None:
            """Handle proxy.

            Args:
                args: Description.
            """
            from nokido_agent.app.forge_handlers import _handle_proxy as _fh

            return await _fh(self, args)

        async def _handle_workflow(self, args: str) -> None:
            """Handle workflow.

            Args:
                args: Description.
            """
            try:
                from nokido_agent.app.forge_hub_handlers import handle_workflow as _hdl

                await _hdl(self, args)
            except Exception as _e:
                self._chat_log().write(f"[red]_handle_workflow: {_e}[/]")

        async def _handle_ci(self, args: str) -> None:
            """Handle ci.

            Args:
                args: Description.
            """
            try:
                from nokido_agent.app.forge_hub_handlers import handle_ci as _hdl

                await _hdl(self, args)
            except Exception as _e:
                self._chat_log().write(f"[red]_handle_ci: {_e}[/]")

        async def _handle_chain(self, args: str) -> None:
            """
            Chaînage d'outils — exécute une séquence de commandes @ en pipeline.

            Syntaxe :
              @chain <cmd1> | <cmd2> | <cmd3>
              @chain <cmd1> | <cmd2 {output}> | <cmd3>

            {output}  → injecté avec le résultat texte de l'étape précédente
            {ip}      → première IP trouvée dans le résultat précédent
            {line:N}  → ligne N du résultat précédent

            Exemples :
              @chain @scan localhost/24 | @switch {ip} admin pass
              @chain @ci run https://github.com/x/repo | @workflow deploy api
              @chain @ids status | @rag save


            Args:
                args (str): Args.
            """
            chat = self._chat_log()
            if not args or args.strip() in ("", "help"):
                chat.write(
                    "[bold #58a6ff]@chain[/] — Pipeline d'outils :\n"
                    "  [bold]@chain[/] [dim]<cmd1> | <cmd2> | <cmd3>[/]\n"
                    "  Variables : [cyan]{output}[/] résultat précédent · "
                    "[cyan]{ip}[/] première IP · [cyan]{line:N}[/] ligne N\n\n"
                    "  [dim]Exemples :[/]\n"
                    "  [dim]@chain @scan localhost/24 | @switch {ip} admin pass[/]\n"
                    "  [dim]@chain @ci run https://github.com/org/repo | @workflow deploy api[/]"
                )
                return

            # Parser les étapes
            raw_steps = [s.strip() for s in args.split("|") if s.strip()]
            if len(raw_steps) < 2:
                chat.write("[yellow]⚠ @chain nécessite au moins 2 étapes séparées par |[/]")
                return

            chat.write(
                f"[bold #58a6ff]⛓ Chain[/] — [dim]{len(raw_steps)} étape(s)[/]\n"
                + "\n".join(f"  [dim]{i + 1}.[/] {s}" for i, s in enumerate(raw_steps))
            )

            import re as _re_chain

            def _extract_ip(text: str) -> str:
                """Extract ip.

                Args:
                    text: Description.
                """
                m = _re_chain.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", text)
                return m.group(1) if m else ""

            def _get_line(text: str, n: int) -> str:
                """Get line.

                Args:
                    text: Description.
                    n: Description.
                """
                lines = text.splitlines()
                return lines[n - 1] if 0 < n <= len(lines) else ""

            def _inject(step: str, prev_output: str) -> str:
                """Injecte les variables dans une étape."""
                step = step.replace("{output}", prev_output.strip()[:500])
                step = step.replace("{ip}", _extract_ip(prev_output))
                # {line:N}
                for m in _re_chain.finditer(r"\{line:(\d+)\}", step):
                    step = step.replace(m.group(0), _get_line(prev_output, int(m.group(1))))
                return step

            # Exécuter chaque étape en capturant la sortie
            prev_output = ""
            chain_ok = True
            for step_i, raw_step in enumerate(raw_steps):
                step_cmd = _inject(raw_step, prev_output)
                chat.write(f"\n[dim]── Étape {step_i + 1}/{len(raw_steps)} : [bold]{step_cmd[:80]}[/][/]")

                # Capturer la sortie en redirigeant temporairement le RichLog
                _captured: list = []
                _orig_write = chat.write

                def _cap_write(msg: str, *a, _c=_captured, _ow=_orig_write, **kw) -> None:
                    """Cap write.

                    Args:
                        msg: Description.
                    """
                    _c.append(str(msg))
                    _ow(msg, *a, **kw)

                chat.write = _cap_write  # type: ignore
                try:
                    if step_cmd.startswith("@"):
                        await self._handle_at(step_cmd)
                    else:
                        # Commande shell directe
                        result = await ssh_manager.run(step_cmd)
                        chat.write(f"[dim]{result[:400]}[/]" if result else "[dim](vide)[/]")
                        _captured.append(result or "")
                    prev_output = "\n".join(_captured)
                    from nokido_agent.app.forge_gui_debug import debug_log as _dl2

                    _dl2(
                        "CHAIN",
                        f"@chain step {step_i + 1}",
                        "OK",
                        {"cmd": step_cmd[:60], "output_len": len(prev_output)},
                    )
                except Exception as _e:
                    chat.write = _orig_write  # type: ignore
                    chat.write(f"[red]❌ Étape {step_i + 1} échouée : {escape(str(_e))}[/]")
                    chain_ok = False
                    break
                finally:
                    chat.write = _orig_write  # type: ignore

            if chain_ok:
                chat.write(f"\n[green]✅ Chain terminé — {len(raw_steps)} étape(s) exécutée(s)[/]")
                # Sauvegarder dans l'historique workflow
                try:
                    prefect_manager._record(f"chain:{raw_steps[0][:30]}", "success", f"{len(raw_steps)} étapes")
                except Exception:
                    pass
            else:
                chat.write("[red]❌ Chain interrompu[/]")

        async def _handle_switch(self, args: str) -> None:
            """Handle switch.

            Args:
                args: Description.
            """
            pass  # stub — handler non implémenté

        async def _index_self_in_rag(self) -> None:
            """
            Auto-indexation : injecte le code source courant dans le RAG
            pour que les agents comprennent leur propre base de code.
            Skip si le code n'a pas change depuis la derniere indexation.
            """
            if not rag_engine:
                return
            try:
                code = version_manager.get_current_code()
                # ── Cache : skip si code inchange ──────────────────────
                import hashlib as _hl

                _h = _hl.md5(code.encode("utf-8", errors="ignore")).hexdigest()
                if getattr(self, "_last_rag_index_hash", None) == _h:
                    return  # Rien de nouveau, on skip
                self._last_rag_index_hash = _h
                # Découpe en sections logiques pour des chunks pertinents
                sections = re.split(r"\n# =+\n# (.+?)\n# =+\n", code)
                if len(sections) <= 1:
                    # Pas de sections → indexe tout le fichier
                    await rag_engine.add_session_message(
                        "self_code", "source", f"[CODE SOURCE v{version_manager.current_version}]\n{code[:6000]}"
                    )
                else:
                    # Indexe section par section
                    for i in range(0, len(sections) - 1, 2):
                        section_name = sections[i + 1] if i + 1 < len(sections) else f"section_{i}"
                        section_code = sections[i + 2] if i + 2 < len(sections) else sections[i]
                        await rag_engine.add_session_message(
                            "self_code", "section", f"[SECTION: {section_name}]\n{section_code[:2000]}"
                        )
                logger.info(f"Auto-indexation RAG : v{version_manager.current_version}")
            except Exception as e:
                logger.warning(f"Auto-indexation RAG échouée : {e}")

        # [→ forge_handlers.py] _propagate_patch

        _AUDIT_MODEL_PREF = [
            # Local spécialistes code (du meilleur au fallback)
            "deepseek-coder-v2",  # 8.9 GB local — deepseek-coder v2 ✨
            "starcoder2:15b",  # 9.1 GB local — code pur
            "glm-4.7-flash",  # 19 GB local — généraliste puissant
            "qwen2.5-coder",  # 4.7 GB
            # Cloud
            "deepseek-v3",
            "qwen3-coder",
            "gpt-oss",
            # Fallbacks
            "starcoder2",
            "deepseek",
        ]

        # Agent B : auditeur léger — erukude dédié multi-agent review ✨
        _AUDITOR_B_PREF = [
            "erukude/multiagent-orchestrator",
            "mistral:7b",
            "mistral:latest",
            "qwen3:8b",
            "qwen2:7b",
        ]
        # Agent C : critique finale — local UNIQUEMENT
        # Les modeles cloud n'ont pas acces au MCP/RAG donc pas au contexte
        # reel du projet -> interdits de proposer des patches applicables.
        _CRITIC_C_PREF = [
            "deepseek-coder-v2",
            "starcoder2:15b",
            "glm-4.7-flash",
            "qwen2.5-coder",
            "starcoder2",
            "deepseek-coder",
        ]
        # Modeles cloud interdits de patch (pas d'acces MCP/RAG/historique)
        _CLOUD_NO_PATCH = [
            "cloud",
            "gpt-oss",
            "deepseek-v3",
            "qwen3-coder",
            "deepseek-v3.1",
            "gpt-4",
            "claude",
        ]

        def _pick_audit_model(self) -> str:
            """Choisit le modèle le plus compétent disponible pour l'audit."""
            return self._pick_model_from(self._AUDIT_MODEL_PREF)

        def _pick_model_from(self, prefs: list) -> str:
            """Choisit le premier modèle dispo parmi une liste de préférences."""
            available = getattr(self, "_available_models", [])
            for pref in prefs:
                for m in available:
                    if pref in m.lower():
                        return m
            return self.model_action or self.model_chat

        # ── Patterns dangereux à détecter statiquement ───────────────────────
        _DANGER_PATTERNS = [
            (r"del\s+sys\.modules(?!\[)", "del sys.modules sans clé → crash"),
            (r"os\.environ\s*=\s*(?![{[])", "os.environ = string/None → crash"),
            (r"sys\.exit\s*\(", "sys.exit() dans un patch"),
            (r"__import__\s*\(", "__import__ dynamique suspect"),
            (r"eval\s*\(", "eval() dangereux"),
            (r"exec\s*\(", "exec() dangereux"),
            (r"open\s*\([^)]*['\"]/etc/", "écriture dans /etc"),
        ]

        async def _validate_suggestion_async(
            self,
            sugg: dict,
        ) -> dict:
            """Validate suggestion async.

            Args:
                sugg: Description.
            """
            from nokido_agent.app.forge_handlers import _validate_suggestion_async as _fh

            return await _fh(self, sugg)

        async def _handle_mem(self, cmd: str) -> object:
            """Handle mem.

            Args:
                cmd: Description.
            """
            from nokido_agent.app.forge_handlers import _handle_mem as _fh

            return await _fh(self, cmd)

        async def _handle_audit(self) -> None:
            """Handle audit."""
            from nokido_agent.app.forge_handlers import _handle_audit as _fh

            await _fh(self)

        async def _handle_estim(self, description: str) -> None:
            """Handle estim.

            Args:
                description: Description.
            """
            from nokido_agent.app.forge_handlers import _handle_estim as _fh

            await _fh(self, description)

        async def _post_loop_safe_check(
            self,
            loop_id: str,
            state: object,  # LoopState
            log_fn: object,
        ) -> None:
            """Post loop safe check.

            Args:
                loop_id: Description.
                state: Description.
                log_fn: Description.
            """
            from nokido_agent.app.forge_loop import post_loop_safe_check as _fh

            await _fh(self, loop_id, state, log_fn)

        async def _handle_loop(self, args: str) -> None:
            """Handle loop.

            Args:
                args: Description.
            """
            try:
                from nokido_agent.app.forge_hub_handlers import handle_loop as _hdl

                await _hdl(self, args)
            except Exception as _e:
                self._chat_log().write(f"[red]_handle_loop: {_e}[/]")

        async def _handle_mode(self, args: str) -> None:
            """Handle mode.

            Args:
                args: Description.
            """
            from nokido_agent.app.forge_handlers import _handle_mode as _fh

            await _fh(self, args)

        async def _handle_role(self, args: str) -> None:
            """Handle role.

            Args:
                args: Description.
            """
            from nokido_agent.app.forge_handlers import _handle_role as _fh

            await _fh(self, args)

        async def _apply_suggestion(self, sugg: dict, _ask_restart: bool = True) -> None:
            # Snapshot RAG avant toute modification
            """Apply suggestion.

            Args:
                sugg: Description.
                _ask_restart: Description.
            """
            try:
                from nokido_agent.app import forge_context as _fcs

                if _fcs.rag_engine and hasattr(_fcs.rag_engine, "_save_embeddings"):
                    _fcs.rag_engine._save_embeddings()
            except Exception:
                pass
            from nokido_agent.app.forge_loop import apply_suggestion as _fh

            _result = await _fh(self, sugg, _ask_restart=_ask_restart)
            # NR check apres application
            if _result:
                try:
                    from tools.mcp_nr import run_fast as _nr_fast

                    _nr = await _nr_fast()
                    if _nr and _nr.get("fail", 0) > 0:
                        self._chat_log().write(f"[red]⚠ NR: {_nr['fail']} FAIL — rollback conseillé[/]")
                    else:
                        self._chat_log().write("[green]✅ NR OK — patch validé[/]")
                except Exception as _nre:
                    self._chat_log().write(f"[dim]NR skip: {_nre}[/]")
            return _result

        def _propose_restart(self, reason: str = "") -> None:
            """Propose restart.

            Args:
                reason: Description.
            """
            chat = self._chat_log()

            def _on_confirm(ok: object) -> None:
                """On confirm.

                Args:
                    ok: Description.
                """
                if ok:
                    chat.write("[dim]🔄 Redémarrage in-place…[/]")
                    import asyncio as _aio

                    async def _do() -> None:
                        """Do."""
                        try:
                            await self.terminal.disconnect()
                        except Exception:
                            pass
                        try:
                            if HAS_ONNX:
                                shutdown_onnx_backend()
                        except Exception:
                            pass
                        await _aio.sleep(0.3)
                        import os as _os, sys as _sys

                        _os.execv(_sys.executable, [_sys.executable] + _sys.argv)

                    self.call_later(lambda: _aio.create_task(_do()))
                else:
                    chat.write("[dim]Redémarrage annulé.[/]")

            self.push_screen(ConfirmScreen(f"Redémarrer Nokido — {reason} ? (y/n)", _on_confirm))

        async def _handle_apply(self, args: str) -> None:
            """Handle apply.

            Args:
                args: Description.
            """
            if not args or not args.isdigit():
                self._chat_log().write("[red]Usage: @apply <numéro>[/]")
                return
            num = int(args)
            sugg = next((s for s in self.last_audit_suggestions if s["num"] == num), None)
            if not sugg:
                self._chat_log().write(f"[red]Aucune suggestion numéro {num} trouvée.[/]")
                return

            # Déléguer à _apply_suggestion (cumulatif + PatchGuard + propagation)
            _ok = await self._apply_suggestion(sugg, _ask_restart=False)
            if _ok:
                self._propose_restart(f"@apply {num} → v{version_manager.current_version}")

        def _extract_commands_from_response(self, text: str) -> list:
            """Extrait les commandes shell d'une réponse LLM."""
            cmds = []
            blocks = re.findall(r"```(?:bash|sh|shell)\s*\n([^`]+?)\n```", text, re.DOTALL | re.IGNORECASE)
            for block in blocks:
                for line in block.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        cmds.append(line)
            if not cmds:
                for m in re.findall(r"^\s*\$\s+(.+)$", text, re.MULTILINE):
                    cmds.append(m.strip())
            return cmds

        async def _dispatch_ai(self, user_input: str) -> None:
            """Dispatch ai.

            Args:
                user_input: Description.
            """
            from nokido_agent.app.forge_dispatch_ai import dispatch_ai as _fh

            await _fh(self, user_input)

        # Tooltips des commandes — affichés dans le tableau d'aide au survol
        COMMAND_TOOLTIPS: dict = {
            "@run CMD": "Exécute CMD via SSH. -sudo pour élévation. Ex: @run df -h",
            "@diag": "Diagnostic système complet: kernel, uptime, RAM, disque",
            "@audit": "Audit IA du code source + indexation RAG. Génère des suggestions numérotées",
            "1, 2… / t": "Applique la suggestion N de l'audit, ou 't' pour toutes les appliquer",
            "@estim <desc>": "Génère une amélioration de code depuis une description langage naturel",
            "@code <desc>": "Génère et teste automatiquement du code Python en sandbox isolée",
            "@test <code>": "Teste du code Python brut directement en sandbox",
            "@sandbox": "Affiche les statistiques d'exécution de la sandbox Python",
            "@loop": "Boucle autonome d'auto-amélioration: start / stop / merge / versions",
            "@role": "Rôles IA: list (modèles+scores) / assign (auto) / detect <texte>",
            "@mode": "Mode multi-agents: autonome / collaboration / comite / set <mode>",
            "@model": "Ouvre le sélecteur de modèle Ollama interactif",
            "@rag": "Base RAG: info / size / list / reindex / del <src> / purge session|all / build",
            "@proxy": "Proxy interne: start / stop / test",
            "@workflow": "Workflows: list / run / add / del / show / deploy / history",
            "@ci": "CI/CD: run / status / lint / test / diff / env",
            "@scan <subnet>": "Découverte réseau nmap+SNMP+mDNS+UPnP+NetBIOS. Ex: @scan localhost/24",
            "@ids start [if]": "IDS temps réel sur interface (défaut eth0). Alertes SSH brute-force, HTTP, DNS",
            "@chain cmd1|cmd2": "Pipeline d'outils. {output}=résultat précédent, {ip}=1ère IP",
            "@switch <ip> <u> <p>": "Récupère la config d'un switch/routeur (SSH/Telnet/SNMP auto)",
            "@switch range <ips…>": "Scan multi-cibles en parallèle",
            "@ids stop": "Arrête le monitoring IDS en cours",
            "@ids status": "Affiche les IPs suspectes détectées depuis le démarrage",
            "@reset": "Annule immédiatement la tâche IA en cours (si bloquée)",
            "@status": "État de l'IA: agent actif, modèle utilisé, occupée ou libre",
        }

        def _show_help(self) -> None:
            """Show help."""
            has_loops = "[green]✓[/]" if HAS_LOOPS else "[red]✗ (loops.py manquant)[/]"
            chat = self._chat_log()
            chat.write(
                f"[bold #58a6ff]══ Aide ⚒ La Forge v{__version__} ══[/]\n\n"
                "[bold]Commandes SSH[/] :\n"
                "  [cyan]@run[/] [-sudo] CMD    Exécute une commande sur le serveur\n"
                "  [cyan]@diag[/]               Diagnostic système complet\n\n"
                "[bold]Auto-amélioration[/] " + has_loops + " :\n"
                "  [cyan]@audit[/]              Audit IA → suggestions numérotées\n"
                "  [cyan]1[/], [cyan]2[/]… / [cyan]t[/]       Applique suggestion N ou toutes\n"
                "  [cyan]@estim[/] <desc>       Génère amélioration depuis description\n"
                "  [cyan]@code[/] <desc>        Génère + teste du code Python\n"
                "  [cyan]@test[/] <code>        Teste du code en sandbox\n"
                "  [cyan]@sandbox[/] status     Stats sandbox\n"
                "  [cyan]@loop[/] start|stop|merge|versions\n\n"
                "[bold]Modes multi-agents[/] :\n"
                "  [cyan]@mode[/] autonome      Agent optimal seul\n"
                "  [cyan]@mode[/] collaboration Agents // + synthèse\n"
                "  [cyan]@mode[/] comite        Propositions + vote juge\n\n"
                "[bold]Rôles IA[/] :\n"
                "  [cyan]@role[/] list|assign|detect <texte>\n\n"
                "[bold]Autres[/] :\n"
                "  [cyan]@scan[/] <subnet>    Découverte réseau (nmap+SNMP+mDNS)\n"
                "  [cyan]@ids[/] start|stop|status [iface]\n"
                "  [cyan]@model[/]  [cyan]@rag[/]  [cyan]@proxy[/]  [cyan]@workflow[/]  [cyan]@ci[/]\n"
                "  [cyan]@reset[/]   Annule la tâche IA\n"
                "  [cyan]@status[/]  État de l'IA\n\n"
                "[dim]↑↓ = autocomplétion · Tab = compléter · Clic droit = coller[/]\n"
                "[dim]Ctrl+T = terminal · Ctrl+B = sidebar · Ctrl+C = copier réponse[/]\n"
            )
            # Tableau de tooltips (simulé en Rich Markup — couleur au survol dans terminal)
            chat.write("[bold]📋 Référence rapide (descriptions détaillées) :[/]")
            for cmd, tip in self.COMMAND_TOOLTIPS.items():
                chat.write(f"  [bold cyan]{cmd:<16}[/]  [dim]{tip}[/]")


# =============================================================================
# FONCTIONS UTILITAIRES (hors classes)
# =============================================================================
async def get_remote_context() -> Dict[str, str]:
    """Get remote context."""
    from nokido_agent.app.forge_handlers import get_remote_context as _fh

    return await _fh()


async def get_models(session: aiohttp.ClientSession) -> List[str]:
    """Get models.

    Args:
        session: Description.
    """
    try:
        async with session.get(settings.ollama_tags_url, timeout=5) as resp:
            data = await resp.json()
            return [m["name"] for m in data.get("models", []) if "embed" not in m["name"]]
    except Exception:
        return []


# =============================================================================
# AUTO-SÉLECTION DES MODÈLES PAR SCORING
# (remplace la StartupScreen manuelle — démarrage direct, sans interaction)
# =============================================================================

LAST_ASSIGNMENT_FILE = _DATA_DIR / "last_assignment.json"


def load_last_assignment() -> dict:
    """Charge la dernière assignation connue — démarrage instantané sans bench."""
    try:
        if LAST_ASSIGNMENT_FILE.exists():
            d = json.loads(LAST_ASSIGNMENT_FILE.read_text(encoding="utf-8"))
            if all(k in d for k in ("chat", "action", "rag")):
                return d
    except Exception:
        pass
    return {}


def save_last_assignment(chat: str, action: str, rag: str) -> None:
    """Persiste l'assignation pour le prochain démarrage."""
    try:
        LAST_ASSIGNMENT_FILE.parent.mkdir(exist_ok=True)
        LAST_ASSIGNMENT_FILE.write_text(
            json.dumps({"chat": chat, "action": action, "rag": rag}, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug(f"save_last_assignment: {e}")


async def auto_select_models(scorer: object, arch: object = None) -> dict:
    """
    Sélectionne automatiquement le meilleur modèle pour chaque agent
    via la banque de scoring.  Retourne {"chat": m, "action": m, "rag": m}.


    Args:
        scorer (object): Scorer.
        arch (object (optional)): Arch.

    Returns:
        dict: Résultat.
    """
    # Si OLLAMA_MODEL_DEFAULT est vide, on ne force rien —
    # l'orchestrateur résoudra via scorer ou le premier modèle Ollama dispo
    fallback = settings.ollama_model_default or ""
    if not globals().get("HAS_SCORING", False) or scorer is None or not scorer.is_ready:
        return {"chat": fallback, "action": fallback, "rag": fallback}
    try:
        _AR = OpsAgentRole
        model_chat = scorer.best_for(_AR.RAG_KNOWLEDGE, arch) or fallback
        model_action = scorer.best_for(_AR.ACTION_EXEC, arch, exclude=[model_chat]) or model_chat
        model_rag = scorer.best_for(_AR.MEMORY, arch, exclude=[model_chat, model_action]) or model_chat
        return {"chat": model_chat, "action": model_action, "rag": model_rag}
    except ImportError:
        # scoring/roles non trouvés — fallback silencieux
        return {"chat": fallback, "action": fallback, "rag": fallback}
    except Exception as e:
        logger.warning(f"auto_select_models: {e}")
        return {"chat": fallback, "action": fallback, "rag": fallback}


# [→ forge_startup.py] _init_smart_router


# =============================================================================
# MAIN
# =============================================================================
from nokido_agent.app.forge_startup import main  # noqa
from nokido_agent.app.forge_startup import _launch_in_new_terminal  # noqa (tombeau)
from nokido_agent.app.forge_startup import _init_onnx_bg  # noqa (tombeau)
from nokido_agent.app.forge_handlers import _validate_patch  # noqa (tombeau)
from nokido_agent.app.forge_compose import compose  # noqa (tombeau corrigé)

# [→ forge_startup.py] _launch_in_new_terminal


if __name__ == "__main__":
    import sys, os
    import multiprocessing as _mp_boot

    _mp_boot.freeze_support()
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    # ── ANTI-DOUBLE-LANCEMENT + NOMMAGE PROCESSUS ────────────────────
    # 1. Lock instance — bloque double lancement
    try:
        from nokido_agent.app.forge_settings import _acquire_instance_lock

        _acquire_instance_lock()  # sys.exit(1) si instance vivante
    except SystemExit:
        raise
    except Exception as _le:
        print(f"[boot] lock warning: {_le}", flush=True)

    # 2. Nommage processus — visible dans le gestionnaire de tâches Windows
    try:
        from nokido_agent.app.forge_version import full_label as _fvfl_boot

        _proc_title = f"LaForge-TUI {_fvfl_boot()}"
    except Exception:
        _proc_title = f"LaForge-TUI v{__version__}"
    try:
        import ctypes as _ct

        _ct.windll.kernel32.SetConsoleTitleW(_proc_title)
    except Exception:
        pass
    try:
        import setproctitle as _spt

        _spt.setproctitle(_proc_title)
    except ImportError:
        pass  # pip install setproctitle pour nommage complet
    try:
        sys.argv[0] = _proc_title
    except Exception:
        pass

    # 3. Écrit le PID dans nokido.lock (vérifiable par le .bat)
    try:
        import pathlib as _pl

        (_pl.Path(__file__).parent.parent / "nokido.lock").write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass

    # ── Mode normal (déjà dans la bonne fenêtre) ─────────────────────────────
    # On n'essaie de relancer dans une nouvelle fenêtre QUE si :
    #   1. Variable d'env LAFORGE_WINDOW=1 absente (évite boucle infinie)
    #   2. Pas de flag --no-window passé explicitement
    #   3. Pas déjà dans un tmux/screen (Textual gère bien ces contextes)
    _already_windowed = os.environ.get("LAFORGE_WINDOW") == "1"
    _no_window_flag = "--no-window" in sys.argv
    _in_multiplexer = bool(os.environ.get("TMUX") or os.environ.get("STY") or os.environ.get("ZELLIJ"))

    # Sur Windows : ne jamais relancer dans une nouvelle fenêtre
    # Le lanceur .bat gère le choix du terminal.
    # --force-window est le seul moyen de forcer une nouvelle fenêtre.
    _force_window = "--force-window" in sys.argv
    _in_win_terminal = sys.platform == "win32" and not _force_window

    if not _already_windowed and not _no_window_flag and not _in_multiplexer and not _in_win_terminal:
        # Tenter de relancer dans une fenêtre dédiée
        os.environ["LAFORGE_WINDOW"] = "1"
        if _launch_in_new_terminal():
            # Succès — minimiser/fermer le terminal courant proprement
            print("⚒  La Forge lancée dans une nouvelle fenêtre.")
            try:
                # Tenter de minimiser la fenêtre courante (Linux X11)
                import subprocess as _sp2

                _wid = _sp2.check_output(["xdotool", "getactivewindow"], stderr=_sp2.DEVNULL).strip()
                _sp2.Popen(["xdotool", "windowminimize", _wid], stdout=_sp2.DEVNULL, stderr=_sp2.DEVNULL)
            except Exception:
                pass
            sys.exit(0)
        # Relancement échoué → continuer normalement dans cette fenêtre
        print("⚒  Lancement direct (aucun émulateur terminal détecté).")

    # ── Mode --test-boot : headless sans Textual ────────────────────────
    if "--test-boot" in sys.argv:
        import json as _json, importlib as _il

        _result = {"canary": {"ok": True, "errors": []}, "function_tests": {}}

        _checks = [
            ("forge_handlers", ["_handle_rag", "_handle_nr", "classify_with_cmd"]),
            ("forge_hub_handlers", ["handle_ci", "handle_workflow"]),
            ("forge_at_dispatch", ["AT_DISPATCH"]),
            ("forge_ollama", ["ollama_call", "ollama_stream"]),
            ("forge_rag_warmup", ["rag_self_warmup"]),
            ("forge_startup", ["main", "_read_env_file"]),
            ("forge_compose", ["compose"]),
            ("forge_capabilities", ["get_caps"]),
        ]
        for _mod, _fns in _checks:
            try:
                _m = _il.import_module(_mod)
                for _fn in _fns:
                    if not hasattr(_m, _fn):
                        _result["canary"]["errors"].append(f"{_mod}.{_fn} manquant")
                        _result["canary"]["ok"] = False
            except Exception as _ce:
                _result["canary"]["errors"].append(f"import {_mod}: {_ce}")
                _result["canary"]["ok"] = False

        try:
            from nokido_agent.app.forge_settings import get_settings as _gs, create_settings as _cs

            s = _gs() or _cs()
            _result["function_tests"]["get_settings"] = {
                "ok": s is not None and hasattr(s, "ollama_model_default"),
                "detail": type(s).__name__ + " ollama=" + str(getattr(s, "ollama_model_default", "MISSING")),
            }
        except Exception as _e:
            _result["function_tests"]["get_settings"] = {"ok": False, "error": str(_e)}

        try:
            from nokido_agent.app.forge_capabilities import get_caps as _gc

            c = _gc()
            _result["function_tests"]["get_caps"] = {"ok": c is not None, "detail": f"HAS_OLLAMA={c.HAS_OLLAMA}"}
        except Exception as _e:
            _result["function_tests"]["get_caps"] = {"ok": False, "error": str(_e)}

        try:
            from nokido_agent.app.forge_context import make_test_context as _mtc

            ctx = _mtc()
            _result["function_tests"]["make_test_context"] = {"ok": ctx is not None, "detail": f"ring={ctx.ring}"}
        except Exception as _e:
            _result["function_tests"]["make_test_context"] = {"ok": False, "error": str(_e)}
        try:
            import textual as _tx

            _result["function_tests"]["textual"] = {"ok": True, "detail": f"v{_tx.__version__}"}
        except Exception as _e:
            _result["function_tests"]["textual"] = {"ok": False, "error": "pip install textual"}
        try:
            from nokido_agent.app.forge_startup import main as _fmain

            _result["function_tests"]["forge_startup.main"] = {"ok": callable(_fmain), "detail": "callable"}
        except Exception as _e:
            _result["function_tests"]["forge_startup.main"] = {"ok": False, "error": str(_e)}

        _out = Path(__file__).resolve().parent.parent / "sandbox" / "boot_test_result.json"
        _out.parent.mkdir(exist_ok=True)
        _out.write_text(_json.dumps(_result, indent=2), encoding="utf-8")
        _ok = _result["canary"]["ok"] and all(v.get("ok") for v in _result["function_tests"].values())
        print("[TEST-BOOT]", "OK" if _ok else "FAILED")
        for _e in _result["canary"]["errors"]:
            print("  CANARI:", _e)
        for _k, _v in _result["function_tests"].items():
            print(f"  {'OK' if _v.get('ok') else 'FAIL'} {_k}: {_v.get('detail', _v.get('error', ''))}")
        sys.exit(0 if _ok else 1)

    try:
        asyncio.run(main(_DevOpsApp=DevOpsApp if HAS_TEXTUAL else None))
    except KeyboardInterrupt:
        print("\nInterrompu.")
    except Exception as e:
        print(f"Erreur fatale : {e}")
        import traceback

        traceback.print_exc()

# [_purge_pycache → forge_startup.py]


async def get_remote_context() -> Dict[str, str]:  # noqa: F811
    """Récupère des informations système sur la machine distante via SSH.

    - Les commandes sont exécutées en parallèle grâce à ``asyncio.gather``.
    - Chaque résultat est associé à son nom de clé (ex. ``hostname``).
    - En cas d’échec d’une commande, la valeur correspondante est remplie
      avec le texte d’erreur, ce qui évite que l’appel échoue complètement.


    Returns:
        Dict[str, str]: Résultat.
    """
    cmds: Dict[str, str] = {
        "hostname": "hostname",
        "kernel": "uname -r",
        "uptime": "uptime",
        "memory": "free -h",
        "disk": "df -h /",
    }

    async def _run_and_capture(key: str, command: str) -> Tuple[str, str]:
        """Run and capture.

        Args:
            key: Description.
            command: Description.
        """
        try:
            result = await run_ssh(command)  # type: ignore[arg-type] – fonction fournie ailleurs
            return key, result.strip()
        except Exception as exc:  # pragma: no cover – capture générique pour éviter la rupture du gather
            logging.getLogger(__name__).error("Erreur lors de l’exécution SSH de %s : %s", command, exc)
            return key, f"<error: {exc}>"

    # Lancer toutes les commandes en parallèle
    tasks = [_run_and_capture(key, cmd) for key, cmd in cmds.items()]
    results = await asyncio.gather(*tasks)

    # Convertir la liste de tuples en dictionnaire
    context: Dict[str, str] = {key: value for key, value in results}
    return context


from contextlib import AbstractContextManager
from typing import Any, Optional, Tuple


class _silent(AbstractContextManager):
    """
    Context manager qui supprime temporairement toute sortie sur ``stdout``,
    ``stderr`` ainsi que les warnings.  Il est compatible Windows/Linux/macOS
    et restaure correctement les flux même en cas d’exception.
    """

    def __enter__(self) -> "_silent":
        """Enter."""
        import sys
        import io
        import warnings as _warnings

        self._old_out: Any = sys.stdout
        self._old_err: Any = sys.stderr
        self._buffer = io.StringIO()
        sys.stdout = self._buffer
        sys.stderr = self._buffer

        self._warnings_ctx = _warnings.catch_warnings()
        self._warnings_ctx.__enter__()
        _warnings.simplefilter("ignore")
        return self

    def __exit__(
        self, exc_type: Optional[type] = None, exc: Optional[BaseException] = None, tb: Optional[Any] = None
    ) -> Optional[bool]:
        """Exit.

        Args:
            exc_type: Description.
            exc: Description.
            tb: Description.
        """
        import sys

        # Restauration des flux – on ignore les erreurs potentielles pour ne
        # jamais laisser le processus sans ``stdout``/``stderr``.
        try:
            sys.stdout = self._old_out
        finally:
            try:
                sys.stderr = self._old_err
            finally:
                # Toujours quitter le contexte warnings, même si une exception
                # s’est produite dans le bloc ``with``.
                self._warnings_ctx.__exit__(exc_type, exc, tb)

        # Ne pas supprimer l’exception – on la laisse se propager.
        return None
