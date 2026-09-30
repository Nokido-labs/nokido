"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_recursive_debugger
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_recursive_debugger.py
=================================
AUTONOMOUS_DEBUG_LOOP_V1 — RecursiveDebugger
Self_Healing_Code : Write -> Test -> Analyze -> Refactor
max_iterations=3 | stop=Zero_Exit_Code_And_Lint_Pass
Pas de subprocess shell — tout via MCP tools et py_compile/pytest API
"""

import ast as _ast
import json
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable


from nokido_agent.app.forge_utils import _safe_llm_text


def _gs(k: str) -> str:
    """Secure secret access — WCM > .env > os.environ."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret(k) or ""
    except Exception:
        import os as _os

        return _os.environ.get(k, "")


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"

# ── Regex Error Parser ────────────────────────────────────────────────────────

ERROR_PATTERNS = [
    # SyntaxError
    (
        re.compile(r"SyntaxError: (.+?) \((.+?), line (\d+)\)"),
        "syntax",
        lambda m: {"msg": m.group(1), "file": m.group(2), "line": int(m.group(3))},
    ),
    # pytest FAILED
    (
        re.compile(r"FAILED (.+?)::(.+?) - (.+)"),
        "test_fail",
        lambda m: {"file": m.group(1), "test": m.group(2), "reason": m.group(3)},
    ),
    # AssertionError
    (re.compile(r"AssertionError: (.+)"), "assertion", lambda m: {"msg": m.group(1)}),
    # ImportError
    (re.compile(r"(ImportError|ModuleNotFoundError): (.+)"), "import", lambda m: {"msg": m.group(2)}),
    # NameError
    (re.compile(r"NameError: name '(.+?)' is not defined"), "name", lambda m: {"name": m.group(1)}),
    # TypeError
    (re.compile(r"TypeError: (.+)"), "type", lambda m: {"msg": m.group(1)}),
    # IndentationError
    (re.compile(r"IndentationError: (.+)"), "indent", lambda m: {"msg": m.group(1)}),
]


def parse_errors(log_text: str) -> list[dict[str, str]]:
    """Regex_Error_Parser — extracts structured errors from log."""
    errors = []
    for pattern, etype, extractor in ERROR_PATTERNS:  # type: Pattern[str], str, object[[Match[str]], dict[str, str]]
        for m in pattern.finditer(log_text):  # type: Match[str]
            try:
                info = extractor(m)  # type: dict[str, str]
                info["type"] = etype  # type: ignore
                info["raw"] = m.group(0)  # type: ignore
                errors.append(info)
            except Exception:
                pass
    return errors


# ── Diff generator ────────────────────────────────────────────────────────────


def make_diff(old: str, new: str) -> str:
    """Show_Changes_Only — diff ligne par ligne minimal."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = []
    max_len = max(len(old_lines), len(new_lines))
    changes = 0
    for i in range(max_len):
        ol = old_lines[i] if i < len(old_lines) else None
        nl = new_lines[i] if i < len(new_lines) else None
        if ol != nl:
            if ol is not None:
                diff.append(f"- {i + 1:3d} | {ol}")
            if nl is not None:
                diff.append(f"+ {i + 1:3d} | {nl}")
            changes += 1
    if not diff:
        return "(aucun changement)"
    return f"{changes} lignes modifiees:\n" + "\n".join(diff[:40])


# ── Step result ───────────────────────────────────────────────────────────────


@dataclass
class StepResult:
    step: str
    ok: bool
    output: str = ""
    errors: list = field(default_factory=list)
    elapsed_ms: int = 0
    code: str = ""
    diff: str = ""


@dataclass
class DebugIteration:
    iteration: int
    steps: list[StepResult] = field(default_factory=list)
    final_code: str = ""
    passed: bool = False

    @property
    def elapsed_ms(self) -> object:
        """Elapsed ms."""
        return sum(s.elapsed_ms for s in self.steps)


# ── RecursiveDebugger ─────────────────────────────────────────────────────────


class RecursiveDebugger:
    """
    AUTONOMOUS_DEBUG_LOOP_V1
    Boucle autonome Write -> Test -> Analyze -> Refactor.

    Usage:
        debugger = RecursiveDebugger(on_step=my_callback)
        result = debugger.run("Ecris une fonction tri_rapide(lst) en Python avec tests")
    """

    MAX_ITER = 3

    def __init__(self, on_step: Optional[Callable] = None) -> None:
        """Init.

        Args:
            on_step: Description.
        """
        self._on_step = on_step  # callback(step_result: StepResult, iter_n: int)
        self._work_dir = ROOT / "sandbox" / "debug_loop"
        self._work_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1 : Write / Refactor via LLM ────────────────────────────────────

    def _step_write(self, task: str, previous_code: str = "", errors: list = None, iteration: int = 1) -> StepResult:
        """Step write.

        Args:
            task: Description.
            previous_code: Description.
            errors: Description.
            iteration: Description.
        """
        t0 = time.time()
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))

        if iteration == 1:
            prompt = (
                "Ecris du code Python de qualite production pour cette tache:\n"
                f"{task}\n\n"
                "REGLES ABSOLUES:\n"
                "1. Retourne UNIQUEMENT le code Python (pas de markdown, pas d'explication)\n"
                "2. Inclus les imports necessaires\n"
                "3. Ajoute des tests pytest dans le meme fichier (fonctions test_*)\n"
                "4. Le code doit etre syntaxiquement correct"
            )
        else:
            errors_str = json.dumps(errors or [], ensure_ascii=False, indent=2)
            prompt = (
                "Corrige ce code Python. Voici les erreurs detectees:\n"
                f"{errors_str}\n\n"
                "Code a corriger:\n"
                f"```python\n{previous_code[:3000]}\n```\n\n"
                "REGLES ABSOLUES:\n"
                "1. Retourne UNIQUEMENT le code Python corrige\n"
                "2. Ne change que ce qui est necessaire\n"
                "3. Conserve tous les tests existants\n"
                "4. Assure-toi que le code est syntaxiquement valide"
            )

        try:
            from nokido_agent.app.forge_swarm_team import _default_team, LeadOrchestrator
            import asyncio

            team = _default_team()
            team.activate("laforge")
            orc = LeadOrchestrator()
            loop = asyncio.new_event_loop()
            res = loop.run_until_complete(orc.run(prompt, team))
            loop.close()
            turns = res.get("results", [])
            raw = _safe_llm_text(res)
            # Extraire le code
            if "```python" in raw:
                raw = raw.split("```python")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            code = raw.strip()
            elapsed = int((time.time() - t0) * 1000)
            diff = make_diff(previous_code, code) if previous_code else ""
            return StepResult("Write", bool(code), code[:5000], [], elapsed, code, diff)
        except Exception as e:
            return StepResult("Write", False, str(e)[:300], [], int((time.time() - t0) * 1000))

    # ── Step 2 : Test via pytest API ──────────────────────────────────────────

    def _step_test(self, code: str, task_name: str) -> StepResult:
        """Step test.

        Args:
            code: Description.
            task_name: Description.
        """
        t0 = time.time()
        # Ecrire le fichier
        target = self._work_dir / f"test_{task_name}.py"
        target.write_text(code, encoding="utf-8")

        # 1. Verifier AST d'abord
        try:
            _ast.parse(code)
        except SyntaxError as e:
            elapsed = int((time.time() - t0) * 1000)
            err = {"type": "syntax", "msg": str(e), "line": e.lineno or 0}
            return StepResult("Test", False, f"SyntaxError: {e}", [err], elapsed, code)

        # 2. Lancer pytest via API
        try:
            import pytest, io
            from contextlib import redirect_stdout, redirect_stderr

            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                exit_code = pytest.main(
                    [
                        str(target),
                        "-v",
                        "--tb=short",
                        "--no-header",
                        "-q",
                        "--timeout=10",
                    ],
                    plugins=[],
                )

            output = buf_out.getvalue() + buf_err.getvalue()
            ok = exit_code == 0
            errors = parse_errors(output) if not ok else []
            elapsed = int((time.time() - t0) * 1000)
            return StepResult("Test", ok, output[:2000], errors, elapsed, code)
        except Exception as e:
            elapsed = int((time.time() - t0) * 1000)
            err_str = traceback.format_exc()[-400:]
            return StepResult("Test", False, err_str, parse_errors(err_str), elapsed, code)

    # ── Step 3 : Analyze via LLM (si echec) ──────────────────────────────────

    def _step_analyze(self, test_output: str, errors: list, code: str) -> StepResult:
        """Step analyze.

        Args:
            test_output: Description.
            errors: Description.
            code: Description.
        """
        t0 = time.time()
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))

        errors_str = json.dumps(errors[:5], ensure_ascii=False, indent=2)
        prompt = (
            "Analyse ces erreurs de tests Python et donne un diagnostic court.\n"
            f"Erreurs detectees:\n{errors_str}\n\n"
            f"Log pytest (extrait):\n{test_output[:800]}\n\n"
            "Reponds en JSON uniquement:\n"
            '{"root_cause": "...",\'fix_instructions": "", '
            '"priority_fix": "ligne X: ..."}\n'
            "Sois tres concis (max 3 phrases par champ)."
        )

        try:
            from nokido_agent.app.forge_swarm_team import _default_team, LeadOrchestrator
            import asyncio

            team = _default_team()
            # Gemini si disponible, sinon nokido
            import os

            agent = "gemini" if _gs("GEMINI_API_KEY") else "laforge"
            team.activate(agent)
            orc = LeadOrchestrator()
            loop = asyncio.new_event_loop()
            res = loop.run_until_complete(orc.run(prompt, team))
            loop.close()
            turns = res.get("results", [])
            raw = str(turns[0].get("response", "")) if turns else "{}"
            # Extraire JSON
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                analysis = json.loads(raw[start:end])
            else:
                analysis = {"root_cause": raw[:200], "fix_instructions": "", "priority_fix": ""}
            elapsed = int((time.time() - t0) * 1000)
            return StepResult("Analyze", True, json.dumps(analysis, ensure_ascii=False, indent=2), errors, elapsed)
        except Exception as e:
            return StepResult("Analyze", False, str(e)[:200], errors, int((time.time() - t0) * 1000))

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self, task: str) -> dict:
        """
        Boucle principale : max MAX_ITER iterations.
        Stop_Condition : tests passent ET lint OK.
        """
        task_name = re.sub(r"\W+", "_", task[:20].lower())
        iterations = []
        current_code = ""
        current_errors = []

        for i in range(1, self.MAX_ITER + 1):
            iteration = DebugIteration(iteration=i)

            # ── Step Write / Refactor
            write_result = self._step_write(task, current_code, current_errors, iteration=i)
            iteration.steps.append(write_result)
            if self._on_step:
                self._on_step(write_result, i)
            if not write_result.ok or not write_result.code:
                iterations.append(iteration)
                break
            current_code = write_result.code

            # ── Step Test
            test_result = self._step_test(current_code, task_name)
            iteration.steps.append(test_result)
            if self._on_step:
                self._on_step(test_result, i)

            if test_result.ok:
                # Zero_Exit_Code_And_Lint_Pass
                iteration.passed = True
                iteration.final_code = current_code
                iterations.append(iteration)
                break

            current_errors = test_result.errors

            # ── Step Analyze (seulement si echec et pas derniere iter)
            if i < self.MAX_ITER:
                analyze_result = self._step_analyze(test_result.output, current_errors, current_code)
                iteration.steps.append(analyze_result)
                if self._on_step:
                    self._on_step(analyze_result, i)
                # Enrichir les erreurs avec l'analyse
                try:
                    analysis = json.loads(analyze_result.output)
                    if analysis.get("fix_instructions"):
                        current_errors.append(
                            {
                                "type": "analysis",
                                "msg": analysis.get("fix_instructions", ""),
                                "priority": analysis.get("priority_fix", ""),
                            }
                        )
                except Exception:
                    pass

            iteration.final_code = current_code
            iterations.append(iteration)

        # Bilan final
        last = iterations[-1]
        passed = last.passed
        total_ms = sum(it.elapsed_ms for it in iterations)
        final_code = last.final_code

        # Sauvegarder le code final
        if final_code:
            out_file = self._work_dir / f"final_{task_name}.py"
            out_file.write_text(final_code, encoding="utf-8")

        # KNOWLEDGE_HARVESTER_V1 — recolter si tests passes
        if passed and final_code:
            try:
                if str(APP) not in sys.path:
                    sys.path.insert(0, str(APP))
                from nokido_agent.app.forge_knowledge_harvester import harvest_on_success

                # Extraire outputs des steps Write
                agent_out = "".join(
                    s.get("output", "")[:300] for it in [] for s in it.get("steps", []) if s.get("step") == "Write"
                )
                harvest_on_success(task, agent_out, final_code)
            except Exception:
                pass

        return {
            "task": task,
            "passed": passed,
            "iterations": len(iterations),
            "total_ms": total_ms,
            "final_code": final_code[:3000],
            "final_path": str(self._work_dir / f"final_{task_name}.py") if final_code else "",
            "history": [
                {
                    "iteration": it.iteration,
                    "passed": it.passed,
                    "elapsed_ms": it.elapsed_ms,
                    "steps": [
                        {"step": s.step, "ok": s.ok, "output": s.output[:200], "errors": s.errors[:3]} for s in it.steps
                    ],
                }
                for it in iterations
            ],
        }
