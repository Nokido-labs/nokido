"""app/forge_pydantic_tools.py - schemas Pydantic pour tool calls SWE-bench.

Remplace forge_dspy_router Signatures pour les tool calls (raisonnement
libre cote LLM, schema strict cote IO). Inspire pydantic-ai mais on
n importe pas le runtime Agent (gros poids deps) - on garde juste les
schemas Pydantic + un helper validate-and-retry.

Tools schemas :
  - ViewFileArgs        / ViewFileResult
  - EditFileBlockArgs   / EditFileResult
  - RunPytestArgs       / PytestResult
  - SubmitPatchArgs     / SubmitResult (final answer du loop SWE-bench)

Helper : call_tool_validated(name, raw_args_dict) -> dict resultat.
  Valide raw_args avec Pydantic. Si fail -> retourne ValidationError JSON
  serialisable que le LLM peut lire et corriger sans casser la chaine.

Le runtime LLM (Ollama/cloud) genere des JSON-like text -> on parse +
valide -> exec deterministe -> rendu pour next iteration.
"""

from __future__ import annotations

import json
from typing import Any, Callable

try:
    from pydantic import BaseModel, Field, ValidationError

    _PYDANTIC_OK = True
except ImportError:
    _PYDANTIC_OK = False
    BaseModel = object  # type: ignore
    Field = lambda *a, **k: None  # type: ignore  # noqa


if _PYDANTIC_OK:
    # === Tool schemas ========================================================

    class ViewFileArgs(BaseModel):
        path: str = Field(description="Absolute or repo-relative file path")
        start_line: int = Field(default=1, ge=1, description="1-indexed start")
        end_line: int | None = Field(default=None, description="Inclusive, None = EOF")

    class EditFileBlockArgs(BaseModel):
        path: str
        old_block: str = Field(min_length=1, description="Exact text to replace (must be unique)")
        new_block: str
        expect_unique: bool = Field(default=True)

    class RunPytestArgs(BaseModel):
        targets: list[str] = Field(default_factory=list, description="Test file paths or dirs; empty = full discover")
        timeout_s: int = Field(default=60, ge=5, le=600)
        workdir: str | None = Field(default=None, description="Override CWD for pytest run")

    class SubmitPatchArgs(BaseModel):
        diff: str = Field(min_length=1, description="Final unidiff to submit for SWE-bench evaluation")
        rationale: str = Field(default="", description="Why this patch fixes the issue, max 500 chars")

    # === Dispatcher ==========================================================

    _SCHEMAS = {
        "view_file_content": ViewFileArgs,
        "edit_file_block": EditFileBlockArgs,
        "run_pytest": RunPytestArgs,
        "submit_patch": SubmitPatchArgs,
    }


def list_tools() -> list[dict]:
    """Retourne la liste des tools + leur schema JSON pour le system prompt LLM."""
    if not _PYDANTIC_OK:
        return []
    return [{"name": name, "args_schema": cls.model_json_schema()} for name, cls in _SCHEMAS.items()]


def validate_args(tool_name: str, raw_args: dict | str) -> dict:
    """Parse + valide raw_args contre le schema du tool.
    raw_args peut etre dict ou JSON str. Retourne :
      - {ok: True, validated: dict}
      - {ok: False, error: str, validation_errors: list}
    """
    if not _PYDANTIC_OK:
        return {"ok": False, "error": "pydantic non installe"}
    schema = _SCHEMAS.get(tool_name)
    if schema is None:
        return {"ok": False, "error": f"unknown tool: {tool_name}", "available": list(_SCHEMAS.keys())}
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"args not valid JSON: {e}"}
    try:
        validated = schema(**raw_args)
        return {"ok": True, "validated": validated.model_dump()}
    except ValidationError as e:
        return {
            "ok": False,
            "error": "validation failed",
            "validation_errors": [
                {"loc": list(err.get("loc", [])), "msg": err.get("msg", ""), "type": err.get("type", "")}
                for err in e.errors()
            ],
        }


def call_tool_validated(tool_name: str, raw_args: dict | str, registry: dict[str, Callable] | None = None) -> dict:
    """Validate + dispatch vers la fonction registry[tool_name].
    Si registry None : utilise les defaults forge_repo_map_tools."""
    v = validate_args(tool_name, raw_args)
    if not v["ok"]:
        return v
    if registry is None:
        registry = _default_registry()
    fn = registry.get(tool_name)
    if fn is None:
        return {"ok": False, "error": f"no handler for {tool_name}"}
    try:
        result = fn(**v["validated"])
        return {"ok": True, "result": result}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"handler raised: {e}"}


def _default_registry() -> dict[str, Callable]:
    """Default handlers : repo_map_tools + simple pytest runner.
    submit_patch est un no-op handler (juste echo, le runner SWE-bench
    intercepte le diff)."""
    try:
        from nokido_agent.app.forge_repo_map_tools import edit_file_block, view_file_content
    except ImportError:
        return {}

    def _run_pytest(targets, timeout_s, workdir=None):
        import subprocess as _sp, sys as _sys

        cmd = [_sys.executable, "-m", "pytest", "-x", "--tb=short", "-q", "-p", "no:cacheprovider"]
        cmd.extend(targets)
        try:
            r = _sp.run(cmd, capture_output=True, text=True, cwd=workdir, timeout=timeout_s, errors="replace")
            return {"returncode": r.returncode, "stdout": r.stdout[-3000:], "stderr": r.stderr[-1000:]}
        except _sp.TimeoutExpired:
            return {"returncode": -1, "error": f"timeout {timeout_s}s"}

    def _submit(diff, rationale):
        return {"submitted_bytes": len(diff), "rationale": rationale[:200]}

    return {
        "view_file_content": view_file_content,
        "edit_file_block": edit_file_block,
        "run_pytest": _run_pytest,
        "submit_patch": _submit,
    }
