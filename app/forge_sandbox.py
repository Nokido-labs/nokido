from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : sandbox"  # organe declare le 2026-09-06 (audit de raccordement)
import ast
import asyncio
import logging
import os
import sys
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, Tuple

from app.forge_code_ast import analyze_ast

logger = logging.getLogger("forge.sandbox")

@dataclass
class SandboxResult:
    prompt: str
    code: str
    passed: bool
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    ast_ok: bool = True
    duration_s: float = 0.0
    attempts: int = 1

    def summary(self) -> str:
        """Summary."""
        status = "✅ PASS" if self.passed else "❌ FAIL"
        lines = [f"{status} ({self.duration_s:.2f}s, {self.attempts} essai(s))"]
        if self.code:
            lines.append(f"```python\n{self.code[:600]}\n```")
        if self.stdout:
            lines.append(f"**Sortie :**\n```\n{self.stdout[:400]}\n```")
        if self.error:
            lines.append(f"**Erreur :**\n```\n{self.error[:300]}\n```")
        return "\n".join(lines)


class SafeRunner:
    """
    Exécute du code Python ou des modules WASM dans un environnement isolé.
    """

    def __init__(self, timeout: float = 5.0, max_output: int = 4096) -> None:
        self.timeout = timeout
        self.max_output = max_output

    async def run(self, code: str, mode: str = "python") -> Tuple[bool, str, str]:
        """
        Retourne (success, stdout, stderr).
        Supporte mode='python' (natif) et mode='wasm' (module compilé).
        """
        if mode == "wasm" or code.strip().startswith(b"\x00asm".decode(errors="ignore")):
            return await self._run_wasm(code)
            
        return await self._run_native_python(code)

    async def _run_wasm(self, wasm_content: str) -> Tuple[bool, str, str]:
        """Délègue l'exécution du module WASM au pont de Claude."""
        try:
            from app.forge_wasm_cervelet import run_wasm
            # On suppose que run_wasm gère le submit_wasm asynchrone
            res = await run_wasm(wasm_content)
            return res.get("ok", False), res.get("stdout", ""), res.get("stderr", "")
        except ImportError:
            return False, "", "WASM Subsystem (forge_wasm_cervelet) indisponible"
        except Exception as e:
            return False, "", f"WASM Execution Error: {e}"

    async def _run_native_python(self, code: str) -> Tuple[bool, str, str]:
        """Exécution standard en subprocess."""
        logger.debug(f"[CodeSandbox.run] native code={str(code)[:60]!r}")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, prefix="sandbox_",
            dir=tempfile.gettempdir(), encoding="utf-8"
        ) as f:
            f.write(code)
            tmpfile = f.name

        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._run_sync, tmpfile)
        finally:
            try:
                os.unlink(tmpfile)
            except OSError:
                pass

    def _run_sync(self, filepath: str) -> Tuple[bool, str, str]:
        import subprocess
        cmd = [sys.executable, filepath]
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=self.timeout,
                text=True, env=env, cwd=tempfile.gettempdir()
            , errors="replace")
            return result.returncode == 0, result.stdout[: self.max_output], result.stderr[: self.max_output]
        except subprocess.TimeoutExpired:
            return False, "", f"Timeout ({self.timeout}s) dépassé"
        except Exception as e:
            return False, "", str(e)


class AgentHistory:
    """
    Historique des exécutions par catégorie de tâche.
    Calcule un score prédictif : taux de succès pondéré par la durée.
    """

    def __init__(self, maxlen: int = 50) -> None:
        self._history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=maxlen))

    def record(self, category: str, duration: float, success: bool) -> None:
        self._history[category].append({
            "duration": duration, "success": 1.0 if success else 0.0, "ts": time.monotonic()
        })

    def predicted_score(self, category: str, base_score: float = 0.5) -> float:
        history = list(self._history.get(category, []))
        if not history:
            return base_score
        avg_success = sum(h["success"] for h in history) / len(history)
        avg_duration = sum(h["duration"] for h in history) / len(history)
        score = (base_score + avg_success) / (1 + avg_duration / 10)
        return max(0.0, min(1.0, score))


class OllamaCodeGen:
    """Génère du code Python via Ollama local."""
    SYSTEM_PROMPT = (
        "Tu es un expert Python DevOps. Génère UNIQUEMENT du code Python valide, "
        "sans explication, sans balises markdown."
    )
    def __init__(self, ollama_url: str = "http://localhost:11434/api/chat", model: str = "llama3"):
        self.ollama_url = ollama_url
        self.model = model

    async def generate(self, prompt: str, rag_context: str = "") -> str:
        # Implémentation via facade LLM ou bridge (simplified for stub)
        from app.api_facade import get_async_facade
        f = get_async_facade()
        ctx = rag_context if rag_context else self.SYSTEM_PROMPT
        # Cleanup markdown if returned
        res = await f.ask_llm_async(prompt, backend="ollama", context=ctx)
        return self._clean(res)
        
    async def fix(self, code: str, error: str) -> str:
        # Same here
        prompt = f"Fix this python code:\n{code}\nError: {error}"
        from app.api_facade import get_async_facade
        res = await get_async_facade().ask_llm_async(prompt, backend="ollama", context=self.SYSTEM_PROMPT)
        return self._clean(res)
        
    def _clean(self, text: str) -> str:
        text = text.replace("```python", "").replace("```", "")
        return text.strip()


class CodeSandbox:
    """
    Orchestre : génération → analyse → test → correction auto.
    """
    def __init__(self, codegen: OllamaCodeGen, runner: SafeRunner, rag_engine: object = None, max_retries: int = 2):
        self.codegen = codegen
        self.runner = runner
        self.rag_engine = rag_engine
        self.max_retries = max_retries
        self.history = AgentHistory()

    async def generate_and_test(self, prompt: str, category: str = "python") -> SandboxResult:
        t0 = time.monotonic()
        rag_ctx = ""
        if self.rag_engine:
            try:
                # Use facade instead of raw engine if needed
                from app.api_facade import get_async_facade
                docs = await get_async_facade().rag_query_async(prompt, k=3)
                if docs:
                    rag_ctx = "\n".join(d.get("text", "")[:200] for d in docs[:3])       
            except Exception:
                pass

        code = await self.codegen.generate(prompt, rag_context=rag_ctx)
        attempts = 1
        last_error = ""

        for attempt in range(self.max_retries + 1):
            if not code:
                return SandboxResult(prompt=prompt, code="", passed=False, error="Aucun code généré par le LLM", duration_s=time.monotonic() - t0, attempts=attempt + 1)

            # 1. Analyse AST
            ast_ok, ast_err = analyze_ast(code)
            if not ast_ok:
                if attempt < self.max_retries:
                    code = await self.codegen.fix(code, ast_err)
                    attempts += 1
                    continue
                return SandboxResult(prompt=prompt, code=code, passed=False, ast_ok=False, error=ast_err, duration_s=time.monotonic() - t0, attempts=attempts)

            # 2. Exécution sandbox
            success, stdout, stderr = await self.runner.run(code)
            last_error = stderr or ""
            attempts = attempt + 1

            if success:
                elapsed = time.monotonic() - t0
                self.history.record(category, elapsed, success=True)
                return SandboxResult(prompt=prompt, code=code, passed=True, stdout=stdout, stderr=stderr, duration_s=elapsed, attempts=attempts)
            
            if attempt < self.max_retries:
                code = await self.codegen.fix(code, stderr)

        elapsed = time.monotonic() - t0
        self.history.record(category, elapsed, success=False)
        return SandboxResult(prompt=prompt, code=code, passed=False, stderr=last_error, error="Echec après retries", duration_s=elapsed, attempts=attempts)
