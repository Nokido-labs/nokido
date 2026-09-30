# -*- coding: utf-8 -*-
"""sandbox/hybrid_orchestrator.py — Assembleur (glue) Phase 4 du plan hybride.

Cable HybridStateMachine (sandbox/hybrid_state_machine.py) aux VRAIS organes Nokido.
ANTI-DUP (verifie 2026-07-18): aucun organe ne chaine deja condense->route locale->
fallback Claude->dispatch->retry ; cette glue est la seule, ses ETAPES reutilisent :
  - condenser         -> forge_llm_router.router_call        (LLM local, sync)
  - route locale      -> forge_semantic_route.semantic_route (bge-m3 cosinus, sync, 0 token)
  - extraction Claude -> forge_agent_proxy.ask_claude        (async -> ponte sync)
  - dispatch local    -> forge_mcp_registry.get_registry().dispatch (async -> ponte sync)

LIMITE CONNUE (refinement Phase 2) : semantic_route rend un USE_CASE (topic), pas un
nom d'outil dispatchable. Tant que les centroides ne sont pas enrichis en intents
executables (auto-apprentissage dialogue_win, cf plan Ph2), le fast-path local
echoue souvent au dispatch -> repli Claude via la boucle de resilience (comportement
sain, seulement hit-rate local bas). La glue elle-meme est correcte et testee.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import threading
from typing import Any, Optional

from sandbox.hybrid_state_machine import AgentState, HybridStateMachine

logger = logging.getLogger("hybrid_orchestrator")


def _sync(coro):
    """Pont async->sync robuste (hors ET dans un event loop deja actif)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict = {}

    def _runner():
        loop = asyncio.new_event_loop()
        try:
            box["v"] = loop.run_until_complete(coro)
        finally:
            loop.close()

    t = threading.Thread(target=_runner)
    t.start()
    t.join()
    return box.get("v")


def _text_of(resp: Any) -> str:
    """Extrait le texte d'une reponse LLM (dict a schema variable ou str)."""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        for k in ("response", "text", "content", "answer", "result", "message", "output"):
            v = resp.get(k)
            if isinstance(v, str) and v.strip():
                return v
    return str(resp)


def condense_fn(query: str, history: list) -> str:
    """local_llm_fn : reecrit la requete en question autonome (LLM local via router)."""
    from forge_llm_router import router_call

    hist = " | ".join(
        f"{m.get('role', '?')}: {str(m.get('content', ''))[:200]}" for m in (history or [])[-6:]
    )
    instruction = "Reformuler la requete utilisateur en question autonome integrant le contexte."
    prompt = f"{instruction}\nContexte:\n{hist}\nRequete: {query}\nReformulation:"
    try:
        out = _text_of(router_call(prompt, use_case="general", max_tokens=200)).strip()
        return out or query
    except Exception as e:  # noqa: BLE001
        logger.error(f"condense_fn: fallback requete brute ({e})")
        return query


def route_local_fn(condensed_query: str):
    """embed_router_fn : route semantique locale -> (use_case, score).
    'general' = fallback sous le seuil de semantic_route -> traite comme non fiable (None)."""
    from forge_semantic_route import semantic_route

    use_case, score = semantic_route(condensed_query)
    if use_case and use_case != "general":
        return use_case, float(score)
    return None, float(score or 0.0)


def extract_claude_fn(messages: list) -> dict:
    """claude_fn : extraction intent+params via Claude (ask_claude, parse JSON strict).
    tool_use_id synthetique (ask_claude renvoie du texte, pas l'API tool-calling native)."""
    from forge_agent_proxy import ask_claude

    instruction = "Deduire de la conversation l'outil a appeler et ses parametres, au format JSON."
    schema = '{"intent": "<nom_outil>", "parameters": {}}'
    prompt = f"{instruction} Format attendu: {schema}\nCONVERSATION:\n" + json.dumps(messages, ensure_ascii=False)[:4000]
    data: dict = {}
    try:
        resp = _sync(ask_claude(prompt, rag_context=False, max_tokens=500))
        txt = _text_of(resp)
        s, e = txt.find("{"), txt.rfind("}")
        if s >= 0 and e > s:
            data = json.loads(txt[s : e + 1])
    except Exception as ex:  # noqa: BLE001
        logger.error(f"extract_claude_fn: extraction echouee ({ex})")
    return {
        "intent": data.get("intent"),
        "parameters": data.get("parameters") or {},
        "tool_use_id": "toolu_" + secrets.token_hex(8),
    }


def make_executor_fn(agent: str = "CLAUDE", ring: int = 2):
    """Fabrique local_executor_fn -> dispatch reel via forge_mcp_registry (async ponte)."""

    def _exec(intent: str, parameters: dict):
        from forge_mcp_registry import get_registry

        out = _sync(get_registry().dispatch(intent, parameters or {}, agent, ring))
        if isinstance(out, dict) and out.get("error"):
            raise RuntimeError(str(out["error"])[:300])
        return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)

    return _exec


def build_hybrid_machine(agent: str = "CLAUDE", ring: int = 2) -> HybridStateMachine:
    """Instancie la machine a etats cablee aux organes reels Nokido."""
    return HybridStateMachine(
        local_llm_fn=condense_fn,
        embed_router_fn=route_local_fn,
        claude_fn=extract_claude_fn,
        local_executor_fn=make_executor_fn(agent, ring),
    )


def run_hybrid(query: str, history: Optional[list] = None, agent: str = "CLAUDE", ring: int = 2) -> AgentState:
    """Point d'entree : execute la machine hybride cablee sur une requete."""
    return build_hybrid_machine(agent, ring).run(query, history)
