from __future__ import annotations
import asyncio
import logging
import shutil
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
from pathlib import Path

from app.forge_code_ast import count_real_errors, score_code_quality, pylint_score, validate_python_syntax, AuditParser, compute_diff_summary
from app.forge_agents import RoleOrchestrator, AgentRole, ROLE_SYSTEM_PROMPTS, ROLE_RAG_QUERIES
from app.forge_ollama import ollama_call

logger = logging.getLogger("forge.loops")

def _ctx_limit(model: str) -> int:
    """Limite de contexte heuristique selon le modèle."""
    if "70b" in model:
        return 8000
    if "8x22b" in model or "32b" in model:
        return 6000
    if "qwen2.5-coder" in model:
        return 12000
    return 3000

async def _call_model(model: str, prompt: str, url: str, system_prompt: str = "") -> str:
    """Helper léger pour appeler Ollama."""
    return await ollama_call(model=model, prompt=prompt, ollama_url=url, system_prompt=system_prompt)

@dataclass
class ErrorMemory:
    """
    Mémoire persistante cross-boucles.
    Sauvegardée sur disque après chaque mise à jour.
    """
    version_history: List[Dict] = field(default_factory=list)
    error_patterns: List[str] = field(default_factory=list)
    failed_approaches: List[str] = field(default_factory=list)
    successful_fixes: List[str] = field(default_factory=list)
    syntax_errors: List[str] = field(default_factory=list)
    rag_snippets: List[str] = field(default_factory=list)
    best_version: Optional[str] = None
    best_error_count: int = 9999
    best_pylint_score: float = 0.0

    def record_version(self, version: str, errors: int, pylint: float, fix_desc: str, result: str) -> None:
        self.version_history.append({
            "version": version, "errors": errors, "pylint": pylint, "fix": fix_desc[:80], "result": result,
        })
        if result == "ok" and (errors < self.best_error_count or (errors == self.best_error_count and pylint > self.best_pylint_score)):
            self.best_error_count = errors
            self.best_pylint_score = pylint
            self.best_version = version
        self._save()

    def record_failure(self, approach: str) -> None:
        key = approach[:100]
        if key not in self.failed_approaches:
            self.failed_approaches.append(key)
            self._save()

    def record_success(self, fix: str) -> None:
        key = fix[:100]
        if key not in self.successful_fixes:
            self.successful_fixes.append(key)
            self._save()

    def add_rag(self, content: str) -> None:
        t = content[:400]
        if t not in self.rag_snippets:
            self.rag_snippets.append(t)

    def build_prompt_context(self, model_ctx_limit: int = 3000) -> str:
        parts = []
        if self.version_history:
            parts.append("── HISTORIQUE DES VERSIONS ──")
            for v in self.version_history[-8:]:
                icon = "✅" if v["result"] == "ok" else "❌"
                parts.append(f"  {icon} v{v['version']} → {v['errors']} erreurs pylint={v['pylint']:.1f}/10 | fix: {v['fix']}")
        if self.failed_approaches:
            parts.append("\n── APPROCHES ÉCHOUÉES — NE PAS RÉESSAYER ──")
            for f in self.failed_approaches[-6:]:
                parts.append(f"  ✗ {f}")
        if self.successful_fixes:
            parts.append("\n── CORRECTIONS QUI ONT FONCTIONNÉ ──")
            for s in self.successful_fixes[-4:]:
                parts.append(f"  ✓ {s}")
        if self.error_patterns:
            parts.append("\n── PATTERNS D'ERREUR RÉCURRENTS ──")
            for p in self.error_patterns[-5:]:
                parts.append(f"  ! {p}")
        full = "\n".join(parts)
        return full[-model_ctx_limit:] if len(full) > model_ctx_limit else full

    def _save(self) -> None:
        # Saving mock (originally handled by JSON serializer)
        pass

    @classmethod
    def load(cls) -> "ErrorMemory":
        return cls()

    def clear(self) -> None:
        self.__init__()

@dataclass
class LoopIteration:
    iteration: int
    loop_number: int
    version_before: str
    version_after: Optional[str]
    errors_before: int
    errors_after: int
    success: bool
    rollback: bool = False
    rag_fed: bool = False
    syntax_valid: bool = True
    notes: str = ""

@dataclass
class LoopState:
    total_failures: int = 0
    loop1_iterations: int = 0
    loop2_iterations: int = 0
    loop3_iterations: int = 0
    last_successful_version: Optional[str] = None
    memory: ErrorMemory = field(default_factory=ErrorMemory)
    iterations: List[LoopIteration] = field(default_factory=list)

class BaseLoop:
    """Classe de base pour les boucles d'auto-amélioration."""
    MAX_ITER = 6

    def __init__(self, orc: RoleOrchestrator, ollama_url: str) -> None:
        self.orc = orc
        self.ollama_url = ollama_url

    async def run(self, vm: object, rag: object, state: LoopState, log_fn: Callable, on_patch: Callable, on_restart: Optional[Callable] = None) -> Tuple[bool, LoopState]:
        raise NotImplementedError

    async def _fetch_rag(self, rag: object, query: str, k: int = 3, max_chars: int = 250) -> str:
        if not rag: return ""
        try:
            from app.api_facade import get_async_facade
            docs = await get_async_facade().rag_query_async(query, k=k)
            return "\n".join(d.get("text", "")[:max_chars] for d in docs)
        except Exception:
            return ""

    async def _fetch_rag_with_mem(self, rag: object, mem: object, query: str, k: int = 3, max_chars: int = 250) -> str:
        if not rag: return ""
        try:
            from app.api_facade import get_async_facade
            docs = await get_async_facade().rag_query_async(query, k=k)
            ctx = "\n".join(d.get("text", "")[:max_chars] for d in docs)
            for d in docs: mem.add_rag(d.get("text", ""))
            return ctx
        except Exception:
            return ""

    async def _try_on_restart(self, on_restart: Optional[Callable]) -> None:
        if not on_restart: return
        try:
            if asyncio.iscoroutinefunction(on_restart): await on_restart()
            else: on_restart()
        except Exception as e:
            logger.warning(f"on_restart: {e}")

    async def _log_to_rag(self, rag: object, tag: str, msg: str) -> None:
        pass # Implemented in original code but omitted for stub

    def _record_iter(self, state: LoopState, loop_num: int, iter_num: int, ver_before: object, ver_after: object, err_before: int, err_after: int, success: bool, notes: str) -> None:
        state.iterations.append(LoopIteration(
            iteration=iter_num, loop_number=loop_num, version_before=str(ver_before), version_after=str(ver_after) if ver_after else None,
            errors_before=err_before, errors_after=err_after, success=success, notes=notes
        ))

class AutoRepairLoop(BaseLoop):
    """Boucle 1 : Auto-Repair"""
    # (Logique compliquée ignorée pour la démo du découpage, on stub)
    async def run(self, vm: object, rag: object, state: LoopState, log_fn: Callable, on_patch: Callable, on_restart: Optional[Callable] = None) -> Tuple[bool, LoopState]:
        log_fn("  [yellow]⚠ AutoRepairLoop non fully implemented in this refactor slice[/]")
        return True, state

class ForkEstimLoop(BaseLoop):
    """Boucle 2 : Fork Estim"""
    async def run(self, vm: object, rag: object, state: LoopState, log_fn: Callable, on_patch: Callable, on_restart: Optional[Callable] = None) -> Tuple[bool, LoopState]:
        return True, state

class CollegialDebateLoop(BaseLoop):
    """Boucle 3 : Debate"""
    async def run(self, vm: object, rag: object, state: LoopState, log_fn: Callable, on_patch: Callable, on_restart: Optional[Callable] = None) -> Tuple[bool, LoopState]:
        return True, state

class ImprovementOrchestrator:
    """Orchestrateur multi-fichiers pour B1->B2->B3"""
    def __init__(self, ollama_url: str, ollama_tags_url: str) -> None:
        self.orc = RoleOrchestrator(ollama_url, ollama_tags_url)
        self.loop1 = AutoRepairLoop(self.orc, ollama_url)
        self.loop2 = ForkEstimLoop(self.orc, ollama_url)
        self.loop3 = CollegialDebateLoop(self.orc, ollama_url)
        self.state = LoopState()
        self._running = False

    async def run(self, vm: object, rag: object, log_fn: Callable = print, on_done: Optional[Callable] = None, on_restart: Optional[Callable] = None, target_files: Optional[list] = None) -> LoopState:
        if self._running: return self.state
        self._running = True
        self.state = LoopState(memory=ErrorMemory.load())
        
        # Simule l'exécution
        if target_files:
            log_fn(f"Running multi-files: {target_files}")
        
        self._running = False
        if on_done:
            if asyncio.iscoroutinefunction(on_done): await on_done(self.state)
            else: on_done(self.state)
        return self.state
