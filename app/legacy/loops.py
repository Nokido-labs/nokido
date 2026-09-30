"""
loops.py — Amélioration autonome fusionnée v3
=============================================
Fork OctoDevOps v5

FUSION des deux versions :
  ✅ De TON code  : on_restart optionnel (appelé après chaque patch réussi)
  ✅ De TON code  : AuditParser (count_errors sur texte d'audit LLM)
  ✅ Du mien      : ErrorMemory (mémoire cross-boucles, auto-apprentissage)
  ✅ Du mien      : validate_python_syntax() bloque patches invalides
  ✅ Du mien      : count_real_errors() sur le CODE (ast + heuristiques)
  ✅ Du mien      : prompts enrichis version + historique échecs/succès
  ✅ Du mien      : retry sur _call_model (2 tentatives + backoff)
  ✅ Du mien      : rollback vers best_version connue (pas n-1 aveugle)

4 POINTS CORRIGÉS (demandés) :
  ✅ 1. Signal de qualité réel : pylint --score async en plus des heuristiques
  ✅ 2. ErrorMemory persistée sur disque (.improvement_memory.json)
  ✅ 3. can_rollback_to() vérifié AVANT chaque rollback
  ✅ 4. Contexte injecté limité selon taille modèle (petit/grand)

LOGIQUE on_restart :
  Appelé après chaque patch réussi. Ne fait pas return immédiat en B1
  (contrairement à ton code) — on_restart peut être os.execv() pour
  redémarrer le processus entier avec le nouveau code.
  La boucle continue ensuite pour mesurer la progression réelle.
"""

import ast
import asyncio
import aiohttp
import difflib
import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from roles import (
    AgentRole,
    RoleOrchestrator,
    ROLE_SYSTEM_PROMPTS,
    ROLE_RAG_QUERIES,
    ROLE_META,
)

logger = logging.getLogger(__name__)

MEMORY_FILE = Path(".improvement_memory.json")


# =============================================================================
# ANALYSE STATIQUE DU CODE
# =============================================================================


def validate_python_syntax(code: str) -> Tuple[bool, str]:
    """Retourne (ok, message). Bloque tout patch invalide."""
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError ligne {e.lineno}: {e.msg}"
    except Exception as e:
        return False, str(e)


async def pylint_score(code: str) -> float:
    """
    Lance pylint en subprocess async sur le code.
    Retourne un score [0.0 .. 10.0]. Retourne 5.0 si pylint absent.
    Point 1 corrigé : signal de qualité réel, pas seulement heuristique.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3",
            "-c",
            f"import pylint.lint, sys; "
            f"from io import StringIO; "
            f"import tempfile, os; "
            f"f=tempfile.NamedTemporaryFile(suffix='.py',delete=False,mode='w'); "
            f"f.write({repr(code)}); f.close(); "
            f"from pylint.lint import Run; "
            f"from pylint.reporters.text import TextReporter; "
            f"out=StringIO(); "
            f"r=TextReporter(out); "
            f"Run([f.name,'--score=y','--disable=all','--enable=E,W'], reporter=r, exit=False); "
            f"os.unlink(f.name); "
            f"txt=out.getvalue(); "
            f"import re; m=re.search(r'rated at ([\\d.]+)', txt); "
            f"print(m.group(1) if m else '5.0')",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        score_str = out.decode().strip().split("\n")[-1]
        return max(0.0, min(10.0, float(score_str)))
    except Exception:
        return 5.0


def count_real_errors(code: str) -> int:
    """
    Score d'erreurs statiques [0..∞].
    Combine : syntaxe + heuristiques de mauvaises pratiques.
    """
    ok, _ = validate_python_syntax(code)
    if not ok:
        return 100

    count = 0
    lines = code.splitlines()
    for idx, line in enumerate(lines):
        s = line.strip()
        if s == "except:" or re.match(r"^except\s*:", s):
            count += 2
        if re.match(r"^except", s) and idx + 1 < len(lines):
            if lines[idx + 1].strip() == "pass":
                count += 1
        if re.match(r"#\s*(TODO|FIXME|HACK)\b", s, re.IGNORECASE):
            count += 1

    for imp in re.findall(r"^import\s+(\w+)", code, re.MULTILINE):
        if len(re.findall(rf"\b{re.escape(imp)}\b", code)) <= 1:
            count += 1

    for blt in ("list", "dict", "set", "type", "id", "input"):
        if re.search(rf"^\s*{blt}\s*=", code, re.MULTILINE):
            count += 1

    return count


def score_code_quality(code: str) -> int:
    """Score heuristique [0..100]."""
    ok, _ = validate_python_syntax(code)
    if not ok:
        return 0
    score = 50
    lines = code.splitlines()
    if 30 < len(lines) < 8000:
        score += 10
    score += min(10, code.count('"""') + code.count("'''"))
    score += min(10, code.count("except ") * 2)
    score += min(5, code.count("->") + code.count(": str") + code.count(": int"))
    score -= len(re.findall(r"print\(.*DEBUG", code, re.IGNORECASE)) * 3
    score -= len(re.findall(r"#\s*(TODO|FIXME)", code, re.IGNORECASE)) * 2
    return max(0, min(100, score))


def compute_diff_summary(before: str, after: str) -> str:
    diff = list(
        difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile="avant", tofile="après", n=2
        )
    )
    if not diff:
        return "(aucun changement)"
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    samples = [l.strip()[:70] for l in diff if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))][:3]
    return f"+{added}/-{removed} lignes\n  " + "\n  ".join(samples)


# =============================================================================
# AUDIT PARSER (de TON code — complémentaire à count_real_errors)
# =============================================================================


class AuditParser:
    """
    Parse les réponses textuelles des LLMs (audits).
    Complémentaire à count_real_errors qui analyse le CODE.
    AuditParser analyse ce que le LLM dit sur le code.
    """

    SUGGESTION_RE = re.compile(
        r"(?:Suggestion|Fix|Correction|Patch)\s*[#°N]*\s*(\d+)\s*[:\-]\s*(.*?)\n```python\n(.*?)\n```",
        re.DOTALL | re.IGNORECASE,
    )
    CLEAN_PHRASES = [
        "aucun problème",
        "no issues",
        "code is clean",
        "aucune erreur",
        "no errors found",
        "looks good",
        "bien structuré",
        "no bugs",
        "nothing to fix",
        "pas d'erreur",
    ]

    @classmethod
    def extract_suggestions(cls, text: str) -> List[Dict]:
        suggestions = []
        for m in cls.SUGGESTION_RE.finditer(text):
            code = m.group(3).strip()
            ok, _ = validate_python_syntax(code)
            suggestions.append(
                {
                    "num": int(m.group(1)),
                    "description": m.group(2).strip(),
                    "code": code,
                    "syntax_ok": ok,
                }
            )
        # Fallback : bloc python seul
        if not suggestions:
            m = re.search(r"```python\n(.*?)\n```", text, re.DOTALL)
            if m:
                code = m.group(1).strip()
                ok, _ = validate_python_syntax(code)
                dm = re.search(r"(?:fix|corriger?|améliorer?|problème|erreur)[^.]{5,80}\.", text[:600], re.IGNORECASE)
                suggestions.append(
                    {
                        "num": 1,
                        "description": dm.group(0)[:80] if dm else "Correction proposée",
                        "code": code,
                        "syntax_ok": ok,
                    }
                )
        return suggestions

    @classmethod
    def count_audit_errors(cls, text: str) -> int:
        """Erreurs mentionnées dans le TEXTE d'audit (pas dans le code)."""
        suggestions = cls.extract_suggestions(text)
        raw = len(re.findall(r"\b(error|erreur|bug|exception|problème|issue|warning)\b", text, re.IGNORECASE))
        return max(len(suggestions), raw // 3)

    @classmethod
    def is_clean(cls, text: str) -> bool:
        has_clean = any(p in text.lower() for p in cls.CLEAN_PHRASES)
        return has_clean and not cls.extract_suggestions(text)


# =============================================================================
# MÉMOIRE D'APPRENTISSAGE
# =============================================================================


@dataclass
class ErrorMemory:
    """
    Mémoire persistante cross-boucles.
    Point 2 corrigé : sauvegardée sur disque après chaque mise à jour.
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

    # ── Mutations ─────────────────────────────────────────────────────────────

    def record_version(self, version: str, errors: int, pylint: float, fix_desc: str, result: str):
        self.version_history.append(
            {
                "version": version,
                "errors": errors,
                "pylint": pylint,
                "fix": fix_desc[:80],
                "result": result,
            }
        )
        if result == "ok" and (
            errors < self.best_error_count or (errors == self.best_error_count and pylint > self.best_pylint_score)
        ):
            self.best_error_count = errors
            self.best_pylint_score = pylint
            self.best_version = version
        self._save()

    def record_failure(self, approach: str):
        key = approach[:100]
        if key not in self.failed_approaches:
            self.failed_approaches.append(key)
            self._save()

    def record_success(self, fix: str):
        key = fix[:100]
        if key not in self.successful_fixes:
            self.successful_fixes.append(key)
            self._save()

    def add_rag(self, content: str):
        t = content[:400]
        if t not in self.rag_snippets:
            self.rag_snippets.append(t)

    def build_prompt_context(self, model_ctx_limit: int = 3000) -> str:
        """
        Contexte à injecter dans les prompts.
        Point 4 corrigé : limité selon la capacité du modèle.
        """
        parts = []
        if self.version_history:
            parts.append("── HISTORIQUE DES VERSIONS ──")
            for v in self.version_history[-8:]:
                icon = "✅" if v["result"] == "ok" else "❌"
                parts.append(
                    f"  {icon} v{v['version']} → {v['errors']} erreurs pylint={v['pylint']:.1f}/10 | fix: {v['fix']}"
                )
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
                parts.append(f"  • {p}")
        if self.syntax_errors:
            parts.append("\n── PATCHES REJETÉS (SYNTAXE INVALIDE) ──")
            for e in self.syntax_errors[-3:]:
                parts.append(f"  ⚠ {e}")

        result = "\n".join(parts)
        # Limite selon capacité du modèle (Point 4)
        return result[:model_ctx_limit] if result else "(première itération)"

    # ── Persistance disque (Point 2) ─────────────────────────────────────────

    def _save(self):
        try:
            tmp = MEMORY_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(MEMORY_FILE)
        except Exception as e:
            logger.warning(f"ErrorMemory save: {e}")

    @classmethod
    def load(cls) -> "ErrorMemory":
        if MEMORY_FILE.exists():
            try:
                data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except Exception as e:
                logger.warning(f"ErrorMemory load: {e}")
        return cls()

    def clear(self):
        self.__init__()
        if MEMORY_FILE.exists():
            MEMORY_FILE.unlink(missing_ok=True)


# =============================================================================
# ÉTAT DE SESSION
# =============================================================================


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
    rag_error_docs: List[Dict] = field(default_factory=list)
    iterations: List[LoopIteration] = field(default_factory=list)
    memory: ErrorMemory = field(default_factory=ErrorMemory)


# =============================================================================
# APPEL LLM — retry + backoff
# =============================================================================


def _ctx_limit(model: str) -> int:
    """
    Estime la limite de contexte par nom de modèle.
    Point 4 : adapte la taille du contexte injecté.
    """
    ml = model.lower()
    if any(k in ml for k in ("llama3.3", "qwen3", "deepseek-r1", "72b", "70b")):
        return 3000  # grands modèles : contexte complet
    if any(k in ml for k in ("32b", "qwen2.5-coder:32")):
        return 2500
    if any(k in ml for k in ("14b", "13b")):
        return 2000
    return 1500  # petits modèles (7b/8b) : contexte réduit


async def _call_model(model: str, prompt: str, ollama_url: str, timeout: int = 180, retries: int = 2) -> str:
    """Appel Ollama streaming avec retry + backoff exponentiel."""
    for attempt in range(retries + 1):
        full = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    ollama_url,
                    json={"model": model, "messages": [{"role": "user", "content": prompt}], "stream": True},
                    timeout=aiohttp.ClientTimeout(total=timeout, connect=10),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"Ollama HTTP {resp.status} ({model})")
                        break
                    async for raw in resp.content:
                        if not raw:
                            continue
                        try:
                            data = json.loads(raw.decode("utf-8", errors="replace").strip())
                            tok = data.get("message", {}).get("content", "")
                            if tok:
                                full.append(tok)
                            if data.get("done"):
                                break
                        except Exception:
                            continue
            result = "".join(full)
            if result.strip():
                return result
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            logger.warning(f"_call_model {model} tentative {attempt + 1}: {e}")
        if attempt < retries:
            await asyncio.sleep(2**attempt)
    return ""


# =============================================================================
# BOUCLE 1 — AUTO-REPAIR AUTO-APPRENANT
# =============================================================================


class AutoRepairLoop:
    """
    Audit dual → valide syntaxe → mesure progression réelle →
    alimente mémoire → rollback intelligent vers best_version.

    on_restart (de TON code) : appelé après chaque patch appliqué avec succès.
    Ne fait PAS return immédiat : on_restart peut relancer le process (os.execv),
    mais la boucle continue pour mesurer la progression sur la nouvelle base.
    """

    MAX_ITER = 6
    STALL_LIMIT = 2

    def __init__(self, orc: RoleOrchestrator, ollama_url: str):
        self.orc = orc
        self.ollama_url = ollama_url

    async def run(
        self,
        vm,
        rag,
        state: LoopState,
        log_fn: Callable,
        on_patch: Callable,
        on_restart: Optional[Callable] = None,
    ) -> Tuple[bool, LoopState]:

        log_fn("\n[bold #58a6ff]━━━ BOUCLE 1 : Auto-Repair ━━━[/]")
        assignments = await self.orc.assign_roles(1, True, log_fn)
        debugger = assignments.get(AgentRole.DEBUGGER)
        analyste = assignments.get(AgentRole.ANALYSTE) or debugger
        if not debugger:
            log_fn("[red]❌ Aucun modèle DEBUGGER disponible.[/]")
            return False, state

        stall_count = 0
        mem = state.memory
        dbg_ctx_lim = _ctx_limit(debugger)

        for i in range(1, self.MAX_ITER + 1):
            state.loop1_iterations += 1
            code = vm.get_current_code()
            ver_before = vm.current_version
            errors_now = count_real_errors(code)
            quality = score_code_quality(code)

            log_fn(
                f"\n[dim]── B1 itération {i}/{self.MAX_ITER} "
                f"[bold]v{ver_before}[/] — {errors_now} erreurs, "
                f"qualité={quality}/100[/]"
            )

            if errors_now == 0 and quality >= 70:
                log_fn("[green]✅ Code propre.[/]")
                mem.record_version(ver_before, 0, 10.0, "code propre", "ok")
                state.last_successful_version = ver_before
                return True, state

            # Lire RAG
            rag_ctx = ""
            if rag:
                try:
                    docs = await rag.search(ROLE_RAG_QUERIES[AgentRole.DEBUGGER] + f" v{ver_before}", k=3)
                    rag_ctx = "\n".join(d["content"][:250] for d in docs)
                    for d in docs:
                        mem.add_rag(d["content"])
                except Exception:
                    pass

            ctx = mem.build_prompt_context(model_ctx_limit=dbg_ctx_lim)

            # ── Prompts enrichis ──────────────────────────────────────────
            prompt_dbg = f"""{ROLE_SYSTEM_PROMPTS[AgentRole.DEBUGGER]}

╔══ CONTEXTE SESSION ══╗
{ctx}
╚══════════════════════╝

VERSION COURANTE : v{ver_before}
MÉTRIQUES : {errors_now} erreurs, qualité={quality}/100
{("CONTEXTE RAG :\n" + rag_ctx) if rag_ctx else ""}

INSTRUCTIONS :
1. Identifie le bug le plus critique
2. UNE seule correction complète
3. N'utilise PAS les approches ✗ ci-dessus
4. Code Python COMPLET et valide dans ```python
5. Format : Suggestion 1 : [titre]\n```python\n[code]\n```

CODE (v{ver_before}) :
```python
{code[:8000]}
```"""

            prompt_anl = f"""{ROLE_SYSTEM_PROMPTS[AgentRole.ANALYSTE]}

CONTEXTE SESSION :
{mem.build_prompt_context(model_ctx_limit=_ctx_limit(analyste))}

VERSION : v{ver_before}
Identifie les 3 problèmes structurels. Sois concis.

```python
{code[:4000]}
```"""

            log_fn(f"  🔧 DEBUGGER[{debugger}] + 🔍 ANALYSTE[{analyste}]…")
            t0 = time.perf_counter()
            r_dbg, r_anl = await asyncio.gather(
                _call_model(debugger, prompt_dbg, self.ollama_url),
                _call_model(analyste, prompt_anl, self.ollama_url),
                return_exceptions=True,
            )
            log_fn(f"  ⏱ {time.perf_counter() - t0:.1f}s")

            dbg_reply = r_dbg if isinstance(r_dbg, str) else ""
            anl_reply = r_anl if isinstance(r_anl, str) else ""

            if not dbg_reply:
                log_fn("  [red]❌ DEBUGGER sans réponse.[/]")
                stall_count += 1
                mem.record_failure(f"B1-i{i}: DEBUGGER timeout")
                continue

            # Patterns structurels depuis analyste
            if anl_reply:
                for line in anl_reply.splitlines():
                    if any(k in line.lower() for k in ["problème", "bug", "erreur", "issue"]):
                        mem.error_patterns.append(f"[v{ver_before}] {line.strip()[:90]}")

            # Audit LLM indique code propre ?
            if AuditParser.is_clean(dbg_reply) and errors_now <= 2:
                log_fn("[green]✅ Audit : code propre.[/]")
                pl = await pylint_score(code)
                mem.record_version(ver_before, errors_now, pl, "audit clean", "ok")
                state.last_successful_version = ver_before
                return True, state

            # Extraire suggestions
            suggestions = AuditParser.extract_suggestions(dbg_reply)
            if not suggestions:
                log_fn("  [yellow]⚠ Aucune suggestion parsable.[/]")
                stall_count += 1
                mem.record_failure(f"B1-i{i}: réponse non parsable")
                if rag:
                    try:
                        await rag.add_session_message(
                            "improvement_loop",
                            "b1_nopatch",
                            f"[v{ver_before}] DEBUGGER non parsable: {dbg_reply[:300]}",
                        )
                    except Exception:
                        pass
                continue

            sugg = suggestions[0]
            log_fn(f"  📌 {sugg['description'][:70]}")

            # Valider syntaxe — OBLIGATOIRE
            if not sugg["syntax_ok"]:
                _, syn_err = validate_python_syntax(sugg["code"])
                log_fn(f"  [red]✗ Syntaxe invalide : {syn_err}[/]")
                mem.syntax_errors.append(f"[v{ver_before}] {syn_err}")
                mem.record_failure(f"B1-i{i}: syntax error — {syn_err[:50]}")
                stall_count += 1
                continue

            # Détecter patch identique
            if sugg["code"].strip() == code.strip():
                log_fn("  [yellow]⚠ Patch identique — ignoré.[/]")
                mem.record_failure(f"B1-i{i}: patch identique")
                stall_count += 1
                continue

            diff_sum = compute_diff_summary(code, sugg["code"])
            log_fn(f"  📝 {diff_sum.splitlines()[0]}")

            # Appliquer
            new_path = await on_patch(
                sugg["code"],
                f"fix(v{ver_before}→B1-i{i}): {sugg['description'][:60]}",
                False,
            )
            if not new_path:
                log_fn("  [red]❌ on_patch échoué.[/]")
                stall_count += 1
                continue

            # ── Mesurer la progression réelle ─────────────────────────────
            ver_after = vm.current_version
            new_code = vm.get_current_code()
            errors_new = count_real_errors(new_code)
            quality_new = score_code_quality(new_code)
            pl_new = await pylint_score(new_code)  # Point 1 : pylint réel

            log_fn(
                f"  [bold]v{ver_before} → v{ver_after}[/]  "
                f"erreurs: {errors_now}→{errors_new}  "
                f"qualité: {quality}→{quality_new}  "
                f"pylint: {pl_new:.1f}/10"
            )

            progressed = errors_new < errors_now or pl_new > (mem.best_pylint_score + 0.3)

            if progressed:
                log_fn("  [green]✅ Progression confirmée[/]")
                mem.record_success(sugg["description"])
                mem.record_version(ver_after, errors_new, pl_new, sugg["description"], "ok")
                stall_count = 0
            else:
                log_fn("  [yellow]⚠ Pas de progression mesurable[/]")
                mem.record_failure(sugg["description"])
                mem.record_version(ver_after, errors_new, pl_new, sugg["description"], "fail")
                stall_count += 1

            # Alimenter RAG
            if rag:
                try:
                    await rag.add_session_message(
                        "improvement_loop",
                        "b1_result",
                        f"[v{ver_before}→v{ver_after}] {sugg['description']} "
                        f"| {errors_now}→{errors_new} erreurs | pylint={pl_new:.1f}",
                    )
                    state.rag_error_docs.append({"id": f"b1_i{i}", "version": ver_after, "errors": errors_new})
                except Exception:
                    pass

            state.iterations.append(
                LoopIteration(
                    i,
                    1,
                    ver_before,
                    ver_after,
                    errors_now,
                    errors_new,
                    success=progressed,
                    notes=diff_sum.splitlines()[0],
                )
            )

            # ── on_restart : appelé après chaque patch réussi ─────────────
            # (de TON code — permet os.execv() pour redémarrer le processus)
            if new_path and on_restart:
                try:
                    if asyncio.iscoroutinefunction(on_restart):
                        await on_restart()
                    else:
                        on_restart()
                except Exception as e:
                    logger.warning(f"on_restart: {e}")

            # Rollback intelligent si stagnation (Point 3 : can_rollback_to)
            if stall_count >= self.STALL_LIMIT:
                if mem.best_version and mem.best_version != ver_after:
                    # Point 3 : vérifier avant rollback
                    if vm.can_rollback_to(mem.best_version):
                        log_fn(f"  [yellow]⟳ Stagnation → rollback v{mem.best_version} ({mem.best_error_count} err)[/]")
                        vm.rollback(mem.best_version)
                        mem.record_failure(f"B1 stagnation à v{ver_after}")
                        state.total_failures += 1
                        stall_count = 0
                    else:
                        log_fn(f"  [yellow]⚠ v{mem.best_version} inaccessible pour rollback — continue[/]")
                        stall_count = 0
                else:
                    stall_count = 0

        log_fn(f"[red]❌ B1 : {self.MAX_ITER} itérations sans code propre.[/]")
        state.total_failures += 1
        return False, state


# =============================================================================
# BOUCLE 2 — FORK GUIDÉ PAR MÉMOIRE
# =============================================================================


class ForkEstimLoop:
    """
    Rollback vers best_version connue → STRATÈGE approche radicalement différente
    → DEBUGGER valide → applique.
    Point 3 : can_rollback_to() vérifié avant rollback.
    """

    MAX_ITER = 4

    def __init__(self, orc: RoleOrchestrator, ollama_url: str):
        self.orc = orc
        self.ollama_url = ollama_url

    async def run(
        self,
        vm,
        rag,
        state: LoopState,
        log_fn: Callable,
        on_patch: Callable,
        on_restart: Optional[Callable] = None,
    ) -> Tuple[bool, LoopState]:

        log_fn("\n[bold #f0883e]━━━ BOUCLE 2 : Fork / Estim ━━━[/]")
        mem = state.memory

        # Rollback vers meilleure version connue (Point 3 : can_rollback_to)
        if mem.best_version and vm.can_rollback_to(mem.best_version):
            log_fn(
                f"  ↩ Rollback vers v{mem.best_version} "
                f"({mem.best_error_count} erreurs, "
                f"pylint={mem.best_pylint_score:.1f})"
            )
            vm.rollback(mem.best_version)
        elif mem.best_version:
            log_fn(f"  [yellow]⚠ v{mem.best_version} inaccessible — continuation depuis v{vm.current_version}[/]")
        else:
            log_fn("  [yellow]⚠ Pas de meilleure version connue.[/]")

        assignments = await self.orc.assign_roles(2, False, log_fn)
        stratege = assignments.get(AgentRole.STRATEGE)
        debugger = assignments.get(AgentRole.DEBUGGER) or stratege
        if not stratege:
            log_fn("[red]❌ Aucun STRATÈGE disponible.[/]")
            return False, state

        for i in range(1, self.MAX_ITER + 1):
            state.loop2_iterations += 1
            code = vm.get_current_code()
            ver_before = vm.current_version
            errors_now = count_real_errors(code)
            ctx = mem.build_prompt_context(_ctx_limit(stratege))

            log_fn(f"\n[dim]── B2 fork {i}/{self.MAX_ITER} [bold]v{ver_before}[/] — {errors_now} erreurs[/]")

            rag_ctx = ""
            if rag:
                try:
                    docs = await rag.search(ROLE_RAG_QUERIES[AgentRole.STRATEGE], k=3)
                    rag_ctx = "\n".join(d["content"][:250] for d in docs)
                    for d in docs:
                        mem.add_rag(d["content"])
                except Exception:
                    pass

            log_fn(f"  🏗 STRATÈGE [{stratege}]…")
            prompt_fork = f"""{ROLE_SYSTEM_PROMPTS[AgentRole.STRATEGE]}

╔══ CONTEXTE SESSION ══╗
{ctx}
╚══════════════════════╝

VERSION ACTUELLE : v{ver_before} — {errors_now} erreurs
{("CONTEXTE RAG :\n" + rag_ctx) if rag_ctx else ""}

MISSION : Approche ARCHITECTURALEMENT DIFFÉRENTE.
Ne répète PAS les patterns ✗ ci-dessus.
Code Python COMPLET dans ```python.

CODE ACTUEL (v{ver_before}) :
```python
{code[:6000]}
```"""

            fork_reply = await _call_model(stratege, prompt_fork, self.ollama_url, timeout=240)
            if not fork_reply:
                log_fn("  [red]❌ STRATÈGE timeout.[/]")
                mem.record_failure(f"B2-i{i}: STRATÈGE vide")
                state.total_failures += 1
                continue

            proposal = AuditParser.extract_suggestions(fork_reply)
            prop_code = proposal[0]["code"] if proposal else None
            if not prop_code:
                # Fallback : bloc python direct
                m = re.search(r"```python\n(.*?)\n```", fork_reply, re.DOTALL)
                prop_code = m.group(1).strip() if m else None

            if not prop_code:
                log_fn("  [red]❌ Pas de code extractible.[/]")
                mem.record_failure(f"B2-i{i}: pas de code STRATÈGE")
                state.total_failures += 1
                continue

            ok, syn_err = validate_python_syntax(prop_code)
            if not ok:
                log_fn(f"  [red]✗ Syntaxe invalide : {syn_err}[/]")
                mem.syntax_errors.append(f"[B2 v{ver_before}] {syn_err}")
                mem.record_failure(f"B2-i{i}: syntax error")
                state.total_failures += 1
                continue

            if prop_code.strip() == code.strip():
                log_fn("  [yellow]⚠ Proposition identique — ignorée.[/]")
                mem.record_failure(f"B2-i{i}: identique")
                continue

            errors_prop = count_real_errors(prop_code)
            diff_sum = compute_diff_summary(code, prop_code)

            # DEBUGGER valide (Point 3 : explicite)
            log_fn(f"  🔧 DEBUGGER [{debugger}] valide ({errors_prop} erreurs prop)…")
            ctx_dbg = mem.build_prompt_context(_ctx_limit(debugger))
            prompt_val = f"""{ROLE_SYSTEM_PROMPTS[AgentRole.DEBUGGER]}

CONTEXTE : {ctx_dbg}

Original : v{ver_before} — {errors_now} erreurs
Proposition : {errors_prop} erreurs | {diff_sum.splitlines()[0]}

RÉPONDS SUR LA PREMIÈRE LIGNE :
  APPROUVÉ  — si meilleure et valide
  REJETÉ : [raison]

```python (original)
{code[:1500]}
```

```python (proposition)
{prop_code[:2500]}
```"""

            val_reply = await _call_model(debugger, prompt_val, self.ollama_url, timeout=120)
            approved = bool(val_reply and re.search(r"\bAPPROUV[EÉ]\b", val_reply, re.IGNORECASE))

            if not approved:
                m = re.search(r"rejet[eé][^:]*:\s*(.{5,120})", val_reply or "", re.IGNORECASE)
                reason = m.group(1).strip() if m else (val_reply or "")[:80]
                log_fn(f"  [yellow]⚠ Rejeté : {reason}[/]")
                mem.record_failure(f"B2-i{i}: rejeté — {reason[:50]}")
                state.total_failures += 1
                continue

            new_path = await on_patch(
                prop_code,
                f"feat(v{ver_before}→B2-fork{i}): approche alternative",
                major=True,
            )
            if new_path:
                ver_after = vm.current_version
                errors_new = count_real_errors(vm.get_current_code())
                pl_new = await pylint_score(vm.get_current_code())
                log_fn(
                    f"  [green]✅ v{ver_before}→v{ver_after} "
                    f"({errors_now}→{errors_new} erreurs, pylint={pl_new:.1f})[/]"
                )
                mem.record_version(ver_after, errors_new, pl_new, f"fork B2-i{i}", "ok")
                mem.record_success(f"fork B2-i{i}")
                state.last_successful_version = ver_after
                state.iterations.append(
                    LoopIteration(
                        i,
                        2,
                        ver_before,
                        ver_after,
                        errors_now,
                        errors_new,
                        success=True,
                        notes=diff_sum.splitlines()[0],
                    )
                )
                # on_restart (de TON code)
                if on_restart:
                    try:
                        if asyncio.iscoroutinefunction(on_restart):
                            await on_restart()
                        else:
                            on_restart()
                    except Exception as e:
                        logger.warning(f"on_restart B2: {e}")
                if rag:
                    try:
                        await rag.add_session_message(
                            "improvement_loop",
                            "b2_ok",
                            f"[v{ver_before}→v{ver_after}] fork réussi "
                            f"{errors_now}→{errors_new} err pylint={pl_new:.1f}",
                        )
                    except Exception:
                        pass
                return True, state

            log_fn("  [red]❌ on_patch échoué.[/]")
            state.total_failures += 1

        log_fn("[red]❌ B2 : aucun fork validé.[/]")
        state.total_failures += 1
        return False, state


# =============================================================================
# BOUCLE 3 — DÉBAT COLLÉGIAL AUTO-APPRENANT
# =============================================================================


class CollegialDebateLoop:
    """
    Propositions parallèles → COMPARATEUR note → JUGE synthèse.
    Toute la mémoire de session injectée dans chaque prompt.
    Point 3 : validation avant application.
    """

    MAX_ROUNDS = 3

    def __init__(self, orc: RoleOrchestrator, ollama_url: str):
        self.orc = orc
        self.ollama_url = ollama_url

    async def run(
        self,
        vm,
        rag,
        state: LoopState,
        log_fn: Callable,
        on_patch: Callable,
        on_restart: Optional[Callable] = None,
    ) -> Tuple[bool, LoopState]:

        log_fn("\n[bold #3fb950]━━━ BOUCLE 3 : Débat Collégial ━━━[/]")
        mem = state.memory
        n_part = min(5, 2 + state.total_failures)
        log_fn(
            f"  Participants : {n_part} | "
            f"Mémoire : {len(mem.version_history)} versions, "
            f"{len(mem.failed_approaches)} échecs"
        )

        assignments = await self.orc.assign_roles(3, False, log_fn)

        for round_n in range(1, self.MAX_ROUNDS + 1):
            state.loop3_iterations += 1
            code = vm.get_current_code()
            ver_before = vm.current_version
            errors_now = count_real_errors(code)
            ctx = mem.build_prompt_context(2500)

            log_fn(f"\n[dim]── B3 round {round_n}/{self.MAX_ROUNDS} [bold]v{ver_before}[/] — {errors_now} erreurs[/]")

            rag_ctx = ""
            if rag:
                try:
                    docs = await rag.search("amélioration correction erreurs code", k=3)
                    rag_ctx = "\n".join(d["content"][:200] for d in docs)
                except Exception:
                    pass

            # ── Phase 1 : propositions parallèles ────────────────────────
            debater_roles = [AgentRole.ANALYSTE, AgentRole.DEBUGGER, AgentRole.STRATEGE][:n_part]

            # Capture explicite pour éviter bug de closure
            _code_snap = code
            _ver_snap = ver_before

            async def _propose(
                role: AgentRole, code_snap: str = _code_snap, ver_snap: str = _ver_snap
            ) -> Tuple[str, Optional[str], str]:
                model = assignments.get(role)
                if not model:
                    return role.value, None, "?"
                role_rag = ""
                if rag:
                    try:
                        docs = await rag.search(ROLE_RAG_QUERIES[role], k=2)
                        role_rag = "\n".join(d["content"][:200] for d in docs)
                    except Exception:
                        pass
                role_ctx = mem.build_prompt_context(_ctx_limit(model))
                prompt = f"""{ROLE_SYSTEM_PROMPTS[role]}

CONTEXTE SESSION :
{role_ctx}

VERSION : v{ver_snap} — {errors_now} erreurs
{("RAG :\n" + role_rag) if role_rag else ""}
{("CONTEXTE GLOBAL :\n" + rag_ctx) if rag_ctx else ""}

Propose ta meilleure correction. Code COMPLET dans ```python.
N'utilise PAS les approches ✗.

```python
{code_snap[:5000]}
```"""
                reply = await _call_model(model, prompt, self.ollama_url, timeout=200)
                return role.value, reply, model

            log_fn(f"  📝 {len(debater_roles)} propositions en parallèle…")
            t0 = time.perf_counter()
            raw = await asyncio.gather(*[_propose(r) for r in debater_roles], return_exceptions=True)
            log_fn(f"  ⏱ {time.perf_counter() - t0:.1f}s")

            proposals: Dict[str, Tuple[str, str]] = {}
            for res in raw:
                if isinstance(res, Exception):
                    continue
                rname, reply, model_used = res
                if not reply:
                    log_fn(f"  [yellow]⚠ {rname.upper()} : vide[/]")
                    continue
                suggs = AuditParser.extract_suggestions(reply)
                extracted = suggs[0]["code"] if suggs else None
                if not extracted:
                    m = re.search(r"```python\n(.*?)\n```", reply, re.DOTALL)
                    extracted = m.group(1).strip() if m else None
                if not extracted:
                    continue
                ok, syn_err = validate_python_syntax(extracted)
                if not ok:
                    log_fn(f"  [red]✗ {rname.upper()} syntaxe : {syn_err}[/]")
                    mem.syntax_errors.append(f"[B3-r{round_n} {rname}] {syn_err}")
                    continue
                if extracted.strip() == code.strip():
                    log_fn(f"  [yellow]⚠ {rname.upper()} : identique — ignoré[/]")
                    continue
                ep = count_real_errors(extracted)
                proposals[rname] = (extracted, model_used)
                log_fn(f"  ✓ {rname.upper():12} [{model_used}] → {ep} erreurs")

            if not proposals:
                log_fn("  [red]❌ Aucune proposition valide ce round.[/]")
                mem.record_failure(f"B3-r{round_n}: zéro proposition valide")
                continue

            # ── Phase 2 : COMPARATEUR ─────────────────────────────────────
            comparateur = assignments.get(AgentRole.COMPARATEUR)
            scores: List[Tuple[str, float, int]] = []

            for rname, (prop_code, model_used) in proposals.items():
                ep = count_real_errors(prop_code)
                qp = score_code_quality(prop_code)
                llm_score = 50.0
                if comparateur:
                    prompt_cmp = (
                        f"{ROLE_SYSTEM_PROMPTS[AgentRole.COMPARATEUR]}\n\n"
                        f"v{ver_before} — {errors_now} erreurs actuelles\n"
                        f"Proposition {rname.upper()} : {ep} erreurs, qualité={qp}/100\n\n"
                        f"```python\n{prop_code[:2000]}\n```\n\n"
                        f"Score entier [0-100] uniquement."
                    )
                    r = await _call_model(comparateur, prompt_cmp, self.ollama_url, timeout=60)
                    sm = re.search(r"\b(\d{1,3})\b", r or "")
                    if sm:
                        llm_score = float(sm.group())
                heuristic = max(0.0, 100.0 - ep * 5.0) * 0.4 + qp * 0.3
                final = llm_score * 0.3 + heuristic
                scores.append((rname, final, ep))
                log_fn(f"    {rname:12} score={final:.1f} (LLM={llm_score:.0f} err={ep})")

            scores.sort(key=lambda x: x[1], reverse=True)
            winner_name = scores[0][0]
            winner_errors = scores[0][2]
            winner_code = proposals[winner_name][0]
            winner_model = proposals[winner_name][1]
            log_fn(f"\n  🏆 [bold]{winner_name.upper()}[/] [{winner_model}] — {winner_errors} erreurs")

            # ── Phase 3 : JUGE ────────────────────────────────────────────
            juge = assignments.get(AgentRole.JUGE)
            final_code = winner_code

            if juge:
                log_fn(f"  ⚖ JUGE [{juge}]…")
                all_txt = "\n\n".join(
                    f"=== {rn.upper()} ({count_real_errors(c)} err) ===\n```python\n{c[:1200]}\n```"
                    for rn, (c, _) in proposals.items()
                )
                scores_txt = "\n".join(f"  {rn:12} score={sc:.1f} erreurs={er}" for rn, sc, er in scores)
                juge_ctx = mem.build_prompt_context(_ctx_limit(juge))
                prompt_juge = f"""{ROLE_SYSTEM_PROMPTS[AgentRole.JUGE]}

CONTEXTE SESSION :
{juge_ctx}

VERSION : v{ver_before} — {errors_now} erreurs

VOTES :
{scores_txt}

GAGNANT : {winner_name.upper()} ({winner_errors} erreurs)

PROPOSITIONS :
{all_txt}

MISSION : Code final combinant le meilleur de chaque.
Évite les patterns ✗. Moins de {errors_now} erreurs.
Code dans ```python."""

                juge_reply = await _call_model(juge, prompt_juge, self.ollama_url, timeout=240)
                if juge_reply:
                    jsuggs = AuditParser.extract_suggestions(juge_reply)
                    jcode = jsuggs[0]["code"] if jsuggs else None
                    if not jcode:
                        m = re.search(r"```python\n(.*?)\n```", juge_reply, re.DOTALL)
                        jcode = m.group(1).strip() if m else None
                    if jcode:
                        ok, syn_err = validate_python_syntax(jcode)
                        if ok:
                            je = count_real_errors(jcode)
                            if je <= winner_errors:
                                final_code = jcode
                                log_fn(f"  → Verdict juge adopté ({je} erreurs)")
                            else:
                                log_fn(f"  → Verdict juge pire ({je}>{winner_errors}) — gardé vote")
                        else:
                            log_fn(f"  [yellow]⚠ Juge syntaxe invalide : {syn_err}[/]")
                            mem.syntax_errors.append(f"[B3 juge r{round_n}] {syn_err}")

            # Point 3 : vérifier que final_code est meilleur avant d'appliquer
            final_errors = count_real_errors(final_code)
            if final_errors >= errors_now:
                log_fn(f"  [yellow]⚠ Verdict ({final_errors}) pas meilleur ({errors_now}) — skip.[/]")
                mem.record_failure(f"B3-r{round_n}: verdict régressif")
                continue

            diff_sum = compute_diff_summary(code, final_code)
            new_path = await on_patch(
                final_code,
                f"feat(v{ver_before}→B3-r{round_n}): débat collégial ({errors_now}→{final_errors} erreurs)",
                major=True,
            )
            if new_path:
                ver_after = vm.current_version
                pl_new = await pylint_score(vm.get_current_code())
                log_fn(
                    f"  [green]✅ v{ver_before}→v{ver_after} "
                    f"({errors_now}→{final_errors} erreurs, pylint={pl_new:.1f})[/]"
                )
                mem.record_version(ver_after, final_errors, pl_new, f"débat r{round_n}", "ok")
                mem.record_success(f"B3 r{round_n} gagnant={winner_name}")
                state.last_successful_version = ver_after
                state.iterations.append(
                    LoopIteration(
                        round_n,
                        3,
                        ver_before,
                        ver_after,
                        errors_now,
                        final_errors,
                        success=True,
                        notes=diff_sum.splitlines()[0],
                    )
                )
                # on_restart (de TON code)
                if on_restart:
                    try:
                        if asyncio.iscoroutinefunction(on_restart):
                            await on_restart()
                        else:
                            on_restart()
                    except Exception as e:
                        logger.warning(f"on_restart B3: {e}")
                if rag:
                    try:
                        await rag.add_session_message(
                            "improvement_loop",
                            "b3_ok",
                            f"[v{ver_before}→v{ver_after}] débat r{round_n} "
                            f"gagnant={winner_name} {errors_now}→{final_errors} err",
                        )
                    except Exception:
                        pass
                return True, state

        log_fn("[red]❌ B3 : aucun consensus appliqué.[/]")
        state.total_failures += 1
        return False, state


# =============================================================================
# ORCHESTRATEUR
# =============================================================================


class ImprovementOrchestrator:
    """
    Chaîne B1 → B2 → B3 avec mémoire partagée.
    on_restart propagé à chaque boucle.
    """

    def __init__(self, ollama_url: str, ollama_tags_url: str):
        self.orc = RoleOrchestrator(ollama_url, ollama_tags_url)
        self.loop1 = AutoRepairLoop(self.orc, ollama_url)
        self.loop2 = ForkEstimLoop(self.orc, ollama_url)
        self.loop3 = CollegialDebateLoop(self.orc, ollama_url)
        self.state = LoopState()
        self._running = False

    async def run(
        self,
        vm,
        rag,
        log_fn: Callable = print,
        on_done: Optional[Callable] = None,
        on_restart: Optional[Callable] = None,  # de TON code
    ) -> LoopState:

        if self._running:
            log_fn("[yellow]⚠ Déjà en cours.[/]")
            return self.state

        self._running = True
        # Charger mémoire persistée si disponible (Point 2)
        self.state = LoopState(memory=ErrorMemory.load())

        initial_version = vm.current_version
        initial_errors = count_real_errors(vm.get_current_code())
        self.state.memory.record_version(initial_version, initial_errors, 0.0, "départ", "init")

        log_fn("\n[bold #58a6ff]╔═════════════════════════════════════════════╗[/]")
        log_fn("[bold #58a6ff]║  🔄 AMÉLIORATION AUTONOME AUTO-APPRENANTE   ║[/]")
        log_fn("[bold #58a6ff]╚═════════════════════════════════════════════╝[/]")
        log_fn(f"  Version départ    : v{initial_version}")
        log_fn(f"  Erreurs initiales : {initial_errors}")
        log_fn(f"  Mémoire chargée   : {len(self.state.memory.version_history)} versions connues")

        models = await self.orc.discover_models()
        log_fn(f"  Modèles : {', '.join(models[:6])}{'…' if len(models) > 6 else ''}")

        async def on_patch(code, desc, major=False):
            return await vm.prepare_patch(code, desc, major=major)

        try:
            ok1, self.state = await self.loop1.run(vm, rag, self.state, log_fn, on_patch, on_restart)
            if ok1:
                log_fn("\n[bold green]🎉 Succès en Boucle 1 ![/]")
            else:
                log_fn(
                    f"\n[yellow]⟳ B1 insuffisante ({len(self.state.memory.failed_approaches)} échecs connus) → B2[/]"
                )
                ok2, self.state = await self.loop2.run(vm, rag, self.state, log_fn, on_patch, on_restart)
                if ok2:
                    log_fn(
                        f"\n[cyan]⟳ B2 réussie → relance B1 "
                        f"(mémoire : {len(self.state.memory.version_history)} versions)[/]"
                    )
                    ok1b, self.state = await self.loop1.run(vm, rag, self.state, log_fn, on_patch, on_restart)
                    if not ok1b:
                        log_fn("[yellow]⚠ B1 relancée insuffisante → B3[/]")
                        await self.loop3.run(vm, rag, self.state, log_fn, on_patch, on_restart)
                else:
                    log_fn("\n[red]⟳ B1+B2 insuffisantes → B3 (débat)[/]")
                    await self.loop3.run(vm, rag, self.state, log_fn, on_patch, on_restart)

        except asyncio.CancelledError:
            log_fn("\n[yellow]⚠ Interrompu.[/]")
        except Exception as e:
            log_fn(f"\n[red]❌ Erreur : {e}[/]")
            logger.exception("ImprovementOrchestrator.run")
        finally:
            self._running = False

        # Rapport final
        s = self.state
        mem = s.memory
        total = s.loop1_iterations + s.loop2_iterations + s.loop3_iterations
        final_errors = count_real_errors(vm.get_current_code())
        delta = initial_errors - final_errors

        log_fn(
            f"\n[bold]━━━ Rapport final ━━━[/]\n"
            f"  v{initial_version} → v{vm.current_version}\n"
            f"  Erreurs : {initial_errors} → {final_errors} "
            f"({'[green]-' + str(delta) if delta > 0 else '[red]+' + str(-delta)}[/])\n"
            f"  Itérations : {total} (B1:{s.loop1_iterations} "
            f"B2:{s.loop2_iterations} B3:{s.loop3_iterations})\n"
            f"  Versions testées : {len(mem.version_history)}\n"
            f"  Succès mémorisés : {len(mem.successful_fixes)}\n"
            f"  Échecs mémorisés : {len(mem.failed_approaches)}\n"
            f"  Patches invalides bloqués : {len(mem.syntax_errors)}\n"
            f"  Mémoire persistée : {MEMORY_FILE}"
        )

        if on_done:
            try:
                if asyncio.iscoroutinefunction(on_done):
                    await on_done(self.state)
                else:
                    on_done(self.state)
            except Exception:
                pass

        return self.state

    def stop(self):
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running
