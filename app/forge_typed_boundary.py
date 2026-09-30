"""forge_typed_boundary.py — Beartype enforced boundaries Nokido.

Source veille Gemini Web : @beartype = chien de garde runtime O(1).
Decore points de passage critiques (agent <-> hub, RAG ingest, LLM router payload).
Si type mismatch a l'execution : crash immediat + trace millimetree.

Install : pip install beartype

Frontieres critiques wrapped :
- build_llm_api_payload : payload sortant vers tiers (OpenAI-compat)
- validate_rag_chunk : avant INSERT rag_chunks (TEXT PRIMARY KEY)
- assert_agent_context : context handoff entre agents
"""

from __future__ import annotations

try:
    from beartype import beartype
    from beartype.typing import Any, Dict, List, Optional, Union

    BEARTYPE_AVAILABLE = True
except ImportError:
    # Fallback gracieux si beartype non installe (no-op decorator)
    BEARTYPE_AVAILABLE = False

    def beartype(func):
        return func

    from typing import Any, Dict, List, Optional, Union  # noqa


@beartype
def build_llm_api_payload(
    messages: List[Dict[str, str]],
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: float = 0.7,
    max_tokens: int = 600,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Build payload OpenAI-compat avec validation runtime stricte.

    Args:
        messages: liste [{role, content}]
        tools: optional list de tool definitions
        temperature: 0.0-2.0
        max_tokens: cap output
        model: model name (provider-specific)

    Raises:
        beartype.BeartypeException si type mismatch (agent injecte mauvais type)
    """
    if not messages:
        raise ValueError("messages vides : au moins 1 message requis")
    if not 0.0 <= temperature <= 2.0:
        raise ValueError(f"temperature hors range : {temperature}")

    payload: Dict[str, Any] = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
    if model:
        payload["model"] = model
    return payload


@beartype
def validate_rag_chunk(chunk: Dict[str, Any]) -> Dict[str, Any]:
    """Valide chunk avant INSERT rag_chunks. Schema requiert id explicite."""
    if "id" not in chunk or not isinstance(chunk["id"], str) or not chunk["id"]:
        raise ValueError("rag_chunk.id requis (TEXT PRIMARY KEY)")
    if "text" not in chunk:
        raise ValueError("rag_chunk.text requis")
    if not isinstance(chunk.get("text"), str):
        raise ValueError(f"text doit etre str, got {type(chunk.get('text'))}")
    return chunk


@beartype
def assert_agent_context(
    chain_id: str,
    step_name: str,
    context: Dict[str, Any],
    expected_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Assert agent context contient les keys attendues."""
    if not chain_id:
        raise ValueError("chain_id vide")
    if not step_name:
        raise ValueError("step_name vide")
    if expected_keys:
        missing = [k for k in expected_keys if k not in context]
        if missing:
            raise ValueError(f"context manque keys : {missing}")
    return context


@beartype
def validate_hub_command(
    action: str,
    args: Optional[Dict[str, Any]] = None,
    timeout_s: Union[int, float] = 30.0,
) -> Dict[str, Any]:
    """Valide command sortante vers hub :8766."""
    ALLOWED_ACTIONS = frozenset(
        [
            "shell",
            "python",
            "github",
            "trusted_script",
            "atlas_build",
            "save_situation",
            "atlas_get",
            "make_snapshot",
            "setup_check",
            "audit_log",
            "worker_status",
        ]
    )
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"action invalide '{action}' (allowed: {sorted(ALLOWED_ACTIONS)})")
    if not 0 < timeout_s <= 600:
        raise ValueError(f"timeout_s hors range : {timeout_s}")
    return {"action": action, "args": args or {}, "timeout_s": timeout_s}


def is_available() -> bool:
    """True si beartype installe + actif."""
    return BEARTYPE_AVAILABLE
