from __future__ import annotations

# Import oublie, mesure le 2026-09-08 : asdict(s) L219.
from dataclasses import asdict

"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-05-05 | VER:v_forge_handler_build_v4
#FORGE:[score:92|agent:agt_gemini|temp:0.00|risk:0.20|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: boucle generate_code -> run_tests -> patch -> retry (max 3) + GOAP cable.
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:92|agent:agt_gemini|temp:0.00|risk:0.20|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"

import asyncio
import subprocess
import sys
import time
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# On s'assure que le path est correct pour les imports internes
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_python_bin import LAFORGE_PYTHON, run_python

logger = logging.getLogger("Nokido.Forge.Handler.Build")

ROOT_DIR = ROOT
APP_DIR = ROOT_DIR / "app"
TMPL_DIR = ROOT_DIR / "templates"


# -- Step runner ---------------------------------------------------------


def _step_read_resource(uri: str) -> str:
    """Reads a resource template from templates://xxx."""
    if uri.startswith("templates://"):
        name: str = uri.replace("templates://", "")
        tmpl: Path = TMPL_DIR / name
        if not tmpl.exists():
            return f"[ERR] Template not found: {name}"
        parts: list[str] = []
        for f in sorted(tmpl.iterdir()):
            if f.is_file():
                parts.append(f"=== {f.name} ===\n{f.read_text(encoding='utf-8', errors='ignore')}")
        return "\n\n".join(parts)
    return f"[ERR] Unsupported URI: {uri}"


def _step_write_file(path: str, content: str) -> str:
    """Ecrit un fichier de maniere securisee avec commit guard."""
    target = ROOT_DIR / path
    # Securite : interdire ecriture hors du projet
    try:
        target.resolve().relative_to(ROOT_DIR.resolve())
    except ValueError:
        return f"[BLOCKED] Chemin hors projet: {path}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    # Commit guard AST si .py
    if target.suffix == ".py":
        r = run_python(["-m", "py_compile", str(target)], cwd=str(ROOT_DIR), capture_output=True, encoding="utf-8")
        if r.returncode != 0:
            target.unlink()
            return f"[BLOCKED] SyntaxError: {r.stderr[:120]}"
    return f"[OK] {path} ({len(content)} chars)"


def _step_run_python(command: str, cwd: str = "") -> str:
    """Execute une commande Python locale (pytest, etc.)."""
    work_dir = ROOT_DIR / cwd if cwd else ROOT_DIR
    parts = command.split()
    # Securite : seulement pytest, python -m, py_compile
    allowed = ["pytest", "python", "python3"]
    if not parts or parts[0] not in allowed:
        # Si c'est juste "pytest", on remplace par [LAFORGE_PYTHON, "-m", "pytest"]
        if parts and parts[0] == "pytest":
            parts = [LAFORGE_PYTHON, "-m", "pytest"] + parts[1:]
        else:
            return f"[BLOCKED] Commande non autorisee: {parts[0] if parts else 'vide'}"

    # Utiliser LAFORGE_PYTHON si possible
    if parts[0] in ("python", "python3"):
        parts[0] = LAFORGE_PYTHON

    r = subprocess.run(parts, cwd=str(work_dir), capture_output=True, encoding="utf-8", errors="replace", timeout=60)
    out = (r.stdout + r.stderr)[:1000]
    status = "OK" if r.returncode == 0 else "FAIL"
    return f"[{status}] {out}"


async def _step_llm_generate(agent: str, task: str, context: str = "") -> str:
    """Appelle llm_generate via MCP Hub."""
    try:
        from nokido_agent.app.forge_cognitive_router import route_task

        # On utilise le router cognitif pour déléguer
        payload = {"prompt": (context + "\n\n" + task).strip() if context else task}
        res_str = await route_task("llm_call", payload)
        # On tente de parser la réponse si c'est du JSON stringifié
        try:
            res_json = json.loads(res_str)
            return res_json.get("result", res_str)
        except:
            return res_str
    except Exception as e:
        return f"[ERR] {e}"


# -- Loop logic ----------------------------------------------------------


async def build_with_retry_loop(
    project_name: str, goal: str, file_path: str, test_cmd: str, max_retries: int = 3
) -> Dict[str, Any]:
    """Boucle fermée: generate -> run test -> patch -> retry."""
    current_code = ""
    attempt = 0
    last_error = ""
    history = []

    while attempt <= max_retries:
        # 1. Generation ou Patch
        if attempt == 0:
            prompt = f"Génère le code complet pour le fichier '{file_path}' du projet '{project_name}'. Objectif: {goal}. Retourne UNIQUEMENT le code Python."
            current_code = await _step_llm_generate("Gemini", prompt)
        else:
            prompt = f"Le test a échoué avec l'erreur suivante:\n{last_error}\n\nCorrige le code de '{file_path}' pour corriger cette erreur. Retourne UNIQUEMENT le code Python complet."
            current_code = await _step_llm_generate("Gemini", prompt, context=f"Ancien code:\n{current_code}")

        # Nettoyage Markdown
        if "```python" in current_code:
            current_code = current_code.split("```python")[1].split("```")[0].strip()
        elif "```" in current_code:
            current_code = current_code.split("```")[1].split("```")[0].strip()

        # 2. Write & Validate AST
        res_write = _step_write_file(file_path, current_code)
        if "[BLOCKED]" in res_write:
            last_error = res_write
            history.append({"attempt": attempt, "ok": False, "error": last_error})
            attempt += 1
            continue

        # dep_manager: install missing imports before tests
        try:
            from nokido_agent.app.forge_dep_manager import manage as _dep_manage

            _dep_result = _dep_manage(str(ROOT_DIR / file_path))
            if not _dep_result.get("success") and _dep_result.get("missing_before"):
                logger.warning("[build] dep_manager failed to install %s", _dep_result["missing_before"])
        except Exception as _dep_e:
            logger.debug("[build] dep_manager skip: %s", _dep_e)

        # coherence-gate: log callers affected by this write
        try:
            from nokido_agent.app.forge_graph_linker import GraphLinker

            _callers = GraphLinker().get_impacted_by_change(file_path)
            if _callers:
                logger.info(
                    "[coherence-gate] %s modified -> %d callers: %s",
                    file_path,
                    len(_callers),
                    [c["source"] for c in _callers[:5]],
                )
        except Exception:
            pass

        # 3. Run Tests
        res_test = _step_run_python(test_cmd)
        if "[OK]" in res_test:
            # Commit Guard validation
            try:
                from nokido_agent.app.forge_commit_guard import CommitGuard

                guard = CommitGuard()
                g_res = guard.check([file_path])
                if not g_res.ok:
                    last_error = f"[COMMIT_BLOCK] {', '.join(g_res.blocks)}"
                    history.append({"attempt": attempt, "ok": False, "error": last_error})
                    attempt += 1
                    continue
                if g_res.warnings:
                    logger.warning("[build] Warnings detected: %s", g_res.warnings)
            except Exception as e:
                logger.error("[build] CommitGuard error: %s", e)

            history.append({"attempt": attempt, "ok": True})
            return {"ok": True, "code": current_code, "attempts": attempt, "history": history}

        last_error = res_test
        history.append({"attempt": attempt, "ok": False, "error": last_error})
        attempt += 1

    return {"ok": False, "code": current_code, "attempts": max_retries, "history": history, "last_error": last_error}


# -- GOAP Integration ----------------------------------------------------


async def execute_build_goal(goal: str, ring: int = 2) -> Dict[str, Any]:
    """Utilise GOAP pour décomposer une demande complexe de build."""
    try:
        from nokido_agent.app.forge_goap import decompose_goal, execute_plan

        plan = await decompose_goal(goal, ring_max=ring)
        traj = await execute_plan(plan)

        ok = all(s.status == "completed" for s in traj.steps)
        return {
            "ok": ok,
            "plan_id": plan.plan_id,
            "steps": len(plan.flat_actions()),
            "trajectory": [asdict(s) for s in traj.steps],
        }
    except Exception as e:
        logger.error(f"GOAP build failed: {e}")
        return {"ok": False, "error": str(e)}


# -- Main handler --------------------------------------------------------


def handle_build_new_app(args="", payload=None, **kw) -> str:
    """
    @build_new_app [goal] - Loop build intelligente.
    Usage: @build_new_app "creer un outil de monitoring CPU"
    """

    goal = args.strip()
    if not goal and payload:
        goal = payload.get("goal", payload.get("project", ""))

    if not goal:
        return "Usage: @build_new_app <objectif>"

    project_name = goal.split()[0].replace(".", "_")
    file_path = f"projects/{project_name}/main.py"
    test_cmd = f"python -m py_compile {file_path}"  # Fallback simple si pas de tests fournis

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # On tente d'abord un GOAP si la demande est complexe (contient 'avec', 'et', 'puis')
        if any(w in goal.lower() for w in ["avec", " et ", "puis", "ensuite"]):
            res = loop.run_until_complete(execute_build_goal(goal))
            return json.dumps(res, indent=2, ensure_ascii=False)
        else:
            # Sinon boucle de build standard sur main.py
            res = loop.run_until_complete(build_with_retry_loop(project_name, goal, file_path, test_cmd))
            return json.dumps(res, indent=2, ensure_ascii=False)
    finally:
        loop.close()


if __name__ == "__main__":
    # Test simple
    if len(sys.argv) > 1:
        print(handle_build_new_app(args=" ".join(sys.argv[1:])))
