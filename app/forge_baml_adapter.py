"""forge_baml_adapter.py — LLM structured outputs avec retry intelligent.

BAML BoundaryML pattern : pydantic schema + LLM call + rerun-on-parse-fail
(jusqu a N=3) avec error feedback dans next prompt.

Workflow :
  1. Define pydantic schema for expected output
  2. structured_call(prompt, schema, max_retries=3)
  3. Si parse fail -> retry avec prompt enrichi de l'erreur ('Last output was
                     invalid JSON. Error: X. Fix and retry.')
  4. Returns validated pydantic model

API :
    from pydantic import BaseModel
    class Recipe(BaseModel):
        title: str
        ingredients: list[str]
        steps: list[str]

    result = structured_call(
        prompt="Generate a recipe for chocolate cake",
        schema=Recipe,
        max_retries=3,
    )
    # result is Recipe instance
"""

from __future__ import annotations
import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Type, TypeVar, Union

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("baml_adapter")

CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

T = TypeVar("T")


def _llm_json_call(url: str, model: str, key: str, prompt: str, timeout: int = 20, max_tokens: int = 1000) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    if "gpt-oss" not in model:
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key.strip()}",
            "User-Agent": "Mozilla/5.0 LaForge-Agent",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    msg = data["choices"][0]["message"]
    return msg.get("content") or msg.get("reasoning", "")


def _get_keys() -> tuple[str, str]:
    try:
        from nokido_agent.app.forge_secrets import get_secret

        return (get_secret("CEREBRAS_API_KEY") or "", get_secret("GROQ_API_KEY") or "")
    except Exception:
        import os

        return (get_secret("CEREBRAS_API_KEY") or "", get_secret("GROQ_API_KEY") or "")


def _schema_json(schema) -> dict:
    """Extract JSON schema from pydantic model class."""
    if hasattr(schema, "model_json_schema"):
        return schema.model_json_schema()
    if hasattr(schema, "schema"):
        return schema.schema()
    return {}


def _build_prompt(prompt: str, schema, attempt: int = 0, prior_error: str = "") -> str:
    """Compose prompt avec schema JSON + retry feedback."""
    schema_json = _schema_json(schema)
    schema_snippet = json.dumps(schema_json, indent=2)[:2000]

    parts = [
        prompt.strip(),
        "",
        "Output STRICT JSON matching this schema:",
        schema_snippet,
        "",
        "Output ONLY the JSON object. No markdown, no comments.",
    ]

    if prior_error:
        parts.append("")
        parts.append(f"PREVIOUS ATTEMPT FAILED: {prior_error}")
        parts.append("Fix the issue and try again.")

    if attempt > 0:
        parts.append(f"(Retry {attempt}, be strict)")

    return "\n".join(parts)


def structured_call(prompt: str, schema, max_retries: int = 3, timeout_per_attempt: int = 20) -> object | None:
    """Call LLM avec schema strict + retry on parse fail.

    Args:
        prompt: user prompt
        schema: pydantic BaseModel class OR plain dict schema
        max_retries: attempts max (incluant le 1er)

    Returns:
        Instance pydantic validee, ou None si tous les retries echouent.
    """
    cerebras_key, groq_key = _get_keys()
    if not (cerebras_key or groq_key):
        logger.error("aucun cle LLM disponible")
        return None

    prior_error = ""
    for attempt in range(max_retries):
        prompt_full = _build_prompt(prompt, schema, attempt=attempt, prior_error=prior_error)
        raw = None
        for url, model, key in [
            (CEREBRAS_URL, "gpt-oss-120b", cerebras_key),
            (GROQ_URL, "llama-3.3-70b-versatile", groq_key),
        ]:
            if not key:
                continue
            try:
                raw = _llm_json_call(url, model, key, prompt_full, timeout=timeout_per_attempt)
                break
            except urllib.error.URLError as e:
                logger.debug(f"call {url} KO: {e}")
                continue
            except Exception as e:
                logger.debug(f"call {url} exc: {e}")
                continue

        if not raw:
            logger.warning(f"attempt {attempt + 1}: aucune reponse LLM")
            prior_error = "LLM call timeout/network"
            continue

        # Parse JSON
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            prior_error = f"JSON parse error: {e}. Output started with: {raw[:200]}"
            logger.info(f"attempt {attempt + 1}: JSON parse fail")
            continue

        # Validate via pydantic (si dispo)
        try:
            if hasattr(schema, "model_validate"):
                instance = schema.model_validate(data)
                return instance
            elif hasattr(schema, "parse_obj"):
                instance = schema.parse_obj(data)
                return instance
            else:
                return data  # schema dict-style, retourne dict
        except Exception as e:
            prior_error = f"Schema validation error: {str(e)[:300]}"
            logger.info(f"attempt {attempt + 1}: validation fail: {prior_error}")
            continue

    logger.warning(f"max_retries={max_retries} epuises sans succes")
    return None


# --- CLI demo ---


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    if not args.demo:
        ap.print_help()
        return

    try:
        from pydantic import BaseModel, Field
    except ImportError:
        print("pydantic absent. pip install pydantic")
        return

    class Article(BaseModel):
        title: str = Field(..., description="Article title")
        authors: list[str] = Field(..., description="List of authors")
        year: int = Field(..., description="Publication year", ge=1900, le=2100)
        abstract: str = Field(..., description="Brief abstract", max_length=500)
        keywords: list[str] = Field(default_factory=list, max_items=10)

    prompt = (
        "Generate metadata for a hypothetical 2025 paper about "
        "'efficient retrieval-augmented generation with graph hops'."
    )
    result = structured_call(prompt, Article, max_retries=3)
    if result:
        print("Structured output validated:")
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
    else:
        print("No result after retries.")


if __name__ == "__main__":
    main()
