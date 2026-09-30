"""
forge_typed_task.py — ControlFlow-style typed task contract for Nokido.

Mined from prefect-archive/ControlFlow (Task(result_type=PydanticModel)). Runs a
single agentic task whose result is constrained + validated. Two tiers
(EXEC_DOCTRINE layer #3 = Structured Outputs):

  1. ENGINE-CONSTRAINED (default, local Ollama): the JSON-Schema is passed to the
     inference engine via Ollama's `format` field -> the model can only emit a
     value matching the schema (true constrained generation).
  2. PROMPT-INSTRUCT fallback (cloud / other providers, or if the engine path
     fails): instruct the schema, parse, validate, repair-retry via the governed
     forge_agent_proxy.ask.

Two entry points:
  - run_typed_task(prompt, PydanticModel, ...)  -> validated Pydantic object
    (for in-process callers / cognitive workers wanting guaranteed structure).
  - run_typed_schema(prompt, json_schema, ...)  -> validated dict (JSON-serialisable;
    the GOVERNED ROUTE: any CLI/agent via `run trusted_script path=app/forge_typed_task.py`).
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "locomoteur/runtime : contrat de tache typee (ControlFlow)"  # organe declare le 2026-09-06 (audit de raccordement)

import asyncio
import json
import os

try:
    from pydantic import ValidationError
except Exception:  # pragma: no cover
    ValidationError = Exception  # type: ignore


def _schema_obj(model):
    try:
        return model.model_json_schema()       # pydantic v2
    except Exception:
        try:
            return model.schema()              # pydantic v1
        except Exception:
            return {}


def _extract_json(text: str) -> str:
    """Strip markdown fences and isolate the first JSON value if prose leaks."""
    s = (text or "").strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    best = s
    for op, cl in (("{", "}"), ("[", "]")):
        i, j = s.find(op), s.rfind(cl)
        if 0 <= i < j:
            cand = s[i:j + 1]
            if len(cand) < len(best) or best is s:
                best = cand
    return best


def _validate(model, data):
    try:
        return model.model_validate(data)   # pydantic v2
    except AttributeError:
        return model.parse_obj(data)        # pydantic v1


def _validate_schema(data, schema):
    """Validate a dict against a raw JSON-Schema (jsonschema if available, else
    a light required-keys check). Raises on mismatch."""
    try:
        import jsonschema
        jsonschema.validate(data, schema)
        return data
    except ImportError:
        for k in (schema or {}).get("required", []):
            if k not in data:
                raise ValueError(f"missing required key: {k}")
        return data


def _ollama_url():
    try:
        from nokido_agent.app.forge_app_context import app_ctx
        u = getattr(app_ctx().settings, "ollama_url", None)
        if u:
            return u
    except Exception:
        pass
    return "http://127.0.0.1:11434/api/chat"


async def _ollama_constrained(model, prompt, schema, system=None, timeout=120, max_tokens=512):
    """Direct, strict Ollama call with `format`=JSON-Schema (constrained
    generation). No fallback cascade (that would dilute the constraint)."""
    import aiohttp
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    payload = {"model": model, "messages": msgs, "stream": False,
               "format": schema, "options": {"num_predict": max_tokens}}
    if "qwen3" in model:
        payload["think"] = False
    async with aiohttp.ClientSession() as s:
        async with s.post(_ollama_url(), json=payload,
                          timeout=aiohttp.ClientTimeout(total=timeout, connect=8)) as r:
            if r.status != 200:
                body = await r.text()
                raise RuntimeError(f"ollama {r.status}: {body[:160]}")
            data = await r.json()
    return data.get("message", {}).get("content", "")


async def _run_async(prompt, schema, validate_fn, provider="ollama", model=None,
                     engine_constrain=True, max_retries=2, rag_context=False, timeout=120):
    """Core: constrain to `schema`, parse, validate via validate_fn(data)->result."""
    # Tier 1 — engine-constrained (local Ollama format=schema).
    if engine_constrain and provider == "ollama":
        mdl = model or os.environ.get("LAFORGE_TYPED_MODEL", "qwen2.5-coder:7b-instruct-q4_K_M")
        try:
            raw = await _ollama_constrained(mdl, prompt, schema, timeout=timeout)
            data = json.loads(_extract_json(raw))
            return {"ok": True, "result": validate_fn(data), "raw": raw,
                    "mode": "engine_constrained", "model": mdl}
        except Exception as exc:  # noqa: BLE001 - fall through to prompt-instruct
            engine_err = str(exc)[:200]
    else:
        engine_err = None

    # Tier 2 — prompt-instruct + repair-retry via the governed ask pipeline.
    from nokido_agent.app import forge_agent_proxy as proxy
    hint = json.dumps(schema)
    base = (f"{prompt}\n\nRespond with ONLY a JSON value matching this JSON Schema "
            f"(no prose, no markdown fences):\n{hint}")
    msg = base
    last_err = engine_err
    for attempt in range(max_retries + 1):
        res = await proxy.ask(provider, msg, rag_context=rag_context, timeout=timeout)
        if not res or not res.get("ok"):
            last_err = (res or {}).get("error", "ask failed")
            break
        raw = res.get("text") or ""
        try:
            data = json.loads(_extract_json(raw))
            return {"ok": True, "result": validate_fn(data), "raw": raw,
                    "mode": "prompt_instruct", "attempts": attempt + 1}
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as e:
            last_err = str(e)
            msg = (base + f"\n\nYour previous answer was invalid: {str(e)[:300]}. "
                   "Return ONLY valid JSON matching the schema.")
    return {"ok": False, "error": str(last_err)[:400]}


async def run_typed_task_async(prompt, result_type, **kw):
    """Pydantic-typed result (in-process). Returns {ok, result: <model>, ...}."""
    return await _run_async(prompt, _schema_obj(result_type),
                            lambda d: _validate(result_type, d), **kw)


def run_typed_task(prompt, result_type, **kw):
    return asyncio.run(run_typed_task_async(prompt, result_type, **kw))


async def run_typed_schema_async(prompt, json_schema, **kw):
    """Raw-schema result (JSON-serialisable dict). The governed-route entry."""
    return await _run_async(prompt, json_schema,
                            lambda d: _validate_schema(d, json_schema), **kw)


def run_typed_schema(prompt, json_schema, **kw):
    return asyncio.run(run_typed_schema_async(prompt, json_schema, **kw))


def _selftest():
    from pydantic import BaseModel

    class Person(BaseModel):
        name: str
        age: int

    raw = "Sure!\n```json\n{\"name\": \"Ada\", \"age\": 36}\n```\n"
    person = _validate(Person, json.loads(_extract_json(raw)))
    ok = person.name == "Ada" and person.age == 36
    bad = False
    try:
        _validate(Person, {"name": "x"})
    except Exception:
        bad = True
    sch = _schema_obj(Person)
    schema_ok = isinstance(sch, dict) and "properties" in sch
    # raw-schema validator
    sv_ok = _validate_schema({"name": "Z", "age": 1}, sch) == {"name": "Z", "age": 1}
    print(json.dumps({"parse_validate_ok": ok, "rejects_invalid": bad,
                      "schema_obj_ok": schema_ok, "schema_validator_ok": sv_ok,
                      "pass": ok and bad and schema_ok and sv_ok}))
    return 0 if (ok and bad and schema_ok and sv_ok) else 1


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Typed task: schema-constrained LLM output")
    ap.add_argument("--task", help="the prompt")
    ap.add_argument("--schema", help="JSON-Schema (JSON string)")
    ap.add_argument("--provider", default="ollama")
    ap.add_argument("--model", default=None)
    ap.add_argument("--no-engine", action="store_true", help="disable engine constraint")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest or not a.task or not a.schema:
        raise SystemExit(_selftest())
    schema = json.loads(a.schema)
    res = run_typed_schema(a.task, schema, provider=a.provider, model=a.model,
                           engine_constrain=not a.no_engine)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
