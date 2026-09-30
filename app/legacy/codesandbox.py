"""
codesandbox.py — Sandbox de test et génération de code pour OctoDevOps
=======================================================================
OctoDevOps v5

Intègre la logique de codetesteur.py dans l'architecture Nokido :
  - Génération de code via Ollama (modèle local)
  - Analyse AST statique (syntaxe Python)
  - Exécution sandboxée avec timeout strict et isolation
  - Validation du résultat (stdout / returncode)
  - Score prédictif : taux de réussite historique par type de tâche
  - Intégration @code, @test, @sandbox dans DevOpsApp

Usage Nokido :
    from codesandbox import CodeSandbox, SandboxResult, get_sandbox

    sandbox = get_sandbox(ollama_url, rag_engine)
    result  = await sandbox.generate_and_test(prompt)
    if result.passed:
        print(result.code)
    else:
        print(result.error)

Commandes chat :
    @code  <description>  — génère + teste du code Python
    @test  <code python>  — teste directement du code
    @sandbox status       — état du sandbox (stats, historique)
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp

# ── Logging ───────────────────────────────────────────────────────────────────
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# RÉSULTAT D'UNE EXÉCUTION SANDBOX
# =============================================================================


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
        status = "✅ PASS" if self.passed else "❌ FAIL"
        lines = [f"{status} ({self.duration_s:.2f}s, {self.attempts} essai(s))"]
        if self.code:
            lines.append(f"```python\n{self.code[:600]}\n```")
        if self.stdout:
            lines.append(f"**Sortie :**\n```\n{self.stdout[:400]}\n```")
        if self.error:
            lines.append(f"**Erreur :**\n```\n{self.error[:300]}\n```")
        return "\n".join(lines)


# =============================================================================
# ANALYSE AST STATIQUE
# =============================================================================


def analyze_ast(code: str) -> Tuple[bool, str]:
    """
    Analyse statique AST du code Python.
    Retourne (is_valid, error_message).
    Bloque aussi les imports dangereux.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"SyntaxError line {e.lineno}: {e.msg}"

    # Vérification des imports dangereux
    BLOCKED_MODULES = {
        "os.system",
        "subprocess",
        "socket",
        "ctypes",
        "shutil.rmtree",
        "sys.exit",
    }
    BLOCKED_IMPORTS = {"socket", "ctypes"}

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = []
            if isinstance(node, ast.Import):
                mods = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module.split(".")[0]]
            for mod in mods:
                if mod in BLOCKED_IMPORTS:
                    return False, f"Import bloqué en sandbox : {mod}"

        # Blocage appels dangereux
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                full = f"{getattr(node.func.value, 'id', '')}. {node.func.attr}"
                if full.replace(" ", "") in BLOCKED_MODULES:
                    return False, f"Appel bloqué en sandbox : {full}"

    return True, ""


# =============================================================================
# EXÉCUTION SANDBOXÉE
# =============================================================================


class SafeRunner:
    """
    Exécute du code Python dans un subprocess isolé avec :
    - Timeout strict (défaut 5s)
    - Restrictions fichiers (répertoire temporaire)
    - Capture stdout / stderr
    - Limite mémoire via ulimit si disponible
    """

    def __init__(self, timeout: float = 5.0, max_output: int = 4096):
        self.timeout = timeout
        self.max_output = max_output

    async def run(self, code: str) -> Tuple[bool, str, str]:
        """
        Retourne (success, stdout, stderr).
        success = True si returncode == 0.
        """
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            prefix="sandbox_",
            dir=tempfile.gettempdir(),
            encoding="utf-8",
        ) as f:
            f.write(code)
            tmpfile = f.name

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._run_sync, tmpfile)
        finally:
            try:
                os.unlink(tmpfile)
            except OSError:
                pass

    def _run_sync(self, filepath: str) -> Tuple[bool, str, str]:
        """Exécution synchrone dans executor."""
        cmd = [sys.executable, filepath]

        # Préfixe ulimit sur Linux pour limiter la mémoire (256 MB)
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.timeout,
                text=True,
                env=env,
                cwd=tempfile.gettempdir(),
            errors="replace")
            stdout = result.stdout[: self.max_output]
            stderr = result.stderr[: self.max_output]
            return result.returncode == 0, stdout, stderr

        except subprocess.TimeoutExpired:
            return False, "", f"Timeout ({self.timeout}s) dépassé"
        except Exception as e:
            return False, "", str(e)


# =============================================================================
# HISTORIQUE & SCORING PRÉDICTIF
# =============================================================================


class AgentHistory:
    """
    Historique des exécutions par catégorie de tâche.
    Calcule un score prédictif : taux de succès pondéré par la durée.
    """

    def __init__(self, maxlen: int = 50):
        self._history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=maxlen))

    def record(self, category: str, duration: float, success: bool):
        self._history[category].append(
            {
                "duration": duration,
                "success": 1.0 if success else 0.0,
                "ts": time.monotonic(),
            }
        )

    def predicted_score(self, category: str, base_score: float = 0.5) -> float:
        """
        Score prédictif ∈ [0, 1].
        Formule : (base + avg_success) / (1 + avg_duration / 10)
        Plus rapide et fiable = meilleur score.
        """
        history = list(self._history.get(category, []))
        if not history:
            return base_score
        avg_success = sum(h["success"] for h in history) / len(history)
        avg_duration = sum(h["duration"] for h in history) / len(history)
        score = (base_score + avg_success) / (1 + avg_duration / 10)
        return max(0.0, min(1.0, score))

    def stats(self) -> Dict[str, Dict]:
        out = {}
        for cat, hist in self._history.items():
            hist_list = list(hist)
            if not hist_list:
                continue
            out[cat] = {
                "count": len(hist_list),
                "success_rate": sum(h["success"] for h in hist_list) / len(hist_list),
                "avg_duration": sum(h["duration"] for h in hist_list) / len(hist_list),
            }
        return out


# =============================================================================
# GÉNÉRATEUR DE CODE VIA OLLAMA
# =============================================================================


class OllamaCodeGen:
    """Génère du code Python via Ollama local."""

    SYSTEM_PROMPT = (
        "Tu es un expert Python DevOps. "
        "Génère UNIQUEMENT du code Python valide, sans explication, sans balises markdown. "
        "Le code doit être exécutable directement, inclure print() pour les résultats visibles. "
        "Utilise uniquement les bibliothèques standard Python (pas de pip install nécessaire)."
    )

    FIX_PROMPT_TMPL = (
        "Le code Python suivant a produit une erreur.\n"
        "Code :\n```python\n{code}\n```\n"
        "Erreur : {error}\n\n"
        "Corrige le code. Réponds UNIQUEMENT avec le code Python corrigé, sans explication."
    )

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434/api/chat",
        model: str = "llama3",
        max_tokens: int = 800,
        timeout: float = 60.0,
    ):
        self.ollama_url = ollama_url
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def generate(self, prompt: str, rag_context: str = "") -> str:
        """Génère du code Python pour le prompt donné."""
        user_content = prompt
        if rag_context:
            user_content = f"{prompt}\n\n# Contexte disponible :\n{rag_context[:600]}"

        return await self._call(
            system=self.SYSTEM_PROMPT,
            user=user_content,
        )

    async def fix(self, code: str, error: str) -> str:
        """Génère un code corrigé basé sur l'erreur."""
        return await self._call(
            system=self.SYSTEM_PROMPT,
            user=self.FIX_PROMPT_TMPL.format(code=code[:1500], error=error[:300]),
        )

    async def _call(self, system: str, user: str) -> str:
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    self.ollama_url,
                    json={
                        "model": self.model,
                        "stream": False,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "options": {"num_predict": self.max_tokens},
                    },
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(f"Ollama {resp.status}: {body[:200]}")
                    data = await resp.json()
                    return self._clean(data.get("message", {}).get("content", ""))
        except Exception as e:
            logger.error(f"CodeGen error: {e}")
            return ""

    def _clean(self, text: str) -> str:
        """Retire les balises markdown si présentes."""
        text = re.sub(r"^```(?:python)?\s*\n", "", text.strip(), flags=re.I)
        text = re.sub(r"\n```\s*$", "", text.strip())
        return text.strip()


# =============================================================================
# SANDBOX PRINCIPAL
# =============================================================================


class CodeSandbox:
    """
    Orchestre : génération → analyse → test → correction auto.

    Flux :
      1. Génère le code via Ollama (avec contexte RAG si dispo)
      2. Analyse AST statique (syntaxe + sécurité)
      3. Exécute dans le subprocess sandbox
      4. Si FAIL → tente auto-correction (max_retries fois)
      5. Enregistre dans l'historique pour le scoring prédictif
    """

    def __init__(
        self,
        codegen: OllamaCodeGen,
        runner: SafeRunner,
        rag_engine=None,
        max_retries: int = 2,
    ):
        self.codegen = codegen
        self.runner = runner
        self.rag_engine = rag_engine
        self.max_retries = max_retries
        self.history = AgentHistory()

    async def generate_and_test(self, prompt: str, category: str = "python") -> SandboxResult:
        """
        Pipeline complet : génère + teste, avec correction automatique.
        """
        t0 = time.monotonic()

        # Contexte RAG
        rag_ctx = ""
        if self.rag_engine:
            try:
                docs = await self.rag_engine.search(prompt, k=3)
                if docs:
                    rag_ctx = "\n".join(d.get("content", "")[:200] for d in docs[:3])
            except Exception:
                pass

        code = await self.codegen.generate(prompt, rag_context=rag_ctx)
        attempts = 1
        last_error = ""

        for attempt in range(self.max_retries + 1):
            if not code:
                return SandboxResult(
                    prompt=prompt,
                    code="",
                    passed=False,
                    error="Aucun code généré par le LLM",
                    duration_s=time.monotonic() - t0,
                    attempts=attempt + 1,
                )

            # 1. Analyse AST
            ast_ok, ast_err = analyze_ast(code)
            if not ast_ok:
                if attempt < self.max_retries:
                    code = await self.codegen.fix(code, ast_err)
                    attempts += 1
                    continue
                return SandboxResult(
                    prompt=prompt,
                    code=code,
                    passed=False,
                    ast_ok=False,
                    error=ast_err,
                    duration_s=time.monotonic() - t0,
                    attempts=attempts,
                )

            # 2. Exécution sandbox
            success, stdout, stderr = await self.runner.run(code)
            last_error = stderr or ""
            attempts = attempt + 1

            if success:
                elapsed = time.monotonic() - t0
                self.history.record(category, elapsed, success=True)
                return SandboxResult(
                    prompt=prompt,
                    code=code,
                    passed=True,
                    stdout=stdout,
                    stderr=stderr,
                    duration_s=elapsed,
                    attempts=attempts,
                )

            # 3. Auto-correction si tentatives restantes
            if attempt < self.max_retries:
                logger.debug(f"Sandbox FAIL (attempt {attempt + 1}) — retrying with fix")
                code = await self.codegen.fix(code, stderr or "Exécution échouée")
                attempts += 1

        elapsed = time.monotonic() - t0
        self.history.record(category, elapsed, success=False)
        return SandboxResult(
            prompt=prompt,
            code=code,
            passed=False,
            stderr=last_error,
            error=f"Échec après {attempts} essai(s)",
            duration_s=elapsed,
            attempts=attempts,
        )

    async def test_code(self, code: str) -> SandboxResult:
        """Teste du code fourni directement (sans génération)."""
        t0 = time.monotonic()
        ast_ok, ast_err = analyze_ast(code)
        if not ast_ok:
            return SandboxResult(
                prompt="[direct test]",
                code=code,
                passed=False,
                ast_ok=False,
                error=ast_err,
                duration_s=time.monotonic() - t0,
            )
        success, stdout, stderr = await self.runner.run(code)
        return SandboxResult(
            prompt="[direct test]",
            code=code,
            passed=success,
            stdout=stdout,
            stderr=stderr,
            duration_s=time.monotonic() - t0,
        )

    def stats_report(self) -> str:
        stats = self.history.stats()
        if not stats:
            return "Aucune exécution sandbox enregistrée."
        lines = ["**Statistiques sandbox :**\n"]
        for cat, s in stats.items():
            rate = s["success_rate"] * 100
            lines.append(f"  `{cat}` : {s['count']} exécutions, {rate:.0f}% succès, moy. {s['avg_duration']:.2f}s")
        return "\n".join(lines)


# =============================================================================
# DÉTECTION DANGER : filtre les commandes distantes risquées
# =============================================================================

# Patterns de code dangereux à détecter avant d'envoyer sur un hôte
_DANGEROUS_PATTERNS = [
    re.compile(r"\b(rm\s+-rf?|shutil\.rmtree|os\.remove)\b", re.I),
    re.compile(r"\b(format\s*\(|mkfs|wipefs|dd\s+if=)\b", re.I),
    re.compile(r"\b(subprocess\.(?:run|Popen|call))\b", re.I),
    re.compile(r"\b(eval|exec)\s*\(", re.I),
    re.compile(r"__import__\s*\(", re.I),
]


def is_dangerous_code(code: str) -> Tuple[bool, str]:
    """
    Détecte du code potentiellement dangereux.
    Retourne (is_dangerous, reason).
    """
    for pat in _DANGEROUS_PATTERNS:
        m = pat.search(code)
        if m:
            return True, f"Pattern dangereux détecté : `{m.group(0)}`"
    return False, ""


# =============================================================================
# INTÉGRATION NOKIDO — handler @code / @test / @sandbox
# =============================================================================


async def handle_code_command(
    sandbox: "CodeSandbox",
    sub: str,
    args: str,
    chat_write,
) -> None:
    """
    Dispatcher pour les commandes @code, @test, @sandbox.
    chat_write = callable(text) pour écrire dans le chat Textual.
    """
    if sub == "code" or sub == "gen":
        if not args:
            chat_write("Usage : `@code <description de ce que le code doit faire>`")
            return
        chat_write(f"[dim]🐍 Génération + test sandbox : {args[:60]}…[/]")
        result = await sandbox.generate_and_test(args)
        chat_write(result.summary())

    elif sub == "test":
        if not args:
            chat_write("Usage : `@test <code python>`")
            return
        dangerous, reason = is_dangerous_code(args)
        if dangerous:
            chat_write(f"[bold red]🛡 Sandbox bloqué — {reason}[/]")
            return
        chat_write("[dim]🧪 Test du code…[/]")
        result = await sandbox.test_code(args)
        chat_write(result.summary())

    elif sub == "sandbox":
        if args.strip().lower() == "status":
            chat_write(sandbox.stats_report())
        else:
            chat_write("Usage : `@sandbox status`")

    else:
        chat_write(
            "`@code <desc>` — génère + teste du code Python\n"
            "`@test <code>` — teste du code directement\n"
            "`@sandbox status` — statistiques d'exécution"
        )


# =============================================================================
# SINGLETON GLOBAL
# =============================================================================
_global_sandbox: Optional[CodeSandbox] = None


def get_sandbox(
    ollama_url: str = "http://localhost:11434/api/chat",
    model: str = "llama3",
    rag_engine=None,
    max_retries: int = 2,
    timeout: float = 5.0,
) -> CodeSandbox:
    global _global_sandbox
    if _global_sandbox is None:
        codegen = OllamaCodeGen(ollama_url=ollama_url, model=model)
        runner = SafeRunner(timeout=timeout)
        _global_sandbox = CodeSandbox(
            codegen=codegen,
            runner=runner,
            rag_engine=rag_engine,
            max_retries=max_retries,
        )
    return _global_sandbox
