"""
__FORGE_COLOR__ = "#fb923c"  # orange — multi-agent handoff orchestrator

forge_handoff — Minimal multi-agent Handoff orchestrator (Swarm pattern).

Inspired by openai/swarm (officially deprecated, ~200 LOC of useful pattern).
NOT a replacement for forge_agentic_engine — that handles RAG context
preparation + skill matching. This module handles AGENT ROUTING : starting
from a triage agent, transfer to specialized agents until one produces a
final answer (no further transfer).

Why a new module : forge_agentic, forge_agentic_engine, forge_agents focus
on RAG + skill match + role authority. None implement the run-loop with
tool-result-as-Agent handoff. Anti-duplication grep 2026-05-02 confirmed.

Design choices :
- Pure Python, no openai SDK dependency.
- LLM dispatch via forge_llm_router (cascade Ollama → cloud fallback) OR
  direct Ollama for explicit model pinning.
- Supports both function-calling LLMs (qwen 2.5 7B+, qwen3:8b — schema
  passed in tools field) AND non-function-calling models (text-based handoff
  parsing via TRANSFER_TO: <name>).
- Resource-aware : calls forge_resource_manager.should_throttle() before
  each LLM round, raises ResourceExhausted if RAM/CPU above threshold.

Compose with :
- forge_md_router.lazy_load_clinical() for ADR-grounded prompts
- forge_silo_engine for domain-typed reasoning
- forge_resource_manager for throttling

Multi-cervelet support added 2026-05-02 — endpoints + workflow modes
(linear/parallel/cross/distant stub). The two local cervelets are :
  * Ollama :11434 — orchestrator-grade, hot-swappable models
  * llama-server :8091 NSSM service `NokidoLlamaNative` — single-model
    fast path with speculative draft for code completion

Workflow modes :
  * LINEAR   — sequential pipeline, output(N) → input(N+1)
  * PARALLEL — broadcast same query to N agents (threaded), return N answers
  * CROSS    — multi-round critique a la LLM-Blender (arxiv 2306.02561)
  * DISTANT  — STUB for Tailscale-mesh edge node dispatch (planned)

Cross-ref :
- forge_resource_manager.brain_pick / request_resources / should_throttle
- forge_md_router.lazy_load_clinical for ADR-grounded agent system prompts
"""

from __future__ import annotations

import inspect
import json
import logging
import random
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from dataclasses import replace as _dc_replace
from typing import Any, Callable, Literal, Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger(__name__)


class ResourceExhausted(RuntimeError):
    """Raised by run_swarm() when the system is under pressure (throttle gate)."""


class NoHealthyEndpoint(RuntimeError):
    """Raised by HandoffRouter when no healthy cervelet endpoint is available."""


# ─────────────────────────────────────────────────────────────────────────────
# Core types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Agent:
    name: str
    instructions: str
    tools: list[Callable] = field(default_factory=list)
    # Either an Ollama model string ("qwen2.5-coder:7b") or a router use_case ("code", "security", "general").
    # Heuristic : if it contains ':' → direct Ollama. Else → router_call(use_case=...).
    model: str = "general"
    # If True, the run loop will parse `TRANSFER_TO: <agent_name>` token from
    # text replies as a fallback handoff trigger (for small models without tool-calling).
    text_handoff: bool = True
    # Dualite Devin/Claude Code 2.0 :
    #   "EXECUTE"  (defaut) — tool-calls / transferts directs (comportement legacy)
    #   "PLANNING"          — _llm_round() prefixe le system prompt avec un gate
    #                         <think> qui force objectif/hypotheses/risques/rollback
    #                         AVANT toute action irreversible. Cf. CLAUDE.md
    #                         section "Planning Mode + <think> Gate".
    mode: Literal["PLANNING", "EXECUTE"] = "EXECUTE"
    # Multi-provider dispatch (2026-05-23) — override le routage par use_case.
    #   None              (defaut) — comportement legacy : Ollama direct si
    #                                model contient ":", sinon router_call(use_case=model).
    #   "ollama_local"    | "llamacpp_local" | "lmstudio_native" — backend local
    #                                via _call_ollama_chat (model = config par defaut).
    #   <nom router PROVIDERS> — dispatch FORCE sur ce slot via
    #                                LLMRouter._call_slot. Quota gate via
    #                                forge_provider_quota.should_skip avant l'appel.
    #                                Fallback automatique sur USE_CASE_CHAINS[use_case]
    #                                en cas d'echec / quota epuise / provider HS.
    # Note : un provider inconnu du router (ex. "cerebras" si pas dans PROVIDERS)
    # tombe directement en text-handoff fallback sans crash.
    provider: Optional[str] = None

    def plan_first(self) -> "Agent":
        """Return an immutable copy of this Agent forced into PLANNING mode.

        Swarm-style : we never mutate the original Agent so the same definition
        can be reused across rounds. Use this just before a transfer to a
        sensitive sink (commit, push, kill, restart, ACL, ingest prod).

        Example :
            triage = Agent(name="triage", instructions="route", model="general")
            secops = Agent(name="secops", instructions="audit", model="security")
            # Force secops to draft a plan before acting :
            transfer_tool = make_transfer_tool(secops.plan_first(),
                                               when="when user asks audit")
        """
        return _dc_replace(self, mode="PLANNING")

    def lats_solve(self, problem: str, budget: int = 8, threshold: float = 0.75) -> dict:
        """LATS tree search wrapper. Wire vers forge_lats_general pour
        problemes durs ou la generation lineaire fail.

        Usage : agent.lats_solve("diagnostic root cause BSOD video_scheduler")

        Returns dict {best_plan, best_score, n_iterations, trace, rationale}.
        """
        try:
            from nokido_agent.app.forge_lats_general import lats_solve as _lats

            return _lats(problem, budget=budget, threshold=threshold)
        except Exception as e:
            return {"error": f"LATS unavailable: {e}"}


# System prompt prefix injected by _llm_round() when current agent is in PLANNING mode.
# Kept module-level (not nested in the function) so tests can assert on the exact text
# and external callers can re-use the same gate prompt elsewhere if needed.
PLANNING_PREFIX = (
    "## PLANNING PHASE\n"
    "Reconnaissance d'abord. Pas d'action irreversible. "
    "Enonce objectif/hypotheses/risques/rollback en bloc <think>.\n"
    "---\n"
)


@dataclass
class Transfer:
    """Tool result that triggers a handoff to another Agent."""

    next_agent: Agent
    context_update: Optional[str] = None


@dataclass
class SwarmResult:
    final_agent: str
    messages: list[dict[str, Any]]
    n_rounds: int
    transfers: list[tuple[str, str]]  # [(from_name, to_name), ...]


# ─────────────────────────────────────────────────────────────────────────────
# Tool schema builder — best-effort, no docstring required
# ─────────────────────────────────────────────────────────────────────────────


def _build_tool_schema(fn: Callable) -> dict:
    """Build OpenAI-style tool schema from a Python callable.

    Type hints required for params. No-arg tools = empty params object.
    """
    sig = inspect.signature(fn)
    props: dict[str, dict] = {}
    required: list[str] = []
    for pname, p in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        ann = p.annotation if p.annotation is not inspect.Parameter.empty else str
        type_str = "string"
        if ann in (int,):
            type_str = "integer"
        elif ann in (float,):
            type_str = "number"
        elif ann in (bool,):
            type_str = "boolean"
        props[pname] = {"type": type_str}
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": (fn.__doc__ or "").strip().split("\n")[0],
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# LLM dispatch helpers
# ─────────────────────────────────────────────────────────────────────────────


def _looks_like_ollama_model(model: str) -> bool:
    return ":" in model or model in ("laforge-qwen", "qwen2.5", "qwen3")


def _call_ollama_chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict] | None = None,
    temperature: float = 0.2,
    timeout: int = 60,
) -> dict:
    """Direct Ollama /api/chat call. Returns dict with .message + .tool_calls."""
    import urllib.request

    payload: dict[str, Any] = {
        "model": model,
        "stream": False,
        "messages": messages,
        "options": {"temperature": temperature, "num_ctx": 4096},
    }
    if tools:
        payload["tools"] = tools
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _call_router(prompt: str, use_case: str, max_tokens: int = 500) -> dict:
    """Wrap forge_llm_router.router_call into the message format used here."""
    import sys as _s
    from pathlib import Path as _P

    _app = _P(__file__).resolve().parent
    if str(_app) not in _s.path:
        _s.path.insert(0, str(_app))
    from nokido_agent.app.forge_llm_router import router_call

    # CONTEXTE DE PARTAGE (2026-09-02) : ce chemin atteignait router_call sans porter
    # la moindre information de politique. Il est desormais INSTRUMENTE mais pas
    # encore CLASSE -- `contexte_legacy` produit UNKNOWN, jamais une valeur
    # permissive inventee : ecrire PUBLIC ici pour faire passer l'appel serait
    # exactement la faute que la politique existe pour empecher.
    from nokido_agent.app.forge_share_policy import contexte_legacy as _ctx_legacy

    out = router_call(prompt, use_case=use_case, max_tokens=max_tokens,
                      context=_ctx_legacy(provenance="forge_handoff._call_router"))
    text = out.get("text") or out.get("content") or ""
    return {
        "message": {"role": "assistant", "content": text},
        "tool_calls": [],  # router doesn't expose function calling natively
        "_router_meta": out,
    }


_LOCAL_PROVIDERS = ("ollama_local", "llamacpp_local", "lmstudio_native", "ollama_mimo_v2")


def _ensure_app_on_path() -> None:
    """Best-effort sys.path insertion for sibling forge_* modules."""
    import sys as _s
    from pathlib import Path as _P

    _app = _P(__file__).resolve().parent
    if str(_app) not in _s.path:
        _s.path.insert(0, str(_app))


def _quota_should_skip(provider: str, threshold: float = 1.0) -> bool:
    """Return True if provider quota is exhausted. Soft-fails on missing module."""
    try:
        _ensure_app_on_path()
        from nokido_agent.app.forge_provider_quota import should_skip

        return should_skip(provider, threshold=threshold)
    except Exception:
        return False


def _call_router_provider(
    prompt: str, provider: str, max_tokens: int = 500, temperature: float = 0.2, timeout: int = 30
) -> dict:
    """Force a single provider via LLMRouter._call_slot, no cascade.

    Returns the handoff-shaped envelope (message + tool_calls + _router_meta)
    when ok. Raises RuntimeError on any failure (unknown provider, quota,
    HTTP error, slot unavailable) so the caller can apply fallback policy.
    """
    _ensure_app_on_path()
    from nokido_agent.app.forge_llm_router import get_router

    router = get_router()
    slot = router._slots.get(provider)
    if slot is None:
        raise RuntimeError(f"unknown router provider: {provider}")
    if not slot.is_configured:
        raise RuntimeError(f"provider {provider} not configured (env_key missing)")
    if _quota_should_skip(provider):
        raise RuntimeError(f"provider {provider} quota exhausted")
    out = router._call_slot(
        slot,
        prompt,
        system="",
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        use_case="general",
    )
    if not out.get("ok"):
        raise RuntimeError(out.get("error", "router call failed"))
    return {
        "message": {"role": "assistant", "content": out.get("text", "")},
        "tool_calls": [],
        "_router_meta": out,
    }


def _llm_round(agent: Agent, messages: list[dict[str, Any]], with_tools: bool) -> dict:
    """One LLM call honoring agent.model + agent.provider dispatch rule.

    Dispatch priority (2026-05-23) :
      1. agent.provider in _LOCAL_PROVIDERS  → direct Ollama (uses agent.model
         as concrete tag, e.g. "qwen2.5-coder:7b-instruct-q4_K_M").
      2. agent.provider set (cloud)          → LLMRouter._call_slot(provider),
         quota gated, fallback to use_case cascade on error.
      3. agent.provider is None              → legacy : Ollama if model has ":",
         else router_call(use_case=model).

    If agent.mode == "PLANNING", PLANNING_PREFIX is prepended to the system
    instructions so the model is gated into a <think> bloc before any action.
    """
    instr = agent.instructions
    if getattr(agent, "mode", "EXECUTE") == "PLANNING":
        instr = PLANNING_PREFIX + instr
    sys_msg = {"role": "system", "content": instr}
    full = [sys_msg] + messages

    provider = getattr(agent, "provider", None)

    # Branch A : explicit local provider — dispatch direct via /api/chat.
    if provider in _LOCAL_PROVIDERS:
        tools_schema = [_build_tool_schema(t) for t in agent.tools] if (with_tools and agent.tools) else None
        return _call_ollama_chat(agent.model, full, tools=tools_schema)

    # Branch B : explicit cloud provider — force single-slot dispatch.
    if provider:
        flat = "\n\n".join(f"[{m['role']}] {m['content']}" for m in full)
        try:
            return _call_router_provider(flat, provider=provider)
        except Exception as exc:
            logger.warning(
                "[SWARM] forced provider %s failed (%s) — fallback cascade on use_case=%s",
                provider,
                exc,
                agent.model,
            )
            # Fallback A : try the cascade for agent.model as use_case
            # (works when agent.model is a USE_CASE_CHAINS key like "code").
            try:
                return _call_router(flat, use_case=agent.model)
            except Exception as exc2:
                logger.warning(
                    "[SWARM] cascade fallback failed (%s) — degraded text-handoff envelope",
                    exc2,
                )
                # Last resort : return an empty assistant message so the
                # run_swarm loop can either parse a TRANSFER_TO: token from
                # subsequent rounds OR terminate cleanly. Keeps API stable.
                return {
                    "message": {
                        "role": "assistant",
                        "content": f"[provider {provider} unavailable, fallback exhausted]",
                    },
                    "tool_calls": [],
                    "_router_meta": {
                        "ok": False,
                        "error": str(exc2)[:120],
                        "provider": provider,
                        "fallback": "text-handoff",
                    },
                }

    # Branch C : legacy path (provider=None).
    if _looks_like_ollama_model(agent.model):
        tools_schema = [_build_tool_schema(t) for t in agent.tools] if (with_tools and agent.tools) else None
        return _call_ollama_chat(agent.model, full, tools=tools_schema)

    # Router path — collapse messages into a single prompt (router doesn't take chat history natively)
    flat = "\n\n".join(f"[{m['role']}] {m['content']}" for m in full)
    return _call_router(flat, use_case=agent.model)


# ─────────────────────────────────────────────────────────────────────────────
# Text-based handoff fallback
# ─────────────────────────────────────────────────────────────────────────────

_TRANSFER_RE = re.compile(r"TRANSFER_TO:\s*([A-Za-z0-9_\-]+)", re.IGNORECASE)


def _parse_text_handoff(content: str, available_agents: dict[str, Agent]) -> Optional[Transfer]:
    m = _TRANSFER_RE.search(content)
    if not m:
        return None
    name = m.group(1)
    target = available_agents.get(name)
    if target is None:
        # Try case-insensitive
        for k, a in available_agents.items():
            if k.lower() == name.lower():
                target = a
                break
    if target is None:
        return None
    return Transfer(next_agent=target, context_update=f"Routed by triage to {target.name}")


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────


# Side-channel events (vue live swarm sur l'UI web) — best-effort, n'altère
# JAMAIS le résultat de run_swarm. Voir app/forge_swarm_bus.py + /api/swarm/stream.
try:
    from nokido_agent.app.forge_swarm_bus import publish as _swarm_emit
except Exception:  # pragma: no cover
    def _swarm_emit(*_a, **_k):
        return None


def _augment_with_dynamic_tools(agent: "Agent") -> "Agent":
    """FRESH par round : ajoute 1 Callable generique forge_call_dynamic + la liste des
    outils forges (registre re-lu a chaque appel) aux tools/instructions de l'agent.
    Corrige le snapshot Agent.tools : un outil forge mid-swarm apparait au round suivant.

    Securite : l'exec passe par SecretGuard (cote forge_call_dynamic). Le swarm n'a pas
    le ring-gate du planner GOAP -> SecretGuard reste la garde de CONTENU.
    """
    try:
        _ensure_app_on_path()
        from nokido_agent.app.forge_tool_forger import forge_list_dynamic_tools

        lst = forge_list_dynamic_tools().get("tools", [])
    except Exception:
        return agent
    if not lst:
        return agent

    def forge_call_dynamic(name: str, kwargs: Optional[dict] = None) -> dict:
        """Invoque un outil forge par son nom (kwargs = dict d'arguments)."""
        from nokido_agent.app.forge_tool_forger import forge_call_dynamic as _fcd

        return _fcd(name, **(kwargs or {}))

    rows = "\n".join(
        f"  - {t['name']}{t.get('signature', '')} — {t.get('description', '')}" for t in lst[:30]
    )
    extra = (
        "\n\nOUTILS DYNAMIQUES forges — pour en utiliser un, appelle l'outil "
        'forge_call_dynamic(name="<nom>", kwargs={...}) :\n' + rows
    )
    try:
        base = [t for t in agent.tools if getattr(t, "__name__", "") != "forge_call_dynamic"]
        return _dc_replace(agent, tools=base + [forge_call_dynamic], instructions=agent.instructions + extra)
    except Exception:
        return agent


def run_swarm(
    starting_agent: Agent,
    user_query: str,
    available_agents: dict[str, Agent] | None = None,
    max_rounds: int = 8,
    throttle_check: bool = True,
    backpressure_mode: str = "sleep",
    backpressure_sleep_s: float = 2.0,
    cloud_fallback_agent: Agent | None = None,
) -> SwarmResult:
    """Run the handoff loop. Returns SwarmResult with full transcript.

    Args:
        starting_agent: where the loop begins (typically "triage").
        user_query: the user's question.
        available_agents: registry for text-handoff parsing. Required if any
            agent has text_handoff=True and no proper tool-calling.
        max_rounds: hard cap on LLM rounds to avoid infinite loops.
        throttle_check: if True, react when system is throttled.
        backpressure_mode: how to react to throttle:
            "sleep"    — pause backpressure_sleep_s, retry round (graceful)
            "fallback" — handoff to cloud_fallback_agent (degraded service)
            "raise"    — raise ResourceExhausted (legacy)
        backpressure_sleep_s: seconds to wait per throttled round (mode=sleep).
        cloud_fallback_agent: target Agent when mode="fallback" and throttled.
    """
    if available_agents is None:
        available_agents = {starting_agent.name: starting_agent}
        for tool in starting_agent.tools:
            # Detect tools that wrap an Agent transfer — best-effort
            if hasattr(tool, "_target_agent"):
                a = tool._target_agent  # type: ignore
                available_agents[a.name] = a

    # Resolve should_throttle once — cheap closure
    def _throttled() -> bool:
        if not throttle_check:
            return False
        try:
            import sys as _s
            from pathlib import Path as _P

            _app = _P(__file__).resolve().parent
            if str(_app) not in _s.path:
                _s.path.insert(0, str(_app))
            from nokido_agent.app.forge_resource_manager import should_throttle

            return should_throttle()
        except ImportError:
            return False

    current = starting_agent
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_query}]
    transfers: list[tuple[str, str]] = []
    backpressure_events = 0
    cloud_fallback_done = False
    _swarm_emit("swarm_start", {"task": user_query[:200], "starting_agent": starting_agent.name, "agents": list(available_agents.keys()), "max_rounds": max_rounds})

    for round_idx in range(max_rounds):
        if _throttled():
            backpressure_events += 1
            if backpressure_mode == "raise":
                raise ResourceExhausted(f"Throttled at round {round_idx} ({len(transfers)} transfers)")
            if backpressure_mode == "fallback" and cloud_fallback_agent is not None and not cloud_fallback_done:
                logger.warning(
                    "[SWARM] Throttled — fallback %s -> %s",
                    current.name,
                    cloud_fallback_agent.name,
                )
                transfers.append((current.name, cloud_fallback_agent.name))
                current = cloud_fallback_agent
                cloud_fallback_done = True
                messages.append(
                    {
                        "role": "system",
                        "content": "Fallback to cloud agent due to local resource pressure.",
                    }
                )
                # Don't sleep — cloud agent doesn't depend on local hardware
            else:
                # mode == "sleep" or fallback-already-done : graceful pause
                import time as _t

                _t.sleep(backpressure_sleep_s)

        _swarm_emit("agent_start", {"agent": current.name, "provider": getattr(current, "provider", ""), "round": round_idx})
        active = _augment_with_dynamic_tools(current)  # FRESH : outils forges visibles ce round (schema + exec)
        response = _llm_round(active, messages, with_tools=bool(active.tools))
        msg = response.get("message", {})
        tool_calls = response.get("tool_calls") or msg.get("tool_calls") or []
        content = msg.get("content", "") or ""
        messages.append({"role": "assistant", "content": content})
        _swarm_emit("agent_reply", {"agent": current.name, "provider": getattr(current, "provider", ""), "chars": len(content), "tool_calls": len(tool_calls), "text": content[:600]})

        # 1. Tool-call handoff (function-calling models)
        transferred = False
        for tc in tool_calls:
            fn_name = tc.get("function", {}).get("name") or tc.get("name")
            fn_args_raw = tc.get("function", {}).get("arguments") or tc.get("arguments") or {}
            if isinstance(fn_args_raw, str):
                try:
                    fn_args = json.loads(fn_args_raw)
                except Exception:
                    fn_args = {}
            else:
                fn_args = fn_args_raw

            tool_fn = next((t for t in active.tools if t.__name__ == fn_name), None)
            if tool_fn is None:
                messages.append({"role": "tool", "name": fn_name or "unknown", "content": "ERR: tool not found"})
                continue
            try:
                result = tool_fn(**fn_args)
            except Exception as e:
                messages.append({"role": "tool", "name": fn_name, "content": f"ERR: {type(e).__name__}: {e}"})
                continue

            if isinstance(result, Transfer):
                _swarm_emit("transfer", {"from": current.name, "to": result.next_agent.name, "kind": "tool"})
                transfers.append((current.name, result.next_agent.name))
                current = result.next_agent
                if result.context_update:
                    messages.append({"role": "system", "content": result.context_update})
                transferred = True
                break
            messages.append({"role": "tool", "name": fn_name, "content": str(result)})

        if transferred:
            continue

        # 2. Text-based handoff (small models without tool-calling)
        if current.text_handoff and content:
            transfer = _parse_text_handoff(content, available_agents)
            if transfer is not None and transfer.next_agent.name != current.name:
                _swarm_emit("transfer", {"from": current.name, "to": transfer.next_agent.name, "kind": "text"})
                transfers.append((current.name, transfer.next_agent.name))
                current = transfer.next_agent
                if transfer.context_update:
                    messages.append({"role": "system", "content": transfer.context_update})
                continue

        # 3. Final answer (no tools, no transfer, plain text reply)
        if not tool_calls and content:
            _swarm_emit("final", {"agent": current.name, "rounds": round_idx + 1, "transfers": len(transfers)})
            return SwarmResult(
                final_agent=current.name,
                messages=messages,
                n_rounds=round_idx + 1,
                transfers=transfers,
            )

    # Hit max_rounds without convergence
    return SwarmResult(
        final_agent=current.name,
        messages=messages,
        n_rounds=max_rounds,
        transfers=transfers,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Load-aware routing — pick local vs cloud agent based on system metrics
# ─────────────────────────────────────────────────────────────────────────────


def dynamic_handoff_decision(
    task_complexity: str,
    local_fast: Agent,
    local_heavy: Agent,
    cloud: Agent,
    ram_free_min_gb: float = 2.0,
    gpu_pct_max: float = 85.0,
) -> Transfer:
    """Pick the best Agent given current system load.

    Heuristic :
        - RAM low  OR GPU saturated  → cloud (Groq / Anthropic)
        - high complexity + healthy hardware → local_heavy (qwen 7B / 32B)
        - else → local_fast (qwen 1.5B / laforge-qwen)

    Args:
        task_complexity: "low" | "medium" | "high"
        local_fast / local_heavy / cloud: pre-built Agent instances
        ram_free_min_gb: under this, consider RAM low
        gpu_pct_max: over this, consider GPU saturated
    """
    try:
        import sys as _s
        from pathlib import Path as _P

        _app = _P(__file__).resolve().parent
        if str(_app) not in _s.path:
            _s.path.insert(0, str(_app))
        from nokido_agent.app.forge_resource_manager import get_snapshot

        snap = get_snapshot()
    except ImportError:
        snap = {}

    ram_free = snap.get("ram_free_gb", 999.0)
    gpu_pct = snap.get("gpu_pct") or 0.0

    if ram_free < ram_free_min_gb or gpu_pct > gpu_pct_max:
        logger.info(
            "[SWARM] Load-aware: hardware pressure (ram_free=%.1f GB, gpu=%.0f%%) -> cloud",
            ram_free,
            gpu_pct,
        )
        return Transfer(next_agent=cloud, context_update="Routed to cloud (local pressure).")

    if task_complexity == "high":
        return Transfer(next_agent=local_heavy, context_update="Routed to local heavy (healthy).")

    return Transfer(next_agent=local_fast, context_update="Routed to local fast.")


# ─────────────────────────────────────────────────────────────────────────────
# Helper : turn a target Agent into a transfer-tool
# ─────────────────────────────────────────────────────────────────────────────


def make_transfer_tool(target: Agent, when: str = "") -> Callable:
    """Wrap an Agent into a function the LLM can call to trigger a handoff.

    Args:
        target: the Agent receiving the transfer.
        when: short docstring telling the LLM when to call this transfer.
    """

    def transfer() -> Transfer:
        return Transfer(next_agent=target, context_update=f"Handoff to {target.name}.")

    transfer.__name__ = f"transfer_to_{target.name.lower().replace(' ', '_').replace('-', '_')}"
    transfer.__doc__ = when or f"Transfer the conversation to {target.name}."
    transfer._target_agent = target  # type: ignore
    return transfer


# ─────────────────────────────────────────────────────────────────────────────
# Multi-cervelet support — endpoints, health probe, picker, router
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CerveletEndpoint:
    """A single LLM serving endpoint (Ollama, llama-server, edge node, cloud).

    Health is updated by `brain_health_probe()`. Pick via `pick_brain_for_task()`
    or `HandoffRouter`. Weight is used for weighted-random load balancing
    when multiple healthy endpoints can serve the same task_kind.
    """

    name: str  # "ollama_local" | "llamacpp_native" | "edge_node_2" | "groq_cloud"
    url: str  # http://127.0.0.1:11434 etc
    model: str  # "qwen2.5-coder:7b-instruct-q4_K_M"
    weight: float = 1.0  # for load balancing weighted random
    auth_header: dict = field(default_factory=dict)
    healthy: bool = True  # set by health probe
    last_check_ts: float = 0.0
    avg_latency_ms: float = 0.0
    # Optional taxonomy hints used by pick_brain_for_task
    kind: str = "ollama"  # "ollama" | "llamacpp" | "openai_compat" | "edge" | "cloud"
    # Optional capability tags : {"code", "fast", "reasoning", "summary", "embedding"}
    capabilities: list[str] = field(default_factory=list)


def _probe_url_for(ep: CerveletEndpoint) -> str:
    """Build the canonical probe URL for an endpoint based on its kind."""
    base = ep.url.rstrip("/")
    if ep.kind == "ollama":
        return f"{base}/api/tags"
    if ep.kind == "llamacpp":
        # llama-server exposes both /health and /v1/models; /health is cheapest
        return f"{base}/health"
    if ep.kind in ("openai_compat", "cloud"):
        return f"{base}/v1/models"
    if ep.kind == "edge":
        # Tailscale edge node — assumed to expose /api/swarm/health
        return f"{base}/api/swarm/health"
    # Fallback : try /health
    return f"{base}/health"


def _probe_one(ep: CerveletEndpoint, timeout_s: float = 5.0) -> CerveletEndpoint:
    """Probe a single endpoint. Mutates and returns the same instance.

    Marks unhealthy if HTTP error OR response > timeout_s. Updates
    avg_latency_ms (EMA, alpha=0.3) and last_check_ts.
    """
    url = _probe_url_for(ep)
    headers = dict(ep.auth_header) if ep.auth_header else {}
    started = time.time()
    ok = False
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            # Consume body so server doesn't block on close
            resp.read(1024)
            ok = 200 <= resp.status < 400
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.debug("[brain] probe %s -> %s: %s", ep.name, type(e).__name__, e)
        ok = False
    except Exception as e:  # pragma: no cover — defensive
        logger.debug("[brain] probe %s unexpected error: %s", ep.name, e)
        ok = False
    elapsed_ms = (time.time() - started) * 1000.0
    # Latency over budget => unhealthy even if HTTP 200
    if ok and elapsed_ms > timeout_s * 1000.0:
        ok = False
    ep.healthy = ok
    ep.last_check_ts = time.time()
    if ep.avg_latency_ms <= 0.0:
        ep.avg_latency_ms = elapsed_ms
    else:
        ep.avg_latency_ms = 0.7 * ep.avg_latency_ms + 0.3 * elapsed_ms
    return ep


def brain_health_probe(
    endpoints: list[CerveletEndpoint],
    timeout_s: float = 5.0,
    max_workers: int = 4,
) -> list[CerveletEndpoint]:
    """Probe all endpoints in parallel. Returns the same list (mutated).

    Non-blocking via ThreadPoolExecutor. An endpoint is marked unhealthy if
    it returns HTTP error or takes more than `timeout_s` seconds.
    """
    if not endpoints:
        return endpoints
    workers = min(max_workers, len(endpoints))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="brain_probe") as pool:
        futs = {pool.submit(_probe_one, ep, timeout_s): ep for ep in endpoints}
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception as e:  # pragma: no cover
                ep = futs[fut]
                logger.warning("[brain] probe future %s failed: %s", ep.name, e)
                ep.healthy = False
                ep.last_check_ts = time.time()
    healthy_count = sum(1 for e in endpoints if e.healthy)
    logger.info("[brain] probe done: %d/%d healthy", healthy_count, len(endpoints))
    return endpoints


def _is_cloud(ep: CerveletEndpoint) -> bool:
    return ep.kind == "cloud" or ep.name.endswith("_cloud") or "groq" in ep.name.lower()


def _is_local(ep: CerveletEndpoint) -> bool:
    return not _is_cloud(ep) and ep.kind != "edge"


def _pick_weighted(candidates: list[CerveletEndpoint]) -> CerveletEndpoint | None:
    """Weighted-random pick across healthy candidates (favoring lower latency)."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    weights = []
    for ep in candidates:
        # Latency-aware weight : raw weight / max(latency, 1ms)
        lat = max(ep.avg_latency_ms, 1.0)
        weights.append(ep.weight * (1000.0 / lat))
    try:
        return random.choices(candidates, weights=weights, k=1)[0]
    except Exception:
        return candidates[0]


def pick_brain_for_task(
    task_kind: str,
    endpoints: list[CerveletEndpoint],
    system_load: dict | None = None,
) -> CerveletEndpoint | None:
    """Pick the best endpoint given a task kind and current system load.

    Decision matrix :
      - load.ram_free_gb < 2 OR gpu_pct > 85 → cloud endpoint if available
      - elif task_kind == "fast"      → smallest healthy local model
      - elif task_kind == "code"      → llamacpp_native if healthy (specialized + speculative draft)
      - elif task_kind == "reasoning" → ollama heavy model
      - else (summary, embedding...)  → ollama default
      - If no healthy endpoint → None (caller must throttle/retry)

    Args:
        task_kind: one of "code", "reasoning", "fast", "summary", "embedding".
        endpoints: list (presumably already health-probed).
        system_load: typically forge_resource_manager.get_snapshot(). If None,
            we try to fetch it lazily; on failure we assume healthy hardware.

    Returns:
        CerveletEndpoint or None if nothing healthy is suitable.
    """
    healthy = [e for e in endpoints if e.healthy]
    if not healthy:
        return None

    if system_load is None:
        try:
            import sys as _s
            from pathlib import Path as _P

            _app = _P(__file__).resolve().parent
            if str(_app) not in _s.path:
                _s.path.insert(0, str(_app))
            from nokido_agent.app.forge_resource_manager import get_snapshot

            system_load = get_snapshot()
        except Exception:
            system_load = {}

    ram_free = float(system_load.get("ram_free_gb", 999.0) or 999.0)
    gpu_pct = float(system_load.get("gpu_pct") or 0.0)

    # 1. Hardware pressure → cloud
    if ram_free < 2.0 or gpu_pct > 85.0:
        cloud = [e for e in healthy if _is_cloud(e)]
        if cloud:
            logger.info(
                "[brain] pressure (ram_free=%.1f GB, gpu=%.0f%%) -> cloud %s",
                ram_free,
                gpu_pct,
                cloud[0].name,
            )
            return _pick_weighted(cloud)
        # No cloud available — fall through to local but log warning
        logger.warning("[brain] pressure but no cloud endpoint healthy — best-effort local")

    locals_ = [e for e in healthy if _is_local(e)]
    pool = locals_ or healthy

    if task_kind == "fast":
        # Heuristic : smallest model name (lex) or those flagged "fast"
        flagged = [e for e in pool if "fast" in e.capabilities]
        if flagged:
            return _pick_weighted(flagged)
        # Fallback : pick lowest-latency healthy
        return min(pool, key=lambda e: e.avg_latency_ms or 1e9)

    if task_kind == "code":
        # Prefer llamacpp_native (specialized + speculative draft on qwen-coder)
        cpp = [e for e in pool if e.kind == "llamacpp" or "code" in e.capabilities or e.name == "llamacpp_native"]
        if cpp:
            return _pick_weighted(cpp)

    if task_kind == "reasoning":
        flagged = [e for e in pool if "reasoning" in e.capabilities]
        if flagged:
            return _pick_weighted(flagged)

    if task_kind == "embedding":
        flagged = [e for e in pool if "embedding" in e.capabilities]
        if flagged:
            return _pick_weighted(flagged)

    # Default : Ollama
    ollama_eps = [e for e in pool if e.kind == "ollama" or e.name.startswith("ollama")]
    if ollama_eps:
        return _pick_weighted(ollama_eps)

    return _pick_weighted(pool)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint-aware LLM dispatch — bridges Agent.model with CerveletEndpoint
# ─────────────────────────────────────────────────────────────────────────────


def _call_endpoint_chat(
    ep: CerveletEndpoint,
    messages: list[dict[str, Any]],
    tools: list[dict] | None = None,
    temperature: float = 0.2,
    timeout: int = 90,
) -> dict:
    """Generic chat call against any endpoint type.

    For Ollama (kind=="ollama") : POSTs to /api/chat with native schema.
    For llamacpp / openai_compat / cloud : POSTs to /v1/chat/completions.
    For edge : POSTs to /api/swarm/chat (planned, currently same as openai).
    Returns a dict with "message" {role, content} and "tool_calls" lists,
    matching the shape used by `_call_ollama_chat`.
    """
    base = ep.url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if ep.auth_header:
        headers.update(ep.auth_header)

    if ep.kind == "ollama":
        payload: dict[str, Any] = {
            "model": ep.model,
            "stream": False,
            "messages": messages,
            "options": {"temperature": temperature, "num_ctx": 4096},
        }
        if tools:
            payload["tools"] = tools
        url = f"{base}/api/chat"
    else:
        # OpenAI-compat (llama-server, LM Studio, Groq, OpenAI, etc.)
        payload = {
            "model": ep.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        url = f"{base}/v1/chat/completions"

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = json.loads(resp.read().decode("utf-8"))

    # Normalize response shape
    if ep.kind == "ollama":
        return raw  # already {message: {...}, ...}
    # OpenAI-compat → repackage
    choices = raw.get("choices") or []
    if not choices:
        return {"message": {"role": "assistant", "content": ""}, "tool_calls": []}
    msg = choices[0].get("message") or {}
    return {
        "message": {"role": "assistant", "content": msg.get("content", "")},
        "tool_calls": msg.get("tool_calls") or [],
        "_raw_openai": raw,
    }


def _llm_round_via_endpoint(
    agent: Agent,
    ep: CerveletEndpoint,
    messages: list[dict[str, Any]],
    with_tools: bool,
) -> dict:
    """Like `_llm_round` but uses an explicit endpoint (multi-cervelet)."""
    sys_msg = {"role": "system", "content": agent.instructions}
    full = [sys_msg] + messages
    tools_schema = [_build_tool_schema(t) for t in agent.tools] if (with_tools and agent.tools) else None
    return _call_endpoint_chat(ep, full, tools=tools_schema)


def _try_round_with_failover(
    agent: Agent,
    messages: list[dict[str, Any]],
    endpoints: list[CerveletEndpoint],
    task_kind: str = "reasoning",
    with_tools: bool = False,
    max_attempts: int = 3,
) -> tuple[dict, CerveletEndpoint]:
    """Try one round, fall over to the next-healthy endpoint on failure.

    Returns (response_dict, endpoint_used). Raises NoHealthyEndpoint if
    all attempts fail or no healthy endpoint is available.
    """
    tried: set[str] = set()
    last_exc: Exception | None = None
    for _ in range(max_attempts):
        candidates = [e for e in endpoints if e.healthy and e.name not in tried]
        if not candidates:
            break
        ep = pick_brain_for_task(task_kind, candidates, system_load=None) or candidates[0]
        tried.add(ep.name)
        try:
            response = _llm_round_via_endpoint(agent, ep, messages, with_tools)
            return response, ep
        except Exception as e:
            logger.warning("[brain] endpoint %s failed mid-flight: %s", ep.name, e)
            ep.healthy = False
            ep.last_check_ts = time.time()
            last_exc = e
    raise NoHealthyEndpoint(f"All endpoints exhausted for task_kind={task_kind} (last_exc={last_exc!r})")


# ─────────────────────────────────────────────────────────────────────────────
# Resource gate — uniform throttle / request_resources check
# ─────────────────────────────────────────────────────────────────────────────


def _resource_gate(needed_ram_gb: float = 2.0) -> tuple[bool, str]:
    """Check throttle + request_resources. Returns (ok, reason).

    Returns (False, reason) if we should defer / fall back to cloud.
    Returns (True, "") if it's safe to proceed locally.
    Never raises — failures default to "ok".
    """
    try:
        import sys as _s
        from pathlib import Path as _P

        _app = _P(__file__).resolve().parent
        if str(_app) not in _s.path:
            _s.path.insert(0, str(_app))
        from nokido_agent.app.forge_resource_manager import should_throttle as _st

        if _st():
            return False, "should_throttle=True"
    except Exception:
        pass
    try:
        from nokido_agent.app.forge_resource_manager import request_resources as _rr  # type: ignore

        plan = _rr(needed_ram_gb=needed_ram_gb, allow_evict=False)
        if not plan.get("ok", True):
            return False, f"request_resources not ok ({plan.get('reason', '?')})"
    except (ImportError, AttributeError):
        # request_resources not yet implemented — soft pass
        pass
    except Exception:
        pass
    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# Workflow modes — linear / parallel / cross / distant (stub)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class WorkflowResult:
    mode: str  # "linear" | "parallel" | "cross"
    final_text: str | None  # consolidated answer (linear) or None
    per_agent: list[dict[str, Any]]  # [{agent, endpoint, content, latency_ms}]
    rounds: int  # logical rounds (1 for parallel/linear, N for cross)
    transfers: list[tuple[str, str]] = field(default_factory=list)


def run_workflow_linear(
    query: str,
    agents: list[Agent],
    endpoints: list[CerveletEndpoint],
    task_kind: str = "reasoning",
) -> WorkflowResult:
    """Sequential pipeline : output(N) becomes input(N+1).

    Each agent picks the best healthy endpoint via pick_brain_for_task.
    On endpoint failure mid-flight, retries with the next-healthy endpoint
    via _try_round_with_failover.
    """
    if not agents:
        raise ValueError("run_workflow_linear: agents list must be non-empty")
    ok, reason = _resource_gate(needed_ram_gb=4.0)
    if not ok:
        # Force cloud-only pool if available
        cloud_only = [e for e in endpoints if _is_cloud(e) and e.healthy]
        if not cloud_only:
            raise ResourceExhausted(f"linear: local pressure ({reason}) and no cloud endpoint")
        endpoints = cloud_only

    per_agent: list[dict[str, Any]] = []
    current_input = query
    for idx, agent in enumerate(agents):
        messages = [{"role": "user", "content": current_input}]
        started = time.time()
        response, ep = _try_round_with_failover(
            agent,
            messages,
            endpoints,
            task_kind=task_kind,
            with_tools=False,
        )
        elapsed_ms = (time.time() - started) * 1000.0
        content = (response.get("message") or {}).get("content", "") or ""
        per_agent.append(
            {
                "agent": agent.name,
                "endpoint": ep.name,
                "content": content,
                "latency_ms": round(elapsed_ms, 1),
                "stage": idx,
            }
        )
        current_input = content  # feed next agent

    return WorkflowResult(
        mode="linear",
        final_text=current_input,
        per_agent=per_agent,
        rounds=1,
    )


def run_workflow_parallel(
    query: str,
    agents: list[Agent],
    endpoints: list[CerveletEndpoint],
    task_kind: str = "reasoning",
    max_workers: int | None = None,
) -> WorkflowResult:
    """Broadcast the same query to N agents simultaneously (threaded).

    Returns a WorkflowResult with per_agent populated. final_text is None —
    caller must post-process (vote, merge, pick best).
    If 1 endpoint fails, others continue.
    """
    if not agents:
        raise ValueError("run_workflow_parallel: agents list must be non-empty")
    ok, reason = _resource_gate(needed_ram_gb=2.0)
    if not ok:
        cloud_only = [e for e in endpoints if _is_cloud(e) and e.healthy]
        if not cloud_only:
            raise ResourceExhausted(f"parallel: local pressure ({reason}) and no cloud endpoint")
        endpoints = cloud_only

    workers = max_workers or min(8, len(agents))

    def _one(agent: Agent) -> dict[str, Any]:
        messages = [{"role": "user", "content": query}]
        started = time.time()
        try:
            response, ep = _try_round_with_failover(
                agent,
                messages,
                endpoints,
                task_kind=task_kind,
                with_tools=False,
            )
            content = (response.get("message") or {}).get("content", "") or ""
            return {
                "agent": agent.name,
                "endpoint": ep.name,
                "content": content,
                "latency_ms": round((time.time() - started) * 1000.0, 1),
                "ok": True,
            }
        except Exception as e:
            return {
                "agent": agent.name,
                "endpoint": None,
                "content": f"ERR: {type(e).__name__}: {e}",
                "latency_ms": round((time.time() - started) * 1000.0, 1),
                "ok": False,
            }

    per_agent: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="hf_parallel") as pool:
        futs = {pool.submit(_one, a): a for a in agents}
        for fut in as_completed(futs):
            per_agent.append(fut.result())

    # Restore original agent order in result
    name_to_idx = {a.name: i for i, a in enumerate(agents)}
    per_agent.sort(key=lambda r: name_to_idx.get(r.get("agent", ""), 999))
    return WorkflowResult(
        mode="parallel",
        final_text=None,
        per_agent=per_agent,
        rounds=1,
    )


def run_workflow_cross(
    query: str,
    agents: list[Agent],
    endpoints: list[CerveletEndpoint],
    rounds: int = 3,
    task_kind: str = "reasoning",
) -> WorkflowResult:
    """Multi-round critique pipeline (LLM-Blender-inspired, simplified).

    Round 1 : every agent answers `query` independently (parallel).
    Rounds 2..N : each agent reviews all peer answers from round N-1 and
                   produces an updated answer, until rounds is exhausted.
    Useful for ambiguous questions where multiple perspectives matter.

    Inspired by LLM-Blender (arxiv 2306.02561) but without the trained
    fusion model — we just iterate cross-critique and let the caller
    pick / merge the final answers.
    """
    if not agents:
        raise ValueError("run_workflow_cross: agents list must be non-empty")
    if rounds < 1:
        raise ValueError("rounds must be >= 1")

    history: list[list[dict[str, Any]]] = []  # per-round per-agent results

    # Round 1 — fresh answers (reuse parallel logic)
    r1 = run_workflow_parallel(query, agents, endpoints, task_kind=task_kind)
    history.append(r1.per_agent)

    for r in range(2, rounds + 1):
        # Build critique prompt = original query + peer answers (anonymized)
        prev = history[-1]
        peer_block = "\n\n".join(f"--- Peer #{i + 1} ---\n{p.get('content', '')}" for i, p in enumerate(prev))
        critique_query = (
            f"Question initiale :\n{query}\n\n"
            f"Reponses des pairs au tour precedent :\n{peer_block}\n\n"
            f"Critique les reponses des pairs et propose ta reponse mise a jour. "
            f"Sois concis."
        )
        r_next = run_workflow_parallel(critique_query, agents, endpoints, task_kind=task_kind)
        # Tag round number
        for entry in r_next.per_agent:
            entry["round"] = r
        history.append(r_next.per_agent)

    # Flatten history into per_agent (with round annotations)
    flat: list[dict[str, Any]] = []
    for r_idx, round_results in enumerate(history, start=1):
        for entry in round_results:
            entry.setdefault("round", r_idx)
            flat.append(entry)

    return WorkflowResult(
        mode="cross",
        final_text=None,  # caller decides convergence / fusion
        per_agent=flat,
        rounds=rounds,
    )


def cascade_dispatch(
    query: str,
    agents: list[Agent],
    endpoints: list[CerveletEndpoint],
    sessions: list | None = None,
    sess_ids: list[str] | None = None,
    tau: float = -4.0,
    task_kind: str = "reasoning",
) -> WorkflowResult:
    """Route to linear (S1) or parallel (S2) workflow via CascadeOracle.

    If `sessions` / `sess_ids` are provided, the CascadeOracle scores the
    query against them using BM25 + CrossEncoder and checks whether the
    CE score is below `tau`. When escalated (S2), all agents run in
    parallel for more thorough coverage. When S1 is confident, only
    agents[0] runs (linear, fast).

    Falls back to parallel dispatch if CascadeOracle import fails.
    """
    import sys as _s
    from pathlib import Path as _P

    _app = str(_P(__file__).parent)
    if _app not in _s.path:
        _s.path.insert(0, _app)

    escalate = True  # default: safe fallback = parallel
    oracle_meta: dict = {}
    if sessions and sess_ids:
        try:
            from nokido_agent.app.forge_cascade_oracle import CascadeOracle

            oracle = CascadeOracle(tau=tau)
            result = oracle.retrieve(query, sessions, sess_ids)
            escalate = result.escalated
            oracle_meta = {
                "ce_score": result.ce_score_top1,
                "system": result.system_used,
                "latency_ms": result.latency_ms,
                "n_candidates": result.n_candidates,
            }
            logger.info(
                "[cascade_dispatch] %s (ce=%.2f tau=%.1f esc=%s)",
                result.system_used,
                result.ce_score_top1,
                tau,
                escalate,
            )
        except Exception as e:
            logger.warning("[cascade_dispatch] CascadeOracle failed: %s — using parallel", e)

    if escalate:
        wf = run_workflow_parallel(query, agents, endpoints, task_kind=task_kind)
    else:
        wf = run_workflow_linear(query, agents[:1], endpoints, task_kind=task_kind)

    # Annotate with oracle metadata
    for entry in wf.per_agent:
        entry["oracle"] = oracle_meta
    return wf


def run_workflow_distant(
    query: str,
    agents: list[Agent],
    edge_endpoint: CerveletEndpoint,
    **kwargs: Any,
) -> WorkflowResult:
    """STUB — route a workflow to a Tailscale-mesh edge node.

    Planned behavior :
        1. GET edge_endpoint.url + "/api/swarm/health" — must return 200
           with body containing `{"can_accept_load": true, ...}`.
        2. POST the workflow descriptor (query + agents serialized) to
           edge_endpoint.url + "/api/swarm/dispatch".
        3. Poll for completion or stream SSE results.
        4. Validate response via SemanticFirewall.post_flight before merge.

    Currently raises NotImplementedError. The signature is locked so callers
    can integrate now and the implementation lands later without breaking.

    Cross-ref :
        - forge_semantic_firewall.post_flight for response validation
        - forge_sovereign_membrane.wrap for outbound payload sanitization
    """
    # Best-effort liveness probe so callers can at least know if the edge is up
    try:
        _probe_one(edge_endpoint, timeout_s=3.0)
    except Exception:
        pass
    raise NotImplementedError(
        "run_workflow_distant: planned — Tailscale edge dispatch not yet wired. "
        "Use run_workflow_linear/parallel/cross with a remote endpoint URL "
        "for now."
    )


# ─────────────────────────────────────────────────────────────────────────────
# HandoffRouter — orchestrator entry point for multi-cervelet workflows
# ─────────────────────────────────────────────────────────────────────────────


class HandoffRouter:
    """Top-level orchestrator for multi-cervelet workflows.

    Owns the endpoint pool, manages periodic health refresh, and dispatches
    to the chosen workflow mode (linear / parallel / cross / distant).

    Example :
        endpoints = [
            CerveletEndpoint(name="ollama_local", url="http://127.0.0.1:11434",
                             model="qwen2.5-coder:7b-instruct-q4_K_M",
                             kind="ollama"),
            CerveletEndpoint(name="llamacpp_native", url="http://127.0.0.1:8091",
                             model="qwen2.5-coder:7b-instruct-q4_K_M",
                             kind="llamacpp", capabilities=["code", "fast"]),
        ]
        router = HandoffRouter(endpoints)
        out = router.execute(query="X", agents=[a1, a2], mode="linear")
    """

    def __init__(self, endpoints: list[CerveletEndpoint]):
        self.endpoints: list[CerveletEndpoint] = list(endpoints)
        self.last_health_ts: float = 0.0
        self._lock = threading.Lock()

    def add_endpoint(self, ep: CerveletEndpoint) -> None:
        with self._lock:
            self.endpoints.append(ep)

    def remove_endpoint(self, name: str) -> bool:
        with self._lock:
            before = len(self.endpoints)
            self.endpoints = [e for e in self.endpoints if e.name != name]
            return len(self.endpoints) < before

    def healthy_endpoints(self) -> list[CerveletEndpoint]:
        return [e for e in self.endpoints if e.healthy]

    def refresh_health(self, max_age_s: float = 30.0, force: bool = False) -> list[CerveletEndpoint]:
        """Re-probe endpoints if last probe is older than max_age_s.

        Returns the (possibly updated) endpoint list.
        """
        now = time.time()
        if not force and (now - self.last_health_ts) < max_age_s:
            return self.endpoints
        with self._lock:
            brain_health_probe(self.endpoints)
            self.last_health_ts = time.time()
        return self.endpoints

    def execute(
        self,
        query: str,
        agents: list[Agent],
        mode: str = "linear",
        **kwargs: Any,
    ) -> WorkflowResult:
        """Dispatch to the chosen workflow mode.

        Args:
            query: user question.
            agents: list of Agent instances participating in the workflow.
            mode: "linear" | "parallel" | "cross" | "distant".
            **kwargs: forwarded to the workflow function (e.g. rounds=3
                for cross, task_kind="code", edge_endpoint=... for distant).
        """
        self.refresh_health()
        if mode == "linear":
            return run_workflow_linear(query, agents, self.endpoints, **kwargs)
        if mode == "parallel":
            return run_workflow_parallel(query, agents, self.endpoints, **kwargs)
        if mode == "cross":
            return run_workflow_cross(query, agents, self.endpoints, **kwargs)
        if mode == "distant":
            edge = kwargs.pop("edge_endpoint", None)
            if edge is None:
                # Try to pick an edge endpoint from the pool
                edges = [e for e in self.endpoints if e.kind == "edge"]
                if not edges:
                    raise ValueError("mode=distant: no edge endpoint provided or available")
                edge = edges[0]
            return run_workflow_distant(query, agents, edge, **kwargs)
        raise ValueError(f"Unknown workflow mode: {mode!r} (linear|parallel|cross|distant)")


def default_local_endpoints() -> list[CerveletEndpoint]:
    """Helper : returns the canonical 2-cervelet local pool (Ollama + llama-server).

    Matches the Nokido stack documented in CLAUDE.md section 8 :
        - Ollama :11434
        - llama-server :8091 NSSM `NokidoLlamaNative`
    """
    return [
        CerveletEndpoint(
            name="ollama_local",
            url="http://127.0.0.1:11434",
            model="qwen2.5-coder:7b-instruct-q4_K_M",
            kind="ollama",
            weight=1.0,
            capabilities=["reasoning", "summary"],
        ),
        CerveletEndpoint(
            name="llamacpp_native",
            url="http://127.0.0.1:8091",
            model="qwen2.5-coder:7b-instruct-q4_K_M",
            kind="llamacpp",
            weight=1.2,
            capabilities=["code", "fast"],
        ),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# CLI smoke test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys, io as _io

    if "--selftest-dyn" in sys.argv:
        # E2E : un outil forge est visible dans le swarm (augment tools+instr + exec via Callable).
        _ensure_app_on_path()
        from nokido_agent.app import forge_tool_forger as _tf

        _code = "def hello_dyn(x: int = 1) -> dict:\n    return {'doubled': x * 2}\n"
        _p = _tf._save_tool("hello_dyn", _code, "double la valeur x", "def hello_dyn(x: int) -> dict")
        _tf._registry_add("hello_dyn", "double la valeur x", "def hello_dyn(x: int) -> dict", str(_p))
        try:
            _a = Agent(name="t", instructions="base", tools=[])
            _aug = _augment_with_dynamic_tools(_a)
            _names = [t.__name__ for t in _aug.tools]
            assert "forge_call_dynamic" in _names, _names
            assert "OUTILS DYNAMIQUES" in _aug.instructions and "hello_dyn" in _aug.instructions
            _fn = next(t for t in _aug.tools if t.__name__ == "forge_call_dynamic")
            _r = _fn(name="hello_dyn", kwargs={"x": 5})
            assert _r.get("result", {}).get("doubled") == 10, _r
            print("SELFTEST-DYN OK | swarm voit l'outil forge (tools+instr) + exec=10")
        finally:
            try:
                _p.unlink()
            except Exception:
                pass
            _rr = _tf._registry_load()
            _rr.pop("hello_dyn", None)
            _tf._registry_save(_rr)
        sys.exit(0)

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(description="forge_handoff smoke test")
    sub = p.add_subparsers(dest="cmd")

    # legacy "swarm" smoke (default if no subcommand)
    p.add_argument("query", nargs="?", default=None, help="(swarm) User question")
    p.add_argument("--triage-model", default="qwen2.5-coder:7b-instruct-q4_K_M")
    p.add_argument("--specialist-model", default="qwen2.5-coder:7b-instruct-q4_K_M")

    wf = sub.add_parser("workflow", help="Run multi-cervelet workflow")
    wf.add_argument("mode", choices=["linear", "parallel", "cross", "distant", "probe"])
    wf.add_argument("wf_query", nargs="?", default="")
    wf.add_argument("--rounds", type=int, default=2, help="cross only")
    wf.add_argument("--model", default="qwen2.5-coder:7b-instruct-q4_K_M")
    wf.add_argument("--task-kind", default="reasoning", choices=["code", "reasoning", "fast", "summary", "embedding"])

    args = p.parse_args()

    # ------ workflow subcommand ------
    if args.cmd == "workflow":
        eps = default_local_endpoints()
        # Override model name for both endpoints
        for ep in eps:
            ep.model = args.model

        router = HandoffRouter(eps)
        router.refresh_health(force=True)
        print("=== Endpoints ===")
        for e in router.endpoints:
            print(f"  {e.name:18s} healthy={e.healthy} lat={e.avg_latency_ms:.0f}ms url={e.url}")

        if args.mode == "probe":
            sys.exit(0)

        if not args.wf_query:
            print("ERR: query required for workflow modes other than probe", file=sys.stderr)
            sys.exit(2)

        # Two simple agents
        a_synth = Agent(
            name="Synthese",
            instructions="Reponds en 2-3 lignes max, francais, precis.",
            model=args.model,
            text_handoff=False,
        )
        a_critic = Agent(
            name="Critique",
            instructions=(
                "Tu es l'esprit critique. Examine le contexte recu et "
                "produis une reponse ou un raffinement en 2-3 lignes."
            ),
            model=args.model,
            text_handoff=False,
        )
        agents = [a_synth, a_critic]

        try:
            if args.mode == "linear":
                out = router.execute(args.wf_query, agents, mode="linear", task_kind=args.task_kind)
            elif args.mode == "parallel":
                out = router.execute(args.wf_query, agents, mode="parallel", task_kind=args.task_kind)
            elif args.mode == "cross":
                out = router.execute(args.wf_query, agents, mode="cross", rounds=args.rounds, task_kind=args.task_kind)
            elif args.mode == "distant":
                # Inject a placeholder edge endpoint so the stub can be exercised
                edge = CerveletEndpoint(
                    name="edge_node_demo",
                    url="http://127.0.0.1:9999",
                    model=args.model,
                    kind="edge",
                )
                out = router.execute(args.wf_query, agents, mode="distant", edge_endpoint=edge)
            else:
                raise SystemExit(f"unhandled mode: {args.mode}")
        except NotImplementedError as e:
            print(f"[distant stub] {e}")
            sys.exit(0)
        except (ResourceExhausted, NoHealthyEndpoint) as e:
            print(f"[abort] {type(e).__name__}: {e}")
            sys.exit(3)

        print(f"\n=== Workflow {out.mode} | rounds={out.rounds} ===")
        for entry in out.per_agent:
            r = entry.get("round", 1)
            print(f"  [r{r}] {entry.get('agent'):15s} via {entry.get('endpoint')} ({entry.get('latency_ms', 0):.0f}ms)")
            print(f"        {(entry.get('content') or '')[:200]}")
        if out.final_text:
            print(f"\n=== Final ===\n{out.final_text}")
        sys.exit(0)

    # ------ default : legacy run_swarm smoke ------
    if not args.query:
        p.print_help()
        sys.exit(2)

    network_agent = Agent(
        name="Architecte_Reseau",
        instructions=(
            "Tu es l'expert reseau de Nokido. Reponds aux questions sur "
            "ports, MCP, netcfg-agent, ADR reseau. 3 lignes max."
        ),
        model=args.specialist_model,
    )
    rag_agent = Agent(
        name="RAG_Expert",
        instructions=(
            "Tu es l'expert RAG / vectorisation / FTS5. Reponds aux questions "
            "sur embeddings, index, chunks, recherche. 3 lignes max."
        ),
        model=args.specialist_model,
    )
    triage = Agent(
        name="Triage",
        instructions=(
            "Tu route la question utilisateur vers un specialiste.\n"
            "- Reseau / port / MCP / netcfg : reponds UNIQUEMENT 'TRANSFER_TO: Architecte_Reseau'\n"
            "- RAG / embedding / FTS / vector : reponds UNIQUEMENT 'TRANSFER_TO: RAG_Expert'\n"
            "- Sinon : reponds toi-meme en 1 ligne."
        ),
        model=args.triage_model,
        text_handoff=True,
    )
    registry = {a.name: a for a in [triage, network_agent, rag_agent]}

    result = run_swarm(triage, args.query, available_agents=registry, max_rounds=4)
    print("\n=== Result ===")
    print(f"Final agent: {result.final_agent}")
    print(f"Rounds: {result.n_rounds}")
    print(f"Transfers: {result.transfers}")
    print("\n=== Last message ===")
    print(result.messages[-1].get("content", ""))
