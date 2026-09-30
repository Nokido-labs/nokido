from __future__ import annotations

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_165156_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns/Raises
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__  = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
import asyncio
import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ── asyncssh (optionnel) ─────────────────────────────────────────────────────
try:
    import asyncssh
except ImportError:
    asyncssh = None

# ── Prefect (optionnel) ──────────────────────────────────────────────────────
try:
    from prefect import flow, task
    from prefect.task_runners import ConcurrentTaskRunner
    from prefect.client.orchestration import get_client

    HAS_PREFECT = True
except ImportError:
    HAS_PREFECT = False

    def flow(*a, **kw) -> object:
        """Flow.
        """
        def dec(f: object) -> object:
            """Dec.
            """
            return f

        return dec

    def task(*a, **kw) -> object:
        """Task.
        """
        def dec(f: object) -> object:
            """Dec.
            """
            return f

        return dec

    class ConcurrentTaskRunner:
        """ConcurrentTaskRunner class."""
        def __init__(self, **kw) -> None:
            """Initialise l'instance.
            """
            pass

    def get_client() -> None:
        """Get client.
        """
        return None


# ── Chemins Nokido ─────────────────────────────────────────────────────────
_ROOT_P = __import__("pathlib").Path(__file__).resolve().parent.parent
_ROOT_DIR = _ROOT_P
_APP_DIR = _ROOT_P / "app"
_DATA_DIR = _ROOT_P / "data"
_LOGS_DIR = _ROOT_P / "logs"
try:
    import aiohttp
except ImportError:
    aiohttp = None

_DATA_DIR.mkdir(exist_ok=True)
_LOGS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("Nokido.Core.Models")


class _JSONLHandler(logging.Handler):
    """Handler qui crit chaque message en JSONL (une ligne JSON par entre)."""

    def __init__(self, path: str) -> None:
        """Initialise l'instance.
        """
        super().__init__()
        self._fh = open(path, "w", encoding="utf-8", buffering=4096)

    def emit(self, record: logging.LogRecord) -> None:
        """Emit.
        """
        try:
            entry = {
                "ts": record.created,
                "time": self.format(record).split(" [")[0] if hasattr(record, "created") else "",
                "level": record.levelname,
                "name": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info and record.exc_info[0]:
                entry["exc"] = logging.Formatter().formatException(record.exc_info)
            self._fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def close(self) -> None:
        """Close.
        """
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass
        super().close()


class AgentType(Enum):
    """AgentType class."""
    CHAT = "chat"
    ACTION = "action"
    RAG = "rag"


class TaskPriority(Enum):
    """TaskPriority class."""
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    BACKGROUND = 4


class TTLCache:
    """TTLCache class."""
    def __init__(self, ttl: int = 60, maxsize: int = 100):
        """Initialise l'instance.
        """
        self.ttl = ttl
        self.cache = OrderedDict()
        self.maxsize = maxsize

    def get(self, key: str) -> None:
        """Get.
        """
        if key in self.cache:
            value, ts = self.cache[key]
            if time.time() - ts < self.ttl:
                self.cache.move_to_end(key)
                return value
            del self.cache[key]
        return None

    def set(self, key: str, value: object) -> None:
        """Set.
        """
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = (value, time.time())
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)


class ErrorManager:
    """Gestion centralisée des erreurs avec retry et logging."""

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        """Initialise l'instance.
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.error_stats: Dict[str, int] = {}

    async def execute_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """Exécute une fonction avec mécanisme de retry."""
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                return result
            except Exception as e:
                last_error = e
                logger.warning(f"Tentative {attempt + 1}/{self.max_retries} échouée: {e}")
                if attempt < self.max_retries:
                    delay = self.base_delay * (2**attempt)
                    await asyncio.sleep(min(delay, 10))
                else:
                    break
        error_type = type(last_error).__name__
        self.error_stats[error_type] = self.error_stats.get(error_type, 0) + 1
        logger.error(f"Échec après {self.max_retries + 1} tentatives: {last_error}")
        raise last_error


class SSHManager:
    """Gère la connexion SSH et l'exécution de commandes avec retry."""

    def __init__(self) -> None:
        """Initialise l'instance.
        """
        self._connection = None
        self._sudo_available = False
        self._privilege_method = None
        self._os_type = "unknown"
        self._lock = asyncio.Lock()
        self.error_manager = ErrorManager(max_retries=2, base_delay=2.0)

    async def connect(self) -> None:
        """Connect.
        """
        from forge_app_context import get_settings as _gset

        settings = _gset()
        async with self._lock:
            if self._connection and not self._connection.is_closed():
                return
            self._connection = await asyncssh.connect(
                settings.ssh_host,
                port=settings.ssh_port,
                username=settings.ssh_user,
                client_keys=[str(settings.private_key_path)],
                known_hosts=None,
            )
            try:
                r = await self._connection.run("uname -s 2>/dev/null || echo UNKNOWN")
                _os = r.stdout.strip().lower()
                if "linux" in _os:
                    self._os_type = "linux"
                elif "darwin" in _os:
                    self._os_type = "macos"
                elif "freebsd" in _os or "openbsd" in _os:
                    self._os_type = "freebsd"
                elif _os == "unknown":
                    r2 = await self._connection.run("whoami 2>nul")
                    if r2.exit_status == 0 and chr(92) in r2.stdout:
                        self._os_type = "windows"
            except Exception:
                pass
            self._sudo_available = False
            self._privilege_method = None
            try:
                if self._os_type == "windows":
                    r = await self._connection.run('whoami /groups 2>nul | findstr /i "S-1-16-12288"')
                    if r.exit_status == 0:
                        self._sudo_available = True
                        self._privilege_method = "admin"
                else:
                    r = await self._connection.run("sudo -n true 2>/dev/null")
                    if r.exit_status == 0:
                        self._sudo_available = True
                        self._privilege_method = "sudo"
                    else:
                        r = await self._connection.run("doas true 2>/dev/null")
                        if r.exit_status == 0:
                            self._sudo_available = True
                            self._privilege_method = "doas"
            except Exception:
                self._sudo_available = False
            logger.info(f"SSH connecte (os={self._os_type} privilege={self._privilege_method or 'none'})")

    @property
    def os_type(self) -> object:
        """Os type.
        """
        return self._os_type

    @property
    def privilege_method(self) -> bool:
        """Privilege method.
        """
        return self._privilege_method or "none"

    async def run(self, command: str, sudo: bool = False, timeout: int = 30) -> Tuple[str, str, int]:
        """Run.
        """
        await self.connect()
        if sudo and self._sudo_available:
            if self._privilege_method == "doas":
                full_cmd = f"doas {command}"
            elif self._privilege_method == "admin":
                full_cmd = command
            else:
                full_cmd = f"sudo {command}"
        else:
            full_cmd = command
        async with self._lock:
            return await self.error_manager.execute_with_retry(self._execute_command, full_cmd, timeout)

    async def _execute_command(self, full_cmd: str, timeout: int) -> Tuple[str, str, int]:
        """Execute command.
        """
        try:
            result = await asyncio.wait_for(self._connection.run(full_cmd), timeout=timeout)
            return result.stdout, result.stderr, result.exit_status
        except asyncio.TimeoutError:
            return "", f"Timeout ({timeout}s)", -1
        except Exception as e:
            return "", f"[SSH] {e}", -1

    async def close(self) -> None:
        """Close.
        """
        async with self._lock:
            if self._connection and not self._connection.is_closed():
                self._connection.close()
                await self._connection.wait_closed()
                self._connection = None

    @property
    def sudo_available(self) -> bool:
        """Sudo available.
        """
        return self._sudo_available


class SkillEntry:
    """Entrée dans le registre de compétences de l'AgenticEngine.

    Pipeline ML :
      waiting → searching → learning → mastered → verified
                                           ↑             ↑
                                      score≥0.7    3 tâches OK

    Anti-pourrissement :
      unverified=True tant que < VERIFY_NEEDED succès distincts
      fail_streak≥3 → régression mastered→learning
      vitality_score décroît exponentiellement selon MEMORY_LAYERS[layer].lambda
    """

    name: str
    status: str = "waiting"  # waiting|searching|learning|mastered|verified|vulnerable
    layer: str = "disco"  # core|library|disco
    score: float = 0.0  # score RAG courant (0→1)
    vitality_score: float = 1.0  # V(t) = score_initial · e^(-λ·Δt)
    initial_score: float = 0.0  # S_initial pour V(t)
    uses: int = 0  # nb utilisations réussies distinctes
    errors: int = 0  # nb erreurs système
    fail_streak: int = 0  # erreurs consécutives (reset à succès)
    unverified: bool = True  # True jusqu'à VERIFY_NEEDED succès
    ingested_at: str = ""  # ISO8601, positionné à la création
    last_task: str = ""
    tasks_ok: List[str] = field(default_factory=list)
    confidence_history: List[float] = field(default_factory=list)  # historique scores


@dataclass
class SupervisorAnalysis:
    """Résultat de l'analyse par le superviseur."""

    needs_rag: bool = False
    needs_action: bool = False
    needs_dialogue: bool = False
    confidence: float = 0.5
    reasoning: str = ""


@dataclass
class ActionResult:
    """Résultat d'une exécution d'action."""

    command: str
    output: str
    success: bool
    execution_time: float


@dataclass
class RoutingPlan:
    """Plan de routage déterminé par le superviseur."""

    steps: List[Dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""


class OrchestratorState:
    """État partagé pour l'orchestrateur."""

    def __init__(self) -> None:
        """Initialise l'instance.
        """
        self.last_command: Optional[str] = None
        self.last_action_result: Optional[str] = None
        self.current_session: Optional[str] = None


class OrchestratorManager:
    """
    Gère l'orchestration intelligente entre tous les agents.

    Singleton : une seule instance est créée au démarrage de l'app,
    partagée entre toutes les interactions. Cela préserve :
      - l'historique de conversation (context_window)
      - le cache RAG
      - les résultats d'action précédents

    IMPORTANT : ne jamais appeler _set_agent depuis ici.
    Le routage interne (rag/action/dialogue) est transparent pour l'UI.
    L'agent UI (chat/action/rag) est géré exclusivement par l'utilisateur
    via Ctrl+1/2/3 ou les boutons.
    """

    def __init__(self) -> None:
        """Initialise l'instance.
        """
        self.state = OrchestratorState()
        self.agents = {
            "supervisor": SupervisorAgent(),
            "rag": RAGAgent(),
            "action": ActionAgent(),
            "dialogue": DialogueAgent(),
        }
        # Fenêtre de contexte de conversation (rôle/contenu)
        self._context_window: List[Dict] = []
        self._max_context = 20  # messages conservés

    def _push_context(self, role: str, content: str) -> None:
        """Push context.
        """
        self._context_window.append({"role": role, "content": content})
        if len(self._context_window) > self._max_context:
            self._context_window.pop(0)

    async def process_user_input(
        self,
        user_input: str,
        raw_input: Optional[str] = None,
    ) -> Tuple[str, str, Optional[str]]:
        """Process user input.
        """
        from forge_handlers import process_user_input as _fh

        return await _fh(
            self,
            _push_context=self._push_context,
            _execute_routing_plan=self._execute_routing_plan,
            _enrich_rag=self._enrich_rag,
            agents=self.agents,
        )

    # ── Modes de collaboration multi-agents ───────────────────────────────────

    async def run_autonome(self, task: str) -> Tuple[str, str]:
        """Mode autonome : le meilleur agent sélectionné par scoring répond seul."""
        return await self.process_user_input(task)

    async def run_collaboration(self, task: str) -> Tuple[str, str]:
        """Run collaboration.
        """
        from forge_handlers import run_collaboration as _fh

        return await _fh(self)

    async def run_comite(self, task: str) -> Tuple[str, str]:
        """Run comite.
        """
        from forge_handlers import run_comite as _fh

        return await _fh(self)

    async def _execute_routing_plan(
        self,
        plan: RoutingPlan,
        user_input: str,
        rag_docs: Optional[List] = None,
        cmd_to_inject: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Execute routing plan.
        """
        from forge_handlers import _execute_routing_plan as _fh

        return await _fh(
            self,
            _build_context=self._build_context,
            _context_window=self._context_window,
            state=self.state,
            agents=self.agents,
        )

    def _build_context(self, results: Dict, user_input: str) -> Dict:
        """Build context.
        """
        ctx = {"user_input": user_input}
        if "rag" in results:
            ctx["rag_context"] = results["rag"]
        if "action" in results:
            ctx["action_result"] = results["action"]
        return ctx

    async def _enrich_rag(self, user_input: str, response: str) -> None:
        """Enrichit le RAG après chaque échange — toujours, pas seulement après action."""
        from forge_app_context import get_rag as _gr

        rag_engine = getattr(self, "rag_engine", None) or _gr()
        if not rag_engine:
            return
        try:
            doc = (
                f"[Échange {datetime.now().strftime('%H:%M:%S')}]\n"
                f"Utilisateur : {user_input}\n"
                f"Réponse     : {response[:600]}\n"
            )
            if self.state.last_command:
                doc += f"Commande exécutée : {self.state.last_command}\n"
                doc += f"Résultat          : {(self.state.last_action_result or '')[:300]}\n"
            await rag_engine.add_session_message("exchange_history", "system", doc)
            logger.debug("RAG enrichi avec échange")
        except Exception as e:
            logger.warning(f"Enrichissement RAG : {e}")

    async def reset_context(self) -> None:
        """Vide la fenêtre de conversation (nouvelle session)."""
        self._context_window.clear()
        self.state = OrchestratorState()


class SessionContext:
    """Gère l'historique d'une conversation et l'indexation RAG."""

    def __init__(self, session_name: str, max_tokens: int = 3000):
        """Initialise l'instance.
        """
        self.name = session_name
        self.max_tokens = max_tokens
        self.messages: List[Dict] = []
        self.summary: Optional[str] = None
        self.current_tokens = 0
        self.filename = _DATA_DIR / f"session_{session_name}.json"
        self._load()
        from forge_app_context import get_rag as _gr

        rag_engine = _gr()
        if rag_engine:
            rag_engine.session_ctxs[session_name] = self

    def _load(self) -> None:
        """Load.
        """
        if self.filename.exists():
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.messages = data.get("messages", [])
                    self.summary = data.get("summary")
                    self.current_tokens = sum(len(m["content"]) // 4 for m in self.messages)
            except Exception as e:
                logger.error(f"Erreur chargement session {self.name}: {e}")

    def save(self) -> None:
        """Save.
        """
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(
                    {"messages": self.messages, "summary": self.summary, "saved_at": datetime.now().isoformat()},
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception as e:
            logger.error(f"Erreur sauvegarde session {self.name}: {e}")

    def add(self, role: str, content: str) -> None:
        """Add.
        """
        from forge_app_context import get_rag as _gr

        rag_engine = getattr(self, "rag_engine", None) or _gr()
        tokens = len(content) // 4
        self.messages.append({"role": role, "content": content, "tokens": tokens})
        self.current_tokens += tokens
        while self.current_tokens > self.max_tokens and len(self.messages) > 1:
            removed = self.messages.pop(0)
            self.current_tokens -= removed["tokens"]
        self.save()
        if rag_engine:
            asyncio.create_task(rag_engine.add_session_message(self.name, role, content))

    def get_context(self) -> List[Dict]:
        """Get context.
        """
        ctx = []
        if self.summary:
            ctx.append({"role": "system", "content": f"Résumé: {self.summary}"})
        ctx.extend(self.messages)
        return ctx

    def unregister(self) -> None:
        """Unregister.
        """
        self.save()
        if rag_engine and self.name in rag_engine.session_ctxs:
            del rag_engine.session_ctxs[self.name]


class PrefectManager:
    """
    Orchestrateur de workflows et pipelines CI/CD via SSH.
    Prefect v2 optionnel — fonctionne aussi en mode SSH pur.
    """

    def __init__(self, settings: object = None) -> None:
        """Initialise l'instance.
        """
        _max = getattr(settings, "max_concurrent_tasks", 4) if settings else 4
        self.task_runner = ConcurrentTaskRunner(max_workers=_max)
        self.logger = logging.getLogger("PrefectManager")
        self.client = None
        self.slack_webhook = getattr(settings, "slack_webhook_url", "") if settings else ""
        # ── Registre des pipelines en cours ──────────────────────────────────
        self._running_pipelines: Dict[str, asyncio.Task] = {}
        self._pipeline_history: List[Dict] = []  # max 50 entrées
        # ── Registre des workflows définis localement ─────────────────────────
        self._custom_workflows: Dict[str, List[str]] = {}  # nom → liste de commandes

    async def start(self) -> None:
        """Start.
        """
        if not HAS_PREFECT:
            self.logger.warning("Prefect non disponible — mode SSH pur")
            return
        try:
            self.client = get_client()
            self.logger.info("Prefect client initialisé")
        except Exception as e:
            self.logger.warning(f"Prefect client non disponible: {e}")
            self.client = None

    async def stop(self) -> None:
        """Stop.
        """
        # Annuler les tâches en cours
        for name, task in list(self._running_pipelines.items()):
            if not task.done():
                task.cancel()
        self._running_pipelines.clear()
        if self.client:
            try:
                if hasattr(self.client, "close"):
                    await self.client.close()
                elif hasattr(self.client, "__aexit__"):
                    await self.client.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"PrefectManager.stop: {e}")
            finally:
                self.client = None

    async def run_ssh_command(self, command: str, sudo: bool = False) -> str:
        """Run ssh command.
        """
        failure_stats["total_commands"] += 1
        out, err, status = await run_ssh(command, sudo)
        if status != 0:
            failure_stats["failed_commands"] += 1
            self._send_notification(f"Commande échouée: {command}\nErreur: {err}")
            raise RuntimeError(f"Commande échouée (exit {status}): {err}")
        return out

    def _send_notification(self, message: str) -> None:
        """Send notification.
        """
        if not self.slack_webhook:
            return
        try:
            import urllib.request

            payload = json.dumps({"text": message}).encode()
            req = urllib.request.Request(
                self.slack_webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            self.logger.warning(f"Notification Slack échouée: {e}")

    def _record(self, name: str, status: str, detail: str = "") -> None:
        """Enregistre dans l'historique des pipelines."""
        import datetime

        entry = {
            "name": name,
            "status": status,
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "detail": detail[:200],
        }
        self._pipeline_history.append(entry)
        if len(self._pipeline_history) > 50:
            self._pipeline_history.pop(0)

    # ── CI/CD ─────────────────────────────────────────────────────────────────

    async def run_ci_pipeline(
        self,
        repo_url: str,
        branch: str = "main",
        workdir: str = "/tmp/ci-repo",
        on_step: Optional[callable] = None,
    ) -> str:
        """Run ci pipeline.
        """
        from forge_ssh import run_ci_pipeline as _fh

        return await _fh(self, repo_url, branch, workdir, on_step)

    async def deploy(
        self,
        service: str,
        strategy: str = "restart",
        on_step: Optional[callable] = None,
    ) -> str:
        """Deploy.
        """
        from forge_handlers import deploy as _fh

        return await _fh(self)

    async def run_workflow(
        self,
        name: str,
        steps: Optional[List[str]] = None,
        on_step: Optional[callable] = None,
    ) -> str:
        """
        Exécute un workflow nommé (prédéfini ou custom).
        Si steps est fourni, crée/écrase le workflow nommé.
        """
        results = []

        def _step(icon, msg):
            """Step.
            """
            return results.append(f"{icon} {msg}") or (on_step and on_step(icon, msg))

        # Enregistrer si steps fournis
        if steps:
            self._custom_workflows[name] = steps
            _step("📝", f"Workflow '{name}' enregistré ({len(steps)} étapes)")
            return "\n".join(results)

        # Chercher le workflow
        cmds = self._custom_workflows.get(name)
        if not cmds:
            return f"❌ Workflow '{name}' inconnu. Crée-le avec @workflow add {name} <cmd1> | <cmd2> …"

        _step("▶", f"Workflow '{name}' — {len(cmds)} étapes")
        ok_count = 0
        for i, cmd in enumerate(cmds, 1):
            _step(f"[{i}/{len(cmds)}]", cmd[:60])
            try:
                out = await self.run_ssh_command(cmd)
                results.append(f"  → {out[:200]}")
                ok_count += 1
            except RuntimeError as e:
                _step("❌", str(e)[:150])
                break

        _step("✅" if ok_count == len(cmds) else "⚠", f"{ok_count}/{len(cmds)} étapes réussies")
        self._record(name, "SUCCESS" if ok_count == len(cmds) else "PARTIAL")
        return "\n".join(results)

    def workflow_list(self) -> List[str]:
        """Liste les workflows définis."""
        return list(self._custom_workflows.keys())

    def pipeline_history(self, limit: int = 10) -> List[Dict]:
        """Pipeline history.
        """
        return self._pipeline_history[-limit:]


class ForgeSaveOrchestrator:
    """
    Gestionnaire de sauvegardes atomiques pour La Forge.

    Garanties :
    - Un seul staging actif à la fois (_staging_lock)
    - Checkpoint créé AVANT toute modification
    - Rollback automatique sur exception
    - Rotation GFS des backups (10 max, hebdo/mensuel conservés)
    - Résumé de chaque opération persisté dans backups/history.jsonl
    """

    MAX_BACKUPS = 10
    KEEP_WEEKLY = 4  # garder 4 checkpoints hebdomadaires
    KEEP_MONTHLY = 3  # garder 3 checkpoints mensuels

    def __init__(self) -> None:
        """Initialise l'instance.
        """
        _base = Path(__file__).resolve().parent
        self.staging_dir = _base / "staging"
        self.backup_dir = _base / "backups"
        self.history_file = self.backup_dir / "history.jsonl"
        self.staging_dir.mkdir(exist_ok=True)
        self.backup_dir.mkdir(exist_ok=True)
        self._staging_lock = asyncio.Lock()
        self._last_backup: Optional[Path] = None

    # ── Checkpoint ────────────────────────────────────────────────────────────
    def create_checkpoint(self, label: str = "") -> Path:
        """
        Copie atomique de workspace/ → backups/backup_<ts>_<label>/
        Retourne le chemin du backup créé.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"backup_{ts}" + (f"_{label[:20]}" if label else "")
        dst = self.backup_dir / name
        src_ws = _ROOT_DIR / "workspace"
        if src_ws.exists():
            shutil.copytree(src_ws, dst)
        else:
            dst.mkdir(exist_ok=True)
        self._last_backup = dst
        self._append_history("checkpoint", str(dst), label)
        logger.info(f"[SaveOrch] Checkpoint créé : {dst.name}")
        return dst

    # ── Staging ───────────────────────────────────────────────────────────────
    def write_to_staging(self, filename: str, content: str) -> Path:
        """Écrit un fichier dans staging/ (zone isolée)."""
        path = self.staging_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    def clear_staging(self) -> None:
        """Vide staging/ (après commit ou rollback)."""
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir)
            self.staging_dir.mkdir(exist_ok=True)
        logger.debug("[SaveOrch] staging/ vidé")

    # ── Commit → production ───────────────────────────────────────────────────
    def commit_to_prod(self, version_manager: "VersionManager") -> bool:
        """
        Transfère le fichier validé de staging/ vers workspace/ via VersionManager.
        Ne touche jamais directement workspace/ — délègue à version_manager.prepare_patch.
        """
        py_files = list(self.staging_dir.glob("*.py"))
        if not py_files:
            logger.warning("[SaveOrch] commit_to_prod : staging/ vide")
            return False
        latest = max(py_files, key=lambda p: p.stat().st_mtime)
        dst = _ROOT_DIR / "workspace" / latest.name
        shutil.copy2(latest, dst)
        version_manager.work_path = dst
        self._append_history("commit", str(dst), latest.name)
        logger.info(f"[SaveOrch] Commit staging → workspace : {latest.name}")
        self.clear_staging()
        return True

    # ── Rollback ──────────────────────────────────────────────────────────────
    async def rollback(self, backup_path: Optional[Path] = None) -> bool:
        """Rollback.
        """
        from forge_handlers import rollback as _fh

        return await _fh(
            self,
            _last_backup=self._last_backup,
            backup_dir=self.backup_dir,
            _append_history=self._append_history,
            clear_staging=self.clear_staging,
        )

    # ── Rotation GFS des backups ──────────────────────────────────────────────
    async def rotate_backups(self) -> object:
        """Rotate backups.
        """
        from forge_handlers import rotate_backups as _fh

        return await _fh(
            self,
            backup_dir=self.backup_dir,
            KEEP_WEEKLY=self.KEEP_WEEKLY,
            MAX_BACKUPS=self.MAX_BACKUPS,
            KEEP_MONTHLY=self.KEEP_MONTHLY,
        )

    # ── Flux complet : evolution_loop ─────────────────────────────────────────
    # evolution_loop — voir forge_versioning.py (version complète)

    # ── Historique persistant ─────────────────────────────────────────────────
    def _append_history(self, op: str, path: str, detail: str) -> None:
        """Append history.
        """
        try:
            entry = json.dumps(
                {
                    "ts": datetime.now().isoformat(),
                    "op": op,
                    "path": path,
                    "detail": detail,
                }
            )
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass

    def history_tail(self, n: int = 20) -> List[Dict]:
        """Retourne les N dernières opérations."""
        if not self.history_file.exists():
            return []
        try:
            lines = self.history_file.read_text(encoding="utf-8").strip().split("\n")
            return [json.loads(l) for l in lines[-n:] if l]
        except Exception:
            return []


class VersionManager:
    """
    Gère les versions du code source.

    Structure :
      workspace/          ← versions de travail (tronc principal)
        Nokido_v1.0.py
        Nokido_v1.1.py
      versions/           ← archives horodatées
      loop_trunk/         ← TRONC SÉPARÉ pour les séquences @loop
        loop_<id>/
          Nokido_v1.0.py  ← point de départ du loop
          Nokido_v1.1.py  ← B1 patch 1
          Nokido_v1.2.py  ← B1 patch 2  …
      .patch_backlog.json ← journal de toutes les opérations
      .improvement_memory.json ← mémoire de l'amélioration (loops.py)
    """

    def __init__(self) -> None:
        """Initialise l'instance.
        """
        # Toujours pointer vers Nokido.py, peu importe quel fichier instancie VersionManager
        # (version_manager.py ou forge_runtime.py peuvent aussi l'instancier)
        _self_path = Path(__file__).resolve()
        _app_dir = _self_path.parent
        _nokido = _app_dir / "Nokido.py"
        self.source_path = _nokido if _nokido.exists() else _self_path
        _root = _app_dir.parent  # LaForge/
        self.workspace_dir = _root / "workspace"
        self.versions_dir = _root / "versions"
        self.loop_dir = _root / "loop_trunk"
        self.workspace_dir.mkdir(exist_ok=True)
        self.versions_dir.mkdir(exist_ok=True)
        self.loop_dir.mkdir(exist_ok=True)
        self._protect_source()
        self.work_path = self._get_current_work_file()
        # Tronc loop courant (None si pas de loop en cours)
        self._loop_id: Optional[str] = None
        self._loop_trunk: Optional[Path] = None
        # Index des versions connues {version_str → Path}
        self._version_index: Dict[str, Path] = {}
        self._rebuild_version_index()

    # ── Protection source ──────────────────────────────────────────────────────
    def _protect_source(self) -> None:
        """Protect source.
        """
        try:
            import stat

            self.source_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            logger.info(f"Source protégé (644) : {self.source_path}")
        except Exception as e:
            logger.warning(f"Impossible de protéger le source : {e}")

    # ── Fichier de travail courant ─────────────────────────────────────────────
    def _get_current_work_file(self) -> Path:
        """Get current work file.
        """
        work_files = list(self.workspace_dir.glob(f"{self.source_path.stem}_v*.py"))
        if work_files:
            work_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return work_files[0]
        return self._create_initial_copy()

    def _create_initial_copy(self) -> Path:
        """Create initial copy.
        """
        version = self._get_version_from_file(self.source_path) or "1.0"
        dest = self.workspace_dir / f"{self.source_path.stem}_v{version}.py"
        if not dest.exists():
            shutil.copy2(self.source_path, dest)
            logger.info(f"Copie initiale créée : {dest}")
        return dest

    # ── Propriété version courante ─────────────────────────────────────────────
    @property
    def current_version(self) -> str:
        """Current version.
        """
        v = self._get_version_from_file(self.work_path)
        if v:
            return v
        # Extraire depuis le nom de fichier
        m = re.search(r"_v([\d.]+)\.py$", self.work_path.name)
        return m.group(1) if m else "0.1"

    # ── Index des versions ─────────────────────────────────────────────────────
    def _rebuild_version_index(self) -> None:
        """Reconstruit l'index {version → path} depuis workspace + loop_trunk."""
        self._version_index.clear()
        for p in self.workspace_dir.glob(f"{self.source_path.stem}_v*.py"):
            v = self._get_version_from_file(p)
            if not v:
                m = re.search(r"_v([\d.]+)\.py$", p.name)
                v = m.group(1) if m else None
            if v:
                self._version_index[v] = p
        # Aussi indexer le tronc loop courant
        if self._loop_trunk:
            for p in self._loop_trunk.glob("*.py"):
                m = re.search(r"_v([\d.]+)\.py$", p.name)
                if m:
                    v = m.group(1)
                    if v not in self._version_index:
                        self._version_index[v] = p

    def can_rollback_to(self, version: str) -> bool:
        """Vérifie si une version est accessible pour rollback."""
        self._rebuild_version_index()
        return version in self._version_index

    def rollback(self, version: str) -> bool:
        """
        Rollback vers une version connue.
        Valide la syntaxe + taille + marqueurs AVANT de changer work_path.
        Sauvegarde l'état courant dans versions/ en cas d'urgence.
        Retourne True si succès.
        """
        self._rebuild_version_index()
        target = self._version_index.get(version)
        if not target or not target.exists():
            logger.warning(f"Rollback impossible : v{version} introuvable")
            return False

        # ── Validation du fichier cible avant rollback ─────────────────────
        reject = self._validate_patch(target, None)  # None = pas de check taille relative
        if reject:
            logger.error(
                f"[Rollback] REFUSÉ — v{version} ne passe pas la validation : {reject}. "
                f"Le fichier cible est peut-être corrompu."
            )
            return False

        # ── Sauvegarde défensive de l'état courant ─────────────────────────
        if self.work_path and self.work_path.exists():
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                safety = self.versions_dir / f"{self.work_path.stem}_pre_rollback_{ts}.py"
                shutil.copy2(self.work_path, safety)
                logger.info(f"[Rollback] Safety snapshot → {safety.name}")
            except Exception as _se:
                logger.warning(f"[Rollback] Safety snapshot échoué (non bloquant) : {_se}")

        prev_version = self.current_version
        self.work_path = target
        logger.info(f"[Rollback] v{prev_version} → v{version} ({target.name})")
        self._log_backlog("rollback", prev_version, version, f"rollback vers v{version}")
        return True

    # ── Tronc loop ────────────────────────────────────────────────────────────
    def start_loop_trunk(self) -> str:
        """
        Démarre un nouveau tronc loop séparé.
        Copie la version courante comme point de départ.
        Retourne l'ID du loop.
        """
        self._loop_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._loop_trunk = self.loop_dir / f"loop_{self._loop_id}"
        self._loop_trunk.mkdir(exist_ok=True)
        # Copie du point de départ
        start_copy = self._loop_trunk / self.work_path.name
        shutil.copy2(self.work_path, start_copy)
        logger.info(f"Tronc loop démarré : {self._loop_trunk}")
        self._rebuild_version_index()
        return self._loop_id

    def end_loop_trunk(self, merge: bool = True) -> None:
        """
        Termine le tronc loop.
        Si merge=True, la meilleure version du loop est fusionnée dans workspace.
        """
        if not self._loop_trunk or not self._loop_trunk.exists():
            return
        if merge:

            def _version_key(p: Path) -> None:
                """Version key.
                """
                m = re.search(r"_v([\d.]+)\.py$", p.name)
                if not m:
                    return [0]
                return [int(x) for x in re.findall(r"\d+", m.group(1))]

            loop_files = sorted(
                self._loop_trunk.glob("*.py"),
                key=_version_key,
                reverse=True,
            )
            if loop_files:
                best = loop_files[0]
                merged_path = self.workspace_dir / best.name
                shutil.copy2(best, merged_path)
                self.work_path = merged_path
                logger.info(f"Loop fusionné : {best.name} → workspace")
        self._loop_id = None
        self._loop_trunk = None
        self._rebuild_version_index()

    # ── Patch ─────────────────────────────────────────────────────────────────
    def _get_version_from_file(self, path: Path) -> Optional[str]:
        """Get version from file.
        """
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
            return m.group(1) if m else None
        except Exception:
            return None

    def _update_version_in_code(self, code: str, new_version: str) -> str:
        """Update version in code.
        """
        pattern = r'(__version__\s*=\s*)[\'"][\d.]+[\'"]'
        replacement = f'__version__ = "{new_version}"'
        if re.search(pattern, code):
            return re.sub(pattern, replacement, code)
        lines = code.splitlines(True)
        for i, line in enumerate(lines):
            if (
                line.strip()
                and not line.startswith("#")
                and not line.startswith("import")
                and not line.startswith("from")
            ):
                lines.insert(i, f"{replacement}\n")
                break
        else:
            lines.append(f"\n{replacement}\n")
        return "".join(lines)

    def _increment_version(self, version: str, major: bool = False) -> str:
        """Increment version.
        """
        parts = version.split(".")
        try:
            maj = int(parts[0])
            min_ = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            return "1.0"
        return f"{maj + 1}.0" if major else f"{maj}.{min_ + 1}"

    async def prepare_patch(
        self, new_code: str, description: str, major: bool = False, surgical: bool = False
    ) -> Optional[Path]:
        """
        Crée une nouvelle version patchée.
        Si un loop est en cours, écrit dans le tronc loop.
        Sinon écrit dans workspace.
        """
        current_version = self.current_version
        new_version = self._increment_version(current_version, major)
        new_code_v = self._update_version_in_code(new_code, new_version)
        new_filename = f"{self.source_path.stem}_v{new_version}.py"

        # Destination : tronc loop ou workspace
        dest_dir = self._loop_trunk if self._loop_trunk else self.workspace_dir
        new_work_path = dest_dir / new_filename

        try:
            new_work_path.write_text(new_code_v, encoding="utf-8")
        except Exception as e:
            logger.error(f"Erreur écriture patch : {e}")
            return None

        # ── PatchGuard : validation avant acceptation ─────────────────────────
        _reject_reason = self._validate_patch(new_work_path, self.work_path, surgical=surgical)
        if _reject_reason:
            logger.error(f"[PatchGuard] REJETÉ ({_reject_reason}) — fichier supprimé, work_path inchangé")
            try:
                new_work_path.unlink(missing_ok=True)
            except Exception:
                pass
            return None

        # Archive l'ancienne version dans workspace (seulement hors loop)
        if not self._loop_trunk and self.work_path.exists() and self.work_path != new_work_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive = self.versions_dir / f"{self.work_path.stem}_{ts}.py"
            shutil.move(str(self.work_path), str(archive))
            logger.info(f"Archivé : {archive.name}")

        self.work_path = new_work_path
        self._version_index[new_version] = new_work_path
        self._log_backlog("patch", current_version, new_version, description, major)
        return new_work_path

    # [→ forge_handlers.py] _validate_patch

    def _log_backlog(self, op: str, old_v: str, new_v: str, desc: str, major: bool = False) -> None:
        """Log backlog.
        """
        backlog_file = _DATA_DIR / ".patch_backlog.json"
        backlog = []
        if backlog_file.exists():
            try:
                backlog = json.loads(backlog_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        backlog.append(
            {
                "timestamp": datetime.now().isoformat(),
                "op": op,
                "old_version": old_v,
                "new_version": new_v,
                "description": desc,
                "major": major,
                "work_file": str(self.work_path),
                "loop_id": self._loop_id,
            }
        )
        try:
            backlog_file.write_text(json.dumps(backlog, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def get_current_code(self) -> str:
        """Get current code.
        """
        return self.work_path.read_text(encoding="utf-8", errors="replace")

    def list_loop_versions(self) -> List[Dict]:
        """Liste toutes les versions du tronc loop courant."""
        if not self._loop_trunk:
            return []
        result = []
        for p in sorted(self._loop_trunk.glob("*.py"), key=lambda x: x.stat().st_mtime):
            m = re.search(r"_v([\d.]+)\.py$", p.name)
            result.append(
                {
                    "version": m.group(1) if m else "?",
                    "path": str(p),
                    "size": p.stat().st_size,
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                }
            )
        return result

    def list_workspace_versions(self) -> List[Dict]:
        """Liste toutes les versions du workspace principal."""
        result = []
        for p in sorted(
            self.workspace_dir.glob(f"{self.source_path.stem}_v*.py"),
            key=lambda x: x.stat().st_mtime,
        ):
            m = re.search(r"_v([\d.]+)\.py$", p.name)
            result.append(
                {
                    "version": m.group(1) if m else "?",
                    "path": str(p),
                    "current": p == self.work_path,
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                }
            )
        return result


class IntentClassifier:
    """
    Classifieur d'intention NLU.
    Comprend les formulations naturelles françaises + commandes directes.
    """

    def __init__(self) -> None:
        """Initialise l'instance.
        """
        pass

    def classify(self, text: str) -> AgentType:
        """Classify.
        """
        intent, _ = self.classify_with_cmd(text)
        debug_log(
            hypothesis_id="H2",
            location="IntentClassifier.classify",
            message="Classification d'intention",
            data={"text_preview": text[:80], "agent": intent.value},
        )
        return intent

    def classify_hybrid(self, text: str) -> Tuple["AgentType", Optional[str], float]:
        """
        Classification hybride : predictif (< 1ms) d'abord, regex en fallback.
        Retourne (AgentType, cmd_extracted, confidence).
        """
        if HAS_PREDICTIF:
            try:
                _MAP = {
                    "action": AgentType.ACTION,
                    "rag": AgentType.RAG,
                    "chat": AgentType.CHAT,
                }
                intent_str, cmd, conf = hybrid_classify(
                    text,
                    static_fn=self.classify_with_cmd,
                    router=_pred_get_router(),
                    log_fn=debug_log,
                )
                return _MAP.get(intent_str, AgentType.CHAT), cmd, conf
            except Exception:
                pass
        # Pas de predictif : NLU regex classique
        agent, cmd = self.classify_with_cmd(text)
        return agent, cmd, 0.60

    # Patterns compilés une fois au niveau classe (performance)
    _CHAT_Q_PAT = re.compile(
        r"^(quel[les]*\s|quand\s|combien\s|pourquoi\s|comment\s+(?!faire\s+pour\s+)?"
        r"est.ce\s+que\s|est-ce\s+que\s|"
        r"qu['\u2019]est|c['\u2019]est\s+quoi|"
        r"peux.tu\s|pourrais.tu\s|sais.tu\s|connais.tu\s|"
        r"explique\s|raconte\s|dis.moi\s|parle.moi\s|"
        r"je\s+veux\s+savoir|j['\u2019]ai\s+besoin\s+de\s+savoir|"
        r"sur\s+quel\s|sur\s+quoi\s|d['\u2019]o[u\u00f9]\s|"
        r"qu['\u2019]il|qu['\u2019]elle|"
        r"c['\u2019]est\s+quoi|kesako|"
        r"(je\s+(veux|voudrais|souhaite|cherche|demande)\s+(?!(?:que\s+tu\s+)?(?:lancer?|ex\u00e9cuter?|stopper?|red\u00e9marrer?|installer?|supprimer?))))",
        re.I,
    )
    _CONV_PAT = re.compile(
        r"^(merci|ok\b|okay\b|oui\b|non\b|nope\b|ouais\b|yep\b|d['\u2019]accord|"
        r"parfait|super|bien\s+s[uû]r|nickel|génial|cool|bravo|"
        r"tu\s+es|tu\s+as|tu\s+peux\s+(me\s+)?(?!(?:lancer?|ex\u00e9cuter?|stopper?))|"
        r"c['\u2019]est\s+(?!la\s+commande|un\s+service|le\s+service)|"
        r"j['\u2019]ai\s+|j['\u2019]aurais\s+|j['\u2019]aimerai|"
        r"bonjour|salut|bonsoir|coucou|hello|hi\b|"
        r"d['\u2019]o[u\u00f9]\s+viens|tu\s+t['\u2019]appelles|"
        r"tu\s+connais|tu\s+sais\s+quoi\b)",
        re.I,
    )
    # Outils système — si présents dans une question, la reroutent vers ACTION
    _SYS_TOOLS = frozenset(
        {
            "top",
            "ps",
            "df",
            "free",
            "uptime",
            "netstat",
            "ss",
            "tail",
            "grep",
            "cat",
            "ls",
            "journalctl",
            "nmap",
            "htop",
            "iotop",
        }
    )
    # Starters conversationnels forts (premier mot) → CHAT immédiat
    _CHAT_STARTERS = frozenset(
        {
            "oui",
            "non",
            "ok",
            "okay",
            "ouais",
            "nope",
            "si",
            "ah",
            "merci",
            "parfait",
            "super",
            "génial",
            "cool",
            "nickel",
            "bonjour",
            "salut",
            "bonsoir",
            "coucou",
            "hello",
            "pourquoi",
            "quand",
            "combien",
            "lequel",
            "laquelle",
        }
    )

    def classify_with_cmd(self, text: str) -> Tuple[AgentType, Optional[str]]:
        """Classify with cmd.
        """
        from forge_handlers import classify_with_cmd as _fh

        return _fh(
            cmd,
            _chat_q_pat=self._CHAT_Q_PAT,
            _chat_starters=self._CHAT_STARTERS,
            _conv_pat=self._CONV_PAT,
            _sys_tools=self._SYS_TOOLS,
        )


class OllamaMemoryManager:
    """
    Gestion dynamique de la RAM/VRAM consommée par Ollama.
    - Détecte la quantification des modèles chargés (Q4, Q8, F16)
    - Configure le KV cache quantifié automatiquement si RAM faible
    - Stratégies d'éviction adaptatives basées sur la RAM disponible
    - Les modules (RAG, LLM, PTY) communiquent via ce manager
    """

    KNOWN_GiB: dict = {
        "deepseek-coder-v2": 8.9,
        "starcoder2:15b": 9.1,
        "glm-4.7-flash": 19.0,
        "qwen2.5-coder:latest": 4.7,
        "qwen2.5-coder:1.5b": 1.0,
        "mistral:7b": 4.4,
        "mistral:latest": 4.4,
        "qwen3:8b": 5.2,
        "qwen2:7b": 4.4,
        "tinyllama:1.1b": 0.6,
        "starcoder2:latest": 1.7,
        "bge-m3:latest": 1.2,
        "nomic-embed-text:latest": 0.3,
        "erukude/multiagent-orchestrator:1b": 1.4,
        "gpt-oss:120b-cloud": 0.0,
        "deepseek-v3.1:671b-cloud": 0.0,
        "deepseek-v3": 0.0,
        "qwen3-coder:480b-cloud": 0.0,
    }
    EVICT_SCORE: dict = {
        "embed": 0,
        "bge": 0,
        "nomic": 0,
        "1.1b": 1,
        "1.5b": 2,
        "3b": 3,
        "7b": 4,
    }
    # Seuils RAM en Mo pour les stratégies adaptatives
    RAM_CRITICAL = 1500  # > 1.5 Go → éviction agressive
    RAM_WARNING = 1000  # > 1 Go → éviction smart
    RAM_OK = 600  # < 600 Mo → tout va bien

    def __init__(self, base_url: str):
        """Initialise l'instance.
        """
        base = base_url.split("/api/")[0].rstrip("/")
        self._ps = base + "/api/ps"
        self._gen = base + "/api/generate"
        self._show = base + "/api/show"
        self._base = base
        self._model_info_cache: dict = {}  # cache info modèle (quant, params)
        self._kv_quant_enabled = False

    def estimate_gib(self, model: str) -> float:
        """Estimate gib.
        """
        low = model.lower()
        for k, v in self.KNOWN_GiB.items():
            if k in low:
                return v
        for tag, g in [("70b", 40.0), ("34b", 20.0), ("13b", 8.0), ("7b", 4.5), ("3b", 2.0), ("1b", 0.8)]:
            if tag in low:
                return g
        return 3.0

    async def loaded(self) -> list:
        """Loaded.
        """
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(self._ps, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        return (await r.json()).get("models", [])
        except Exception:
            pass
        return []

    async def model_info(self, model: str) -> dict:
        """Récupère les infos d'un modèle : quantification, taille, famille."""
        if model in self._model_info_cache:
            return self._model_info_cache[model]
        info = {"name": model, "quant": "unknown", "params": "?", "family": "?"}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(self._show, json={"name": model}, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        data = await r.json()
                        details = data.get("details", {})
                        info["quant"] = details.get("quantization_level", "unknown")
                        info["params"] = details.get("parameter_size", "?")
                        info["family"] = details.get("family", "?")
                        info["format"] = details.get("format", "?")
        except Exception:
            pass
        self._model_info_cache[model] = info
        return info

    async def detect_quantization(self) -> list:
        """Détecte la quantification de tous les modèles chargés."""
        models = await self.loaded()
        results = []
        for m in models:
            name = m.get("name", "")
            if not name:
                continue
            info = await self.model_info(name)
            gib = m.get("size_vram", m.get("size", 0)) / (1024**3)
            results.append(
                {
                    "name": name,
                    "quant": info["quant"],
                    "params": info["params"],
                    "family": info["family"],
                    "vram_gb": round(gib, 1),
                }
            )
        return results

    async def unload(self, model: str) -> float:
        """Unload.
        """
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    self._gen, json={"model": model, "keep_alive": 0}, timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    if r.status in (200, 204):
                        g = self.estimate_gib(model)
                        logger.debug(f"[MemMgr] unload {model} ~{g:.1f}G")
                        return g
        except Exception as e:
            logger.debug(f"[MemMgr] unload {model}: {e}")
        return 0.0

    async def set_kv_quant(self, model: str, enable: bool = True) -> bool:
        """Configure le KV cache quantifié pour un modèle (via num_ctx + flash_attn)."""
        try:
            # Ollama supporte flash attention et KV cache quantifié via les options
            opts = {"num_ctx": 4096}  # contexte réduit = moins de KV cache
            if enable:
                opts["num_ctx"] = 2048  # contexte court → KV cache minimal
                opts["num_batch"] = 256  # batch réduit
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    self._gen,
                    json={"model": model, "keep_alive": "5m", "options": opts},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    if r.status == 200:
                        self._kv_quant_enabled = enable
                        logger.info(
                            f"[MemMgr] KV quant {'ON' if enable else 'OFF'} pour {model} (ctx={opts['num_ctx']})"
                        )
                        return True
        except Exception as e:
            logger.debug(f"[MemMgr] set_kv_quant: {e}")
        return False

    async def status_lines(self) -> object:
        """Status lines.
        """
        models = await self.loaded()
        lines, total = [], 0.0
        for m in models:
            name = m.get("name", "?")
            gib = m.get("size_vram", m.get("size", 0)) / (1024**3)
            total += gib
            info = await self.model_info(name)
            quant = info.get("quant", "?")
            exp = m.get("expires_at", "")[:16].replace("T", " ")
            lines.append(f"  {name:<35} {quant:<6} {gib:>5.1f} GiB  exp {exp}")
        lines.append(f"  {'TOTAL':<35} {'':6} {total:>5.1f} GiB")
        return lines, total

    async def free(self, strategy: str = "embed", target: str = "") -> dict:
        """Free.
        """
        models = await self.loaded()
        evicted = []
        freed = 0.0
        if strategy == "all":
            for m in models:
                name = m.get("name", "")
                if name and name != target:
                    g = await self.unload(name)
                    evicted.append(name)
                    freed += g
        elif strategy == "embed":
            for m in models:
                name = m.get("name", "")
                if any(k in name.lower() for k in ("embed", "bge", "nomic")):
                    g = await self.unload(name)
                    evicted.append(name)
                    freed += g
        elif strategy == "smart":

            def score(m: object) -> int:
                """Score.
                """
                low = m.get("name", "").lower()
                for k, v in OllamaMemoryManager.EVICT_SCORE.items():
                    if k in low:
                        return v
                return 5

            need = self.estimate_gib(target) * 0.4
            for m in sorted(models, key=score):
                name = m.get("name", "")
                if name == target:
                    continue
                g = await self.unload(name)
                evicted.append(name)
                freed += g
                if freed >= need:
                    break
        return {"evicted": evicted, "freed_gib": freed}

    async def adaptive_manage(self, current_ram_mb: float = 0, target_model: str = "") -> None:
        """
        Stratégie adaptive — appelée automatiquement par le watchdog mémoire.
        Les modules ne s'appellent pas entre eux — ils passent tous par ici.
        """
        actions = []
        if current_ram_mb > self.RAM_CRITICAL:
            # Critique → tout décharger sauf le modèle cible
            r = await self.free("all", target=target_model)
            actions.append(f"critical: evicted {r['evicted']}")
            # Activer KV quant sur le modèle actif
            if target_model:
                await self.set_kv_quant(target_model, enable=True)
                actions.append(f"kv_quant ON for {target_model}")
        elif current_ram_mb > self.RAM_WARNING:
            # Warning → éviction smart
            r = await self.free("smart", target=target_model)
            if r["evicted"]:
                actions.append(f"smart: evicted {r['evicted']}")
        else:
            # OK → désactiver KV quant si activé
            if self._kv_quant_enabled and target_model:
                await self.set_kv_quant(target_model, enable=False)
                actions.append("kv_quant OFF (RAM OK)")
        if actions:
            logger.info(f"[MemMgr] adaptive: {', '.join(actions)}")
        return actions
