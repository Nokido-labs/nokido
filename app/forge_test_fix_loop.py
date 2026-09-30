"""
app/forge_test_fix_loop.py — Software creator test-fix loop autonome.
====================================================================
Lancement de tests, parsing d'erreurs, patch via AST et LLM local (laforge-qwen).
"""

from __future__ import annotations
import ast
import asyncio
import logging
import subprocess
import sys
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

# Racine du projet
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from nokido_agent.app.forge_python_bin import LAFORGE_PYTHON
except ImportError:
    LAFORGE_PYTHON = sys.executable

logger = logging.getLogger("Nokido.TestFixLoop")


@dataclass
class FixResult:
    """Résultat d'une session de test-fix."""

    ok: bool
    iterations: int
    final_code: str
    history: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


class TestFixLoop:
    """Moteur de boucle fermée Tests -> Erreurs -> Patch -> Tests."""

    def __init__(self, max_iterations: int = 3, provider: str = "ollama_local"):
        self.max_iterations = max_iterations
        self.provider = provider

    def run_pytest(self, test_path: str) -> Dict[str, Any]:
        """
        Exécute pytest sur le chemin spécifié et capture les échecs structurés.
        """
        cmd = [LAFORGE_PYTHON, "-m", "pytest", "-v", "--tb=short", str(test_path)]
        logger.info(f"Running tests: {' '.join(cmd)}")

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            ok = r.returncode == 0
            stdout = r.stdout
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "failures": [{"test": "timeout", "traceback": "Pytest timed out after 60s"}],
                "raw": "",
            }

        failures = []
        if not ok:
            # Parsing simple du traceback pytest pour extraire les tests en échec
            # Pattern standard pytest: _________________ test_name _________________
            sections = re.split(r"_+ (test_[a-zA-Z0-9_]+) _+", stdout)
            if len(sections) > 1:
                for i in range(1, len(sections), 2):
                    test_name = sections[i]
                    # On prend le bloc après le nom du test jusqu'au prochain délimiteur ou fin
                    tb = sections[i + 1].split("----------------")[0].strip()
                    failures.append({"test": test_name, "traceback": tb})

            if not failures:
                # Fallback sur la sortie complète si le pattern n'a pas matché
                failures.append({"test": "unknown", "traceback": (stdout + r.stderr)[-2000:]})

        return {"ok": ok, "failures": failures, "raw": stdout[:5000]}

    async def get_llm_patch(self, file_path: str, code: str, failures: List[Dict[str, Any]]) -> str:
        """
        Appelle le LLM (laforge-qwen) pour proposer une correction.
        """
        try:
            from nokido_agent.app.forge_cognitive_router import route_task
        except ImportError:
            return code  # Fail silent si router absent

        failure_desc = "\n\n".join([f"Test: {f['test']}\nError: {f['traceback']}" for f in failures])

        prompt = f"""
        # TÂCHE: CORRECTION DE CODE PYTHON
        Le fichier '{file_path}' a échoué aux tests pytest. 
        
        ## ERREURS DÉTECTÉES:
        {failure_desc}
        
        ## CODE ACTUEL:
        ```python
        {code}
        ```
        
        ## INSTRUCTIONS:
        1. Analyse les erreurs et le code.
        2. Propose une version CORRIGÉE et COMPLÈTE du fichier.
        3. Garde les mêmes noms de fonctions et classes.
        4. Réponds UNIQUEMENT avec le code Python complet, sans texte explicatif.
        """

        payload = {"prompt": prompt, "provider": self.provider, "use_case": "code"}

        logger.info(f"Requesting patch from {self.provider}...")
        res_str = await route_task("llm_call", payload)

        # Nettoyage Markdown (on extrait le bloc de code)
        new_code = res_str
        if "```python" in res_str:
            new_code = res_str.split("```python")[1].split("```")[0].strip()
        elif "```" in res_str:
            new_code = res_str.split("```")[1].split("```")[0].strip()

        return new_code

    def apply_patch_ast(self, file_path: str, new_code: str) -> bool:
        """
        Valide la syntaxe via AST et réécrit le fichier via unparse pour normalisation.
        """
        try:
            tree = ast.parse(new_code)
            # Validation structurelle ok -> Réécriture
            final_code = ast.unparse(tree)
            Path(file_path).write_text(final_code, encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"AST validation/write failed for {file_path}: {e}")
            return False

    async def loop(self, module_path: str, test_path: str) -> FixResult:
        """
        Cycle autonome : Tests -> Fix -> Tests.
        """
        p_module = Path(module_path)
        if not p_module.exists():
            return FixResult(ok=False, iterations=0, final_code="", error="MODULE_NOT_FOUND")

        history = []
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1
            current_code = p_module.read_text(encoding="utf-8")

            # 1. Exécution des tests
            res_test = self.run_pytest(test_path)
            if res_test["ok"]:
                logger.info(f"Tests passed for {module_path} (Iteration {iteration - 1})")
                return FixResult(ok=True, iterations=iteration - 1, final_code=current_code, history=history)

            logger.warning(
                f"Tests failed (Iteration {iteration}/{self.max_iterations}): {len(res_test['failures'])} errors"
            )
            history.append({"iteration": iteration, "failures": res_test["failures"]})

            if iteration >= self.max_iterations:
                break

            # 2. Demande de patch au LLM
            new_code = await self.get_llm_patch(module_path, current_code, res_test["failures"])

            # 3. Application et validation AST
            if not self.apply_patch_ast(module_path, new_code):
                return FixResult(
                    ok=False, iterations=iteration, final_code=current_code, history=history, error="AST_PARSE_FAILED"
                )

        return FixResult(
            ok=False, iterations=iteration, final_code=current_code, history=history, error="MAX_ITERATIONS_REACHED"
        )


async def run_test_fix_loop(module_path: str, test_path: str) -> FixResult:
    """
    API Publique pour déclencher la boucle de réparation autonome.
    """
    engine = TestFixLoop()
    return await engine.loop(module_path, test_path)


if __name__ == "__main__":
    # Test unitaire rapide si lancé en direct
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 2:
        asyncio.run(run_test_fix_loop(sys.argv[1], sys.argv[2]))
    else:
        print("Usage: python forge_test_fix_loop.py <module_path> <test_path>")
