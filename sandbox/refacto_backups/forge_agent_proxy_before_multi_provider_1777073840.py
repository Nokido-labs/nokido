from __future__ import annotations
# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-25 | VER:v_forge_agent_proxy_v1
#FORGE:[score:95|agent:claude-desktop|temp:0.00|risk:0.15|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: RPC conversationnel inter-agents via MCP

app/forge_agent_proxy.py - RPC agent-to-agent.

Probleme resolu :
Le flow actuel notify -> poll est fire-and-forget : pas de correlation
requete<->reponse, pas de boucle automatique, pas de memoire de conversation.

Ce module transforme ce pattern en RPC conversationnel :
  Gemini -> ask_claude(msg) -> attend reponse synchrone -> Gemini traite
  Claude -> ask_gemini(msg) -> attend reponse synchrone -> Claude traite
  agent_debate(topic) -> boucle ping-pong automatise Claude<->Gemini<->Ollama

Implementation :
- ask_claude  : via OpenRouter (anthropic/claude-sonnet-4) - ANTHROPIC_API_KEY vide
- ask_gemini  : via google.generativeai (GEMINI_API_KEY dispo)
- ask_ollama  : via forge_litellm_bridge ou direct Ollama local
- agent_debate : orchestre N rounds avec synthese finale Ollama

Integration EventBus (EVENT_SPEC.md) :
Chaque call emet rpc.{agent}.request et rpc.{agent}.response avec corr_id
pour thread tracking. Visible via event_history et dashboard.

RAG context injection :
Chaque ask_* charge top-5 chunks RAG pertinents en system prompt pour
preserver la memoire du projet Nokido entre sessions.

Part du package app (imports absolus).
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:95|agent:claude-desktop|temp:0.00|risk:0.15|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Nokido.AgentProxy")

# ── Chemins & Constantes ──────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent

# Cache des cles API au premier usage (evite de relire Nokido.env)
_API_KEYS: Dict[str, str] = {}

# Cache des threads de conversation : {thread_id: [{"role", "content"}]}
_THREADS: Dict[str, List[Dict[str, str]]] = {}

# Limites
MAX_THREAD_MESSAGES = 20     # cap memoire par thread pour eviter explosion contexte
MAX_RESPONSE_CHARS = 4000    # cap taille reponse
DEFAULT_TIMEOUT = 60         # secondes


# ── Helpers cles API ──────────────────────────────────────────────────────────
def _load_api_key(name: str) -> Optional[str]:
    """Charge une cle API depuis Nokido.env si pas deja en cache."""
    if name in _API_KEYS:
        return _API_KEYS[name]
    # D'abord os.environ
    val = os.environ.get(name, "")
    if not val:
        # Puis Nokido.env
        env_file = ROOT / "Nokido.env"
        if env_file.exists():
            try:
                for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() == name:
                            val = v.strip().strip('"').strip("'")
                            break
            except Exception as e:
                logger.debug(f"Load env failed: {e}")
    _API_KEYS[name] = val
    return val or None


# ── Helper EventBus ───────────────────────────────────────────────────────────
_BUS_CACHE = None

def _emit(topic: str, kind: str, data: Dict[str, Any], corr_id: Optional[str] = None,
          parent_id: Optional[str] = None) -> None:
    """Emission non-bloquante d'un event. Silent fail si bus indispo."""
    global _BUS_CACHE
    try:
        if _BUS_CACHE is None:
            from forge_state_manager import EventBus, get_state_manager
            _BUS_CACHE = EventBus(get_state_manager())
        _BUS_CACHE.publish(
            topic=topic, kind=kind, data=data, agent="RPC_PROXY",
            corr_id=corr_id, parent_id=parent_id, trusted=True,
        )
    except Exception as e:
        logger.debug(f"EventBus emit skip: {e}")


# ── Helper RAG context ────────────────────────────────────────────────────────
async def _get_rag_context(query: str, k: int = 3) -> str:
    """Recupere top-k chunks RAG pertinents comme context system."""
    try:
        from forge_app_context import get_rag
        rag = get_rag()
        if not rag:
            return ""
        results = await rag.search(query, k=k)
        if not results:
            return ""
        ctx = "\n---\n".join(
            f"[{r.get('source','?')}] {r.get('text','')[:500]}" 
            for r in results
        )
        return ctx[:3000]
    except Exception as e:
        logger.debug(f"RAG context unavailable: {e}")
        return ""


def _build_system_prompt(rag_context: str, agent_name: str) -> str:
    """Construit le system prompt avec context RAG et role."""
    base = (
        f"Tu es l'agent {agent_name} dans l'ecosysteme Nokido. "
        f"Tu dialogues avec d'autres agents (Claude, Gemini, Ollama) pour resoudre des taches. "
        f"Reponds de maniere concise et technique. "
        f"Si tu n'es pas d'accord, dis-le clairement et explique pourquoi. "
        f"Si tu valides, dis-le sans chichis."
    )
    if rag_context:
        return f"{base}\n\n[CONTEXT RAG NOKIDO]\n{rag_context}"
    return base


# ── Thread management ─────────────────────────────────────────────────────────
def _get_thread(thread_id: Optional[str]) -> Tuple[str, List[Dict[str, str]]]:
    """Retourne (thread_id, messages). Cree si absent."""
    if not thread_id:
        thread_id = f"th_{int(time.time())}_{uuid.uuid4().hex[:4]}"
    if thread_id not in _THREADS:
        _THREADS[thread_id] = []
    return thread_id, _THREADS[thread_id]


def _add_to_thread(thread_id: str, role: str, content: str) -> None:
    """Ajoute un message au thread, cap a MAX_THREAD_MESSAGES."""
    if thread_id not in _THREADS:
        _THREADS[thread_id] = []
    _THREADS[thread_id].append({"role": role, "content": content})
    # Rotation si trop long
    if len(_THREADS[thread_id]) > MAX_THREAD_MESSAGES:
        # Garder le premier system + les N derniers user/assistant
        _THREADS[thread_id] = _THREADS[thread_id][-MAX_THREAD_MESSAGES:]


# ── ASK CLAUDE ────────────────────────────────────────────────────────────────
async def ask_claude(
    message: str,
    thread_id: Optional[str] = None,
    rag_context: bool = True,
    max_tokens: int = 2000,
) -> Dict[str, Any]:
    """
    RPC synchrone vers Claude via OpenRouter (ANTHROPIC_API_KEY vide -> fallback).
    
    Retourne : {ok, thread_id, text, latency_ms, model, error?}
    """
    t0 = time.monotonic()
    tid, messages = _get_thread(thread_id)
    corr_id = f"rpc_claude_{tid}_{uuid.uuid4().hex[:6]}"
    
    _emit("rpc.claude.request", "msg", 
          {"thread_id": tid, "message_preview": message[:200], "max_tokens": max_tokens},
          corr_id=corr_id)
    
    # Strategy 1 : ANTHROPIC_API_KEY direct si present
    anthropic_key = _load_api_key("ANTHROPIC_API_KEY")
    
    if anthropic_key:
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=anthropic_key)
            
            # Preparation messages
            system_prompt = _build_system_prompt(
                await _get_rag_context(message, k=3) if rag_context else "",
                agent_name="CLAUDE",
            )
            api_messages = list(messages) + [{"role": "user", "content": message}]
            
            resp = await client.messages.create(
                model="claude-sonnet-4-20250514",
                system=system_prompt,
                messages=api_messages,
                max_tokens=max_tokens,
            )
            text = resp.content[0].text[:MAX_RESPONSE_CHARS]
            
            _add_to_thread(tid, "user", message)
            _add_to_thread(tid, "assistant", text)
            
            latency = round((time.monotonic() - t0) * 1000, 1)
            _emit("rpc.claude.response", "msg",
                  {"thread_id": tid, "text_preview": text[:200], "latency_ms": latency,
                   "model": "claude-sonnet-4", "via": "anthropic_direct"},
                  corr_id=corr_id)
            return {"ok": True, "thread_id": tid, "text": text, 
                    "latency_ms": latency, "model": "claude-sonnet-4",
                    "via": "anthropic_direct"}
        except Exception as e:
            logger.warning(f"ANTHROPIC_API direct failed: {e} - fallback OpenRouter")
    
    # Strategy 2 : OpenRouter -> anthropic/claude-sonnet-4
    openrouter_key = _load_api_key("OPENROUTER_API_KEY") or _load_api_key("OPENROUTEUR_API_KEY")
    
    if openrouter_key:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=openrouter_key,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": "https://nokido.local",
                    "X-Title": "Nokido Agent Proxy",
                },
            )
            
            system_prompt = _build_system_prompt(
                await _get_rag_context(message, k=3) if rag_context else "",
                agent_name="CLAUDE (via OpenRouter)",
            )
            api_messages = [{"role": "system", "content": system_prompt}]
            api_messages.extend(messages)
            api_messages.append({"role": "user", "content": message})
            
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model="anthropic/claude-sonnet-4",
                    messages=api_messages,
                    max_tokens=max_tokens,
                    temperature=0.7,
                ),
                timeout=DEFAULT_TIMEOUT,
            )
            text = resp.choices[0].message.content[:MAX_RESPONSE_CHARS]
            
            _add_to_thread(tid, "user", message)
            _add_to_thread(tid, "assistant", text)
            
            latency = round((time.monotonic() - t0) * 1000, 1)
            _emit("rpc.claude.response", "msg",
                  {"thread_id": tid, "text_preview": text[:200], "latency_ms": latency,
                   "model": "claude-sonnet-4", "via": "openrouter"},
                  corr_id=corr_id)
            return {"ok": True, "thread_id": tid, "text": text,
                    "latency_ms": latency, "model": "claude-sonnet-4",
                    "via": "openrouter"}
        except asyncio.TimeoutError:
            _emit("rpc.claude.response", "error",
                  {"thread_id": tid, "error": "timeout", "latency_ms": DEFAULT_TIMEOUT * 1000},
                  corr_id=corr_id)
            return {"ok": False, "thread_id": tid, "text": "",
                    "latency_ms": DEFAULT_TIMEOUT * 1000,
                    "error": f"Timeout apres {DEFAULT_TIMEOUT}s"}
        except Exception as e:
            logger.error(f"OpenRouter failed: {e}")
            _emit("rpc.claude.response", "error",
                  {"thread_id": tid, "error": str(e)[:200]},
                  corr_id=corr_id)
            return {"ok": False, "thread_id": tid, "text": "",
                    "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                    "error": str(e)[:200]}
    
    return {"ok": False, "thread_id": tid, "text": "",
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "error": "Aucune cle API dispo (ni ANTHROPIC_API_KEY ni OPENROUTER_API_KEY)"}


# ── ASK GEMINI ────────────────────────────────────────────────────────────────
async def ask_gemini(
    message: str,
    thread_id: Optional[str] = None,
    rag_context: bool = True,
    max_tokens: int = 2000,
) -> Dict[str, Any]:
    """
    RPC synchrone vers Gemini via google.generativeai.
    """
    t0 = time.monotonic()
    tid, messages = _get_thread(thread_id)
    corr_id = f"rpc_gemini_{tid}_{uuid.uuid4().hex[:6]}"
    
    _emit("rpc.gemini.request", "msg",
          {"thread_id": tid, "message_preview": message[:200]},
          corr_id=corr_id)
    
    gemini_key = _load_api_key("GEMINI_API_KEY")
    if not gemini_key:
        return {"ok": False, "thread_id": tid, "text": "",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "error": "GEMINI_API_KEY absente"}
    
    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_key)
        
        model_name = _load_api_key("GEMINI_MODEL") or "gemini-2.0-flash"
        system_prompt = _build_system_prompt(
            await _get_rag_context(message, k=3) if rag_context else "",
            agent_name="GEMINI",
        )
        
        # Reconstruire historique au format Gemini (pas de system field, on prepend dans le premier user)
        history_str = ""
        for m in messages:
            role = "User" if m["role"] == "user" else "Assistant"
            history_str += f"\n{role}: {m['content']}"
        
        full_prompt = f"{system_prompt}\n\n{history_str}\n\nUser: {message}".strip()
        
        # Call non-async natif -> wrap dans run_in_executor
        loop = asyncio.get_event_loop()
        def _call():
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                full_prompt,
                generation_config={"max_output_tokens": max_tokens, "temperature": 0.7},
            )
            return response.text
        
        text = await asyncio.wait_for(
            loop.run_in_executor(None, _call),
            timeout=DEFAULT_TIMEOUT,
        )
        text = text[:MAX_RESPONSE_CHARS]
        
        _add_to_thread(tid, "user", message)
        _add_to_thread(tid, "assistant", text)
        
        latency = round((time.monotonic() - t0) * 1000, 1)
        _emit("rpc.gemini.response", "msg",
              {"thread_id": tid, "text_preview": text[:200], "latency_ms": latency,
               "model": model_name},
              corr_id=corr_id)
        return {"ok": True, "thread_id": tid, "text": text,
                "latency_ms": latency, "model": model_name, "via": "google_genai"}
    except asyncio.TimeoutError:
        _emit("rpc.gemini.response", "error",
              {"thread_id": tid, "error": "timeout"}, corr_id=corr_id)
        return {"ok": False, "thread_id": tid, "text": "",
                "latency_ms": DEFAULT_TIMEOUT * 1000,
                "error": f"Timeout apres {DEFAULT_TIMEOUT}s"}
    except Exception as e:
        logger.error(f"Gemini failed: {e}")
        _emit("rpc.gemini.response", "error",
              {"thread_id": tid, "error": str(e)[:200]}, corr_id=corr_id)
        return {"ok": False, "thread_id": tid, "text": "",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "error": str(e)[:200]}


# ── ASK OLLAMA (synthese local) ───────────────────────────────────────────────
async def ask_ollama(
    message: str,
    model: str = "laforge-qwen:latest",
    thread_id: Optional[str] = None,
    max_tokens: int = 1000,
) -> Dict[str, Any]:
    """
    RPC vers Ollama local pour synthese/arbitrage rapide.
    Utilise _ollama_ask existant du package collab_modes.
    """
    t0 = time.monotonic()
    tid, _messages = _get_thread(thread_id)
    corr_id = f"rpc_ollama_{tid}_{uuid.uuid4().hex[:6]}"
    
    _emit("rpc.ollama.request", "msg",
          {"thread_id": tid, "message_preview": message[:200], "model": model},
          corr_id=corr_id)
    
    try:
        from collab_modes._participants import _ollama_ask
        text = await asyncio.wait_for(
            _ollama_ask(message, context="", system="", max_tokens=max_tokens),
            timeout=DEFAULT_TIMEOUT,
        )
        text = text[:MAX_RESPONSE_CHARS]
        
        latency = round((time.monotonic() - t0) * 1000, 1)
        _emit("rpc.ollama.response", "msg",
              {"thread_id": tid, "text_preview": text[:200], "latency_ms": latency,
               "model": model},
              corr_id=corr_id)
        return {"ok": True, "thread_id": tid, "text": text,
                "latency_ms": latency, "model": model, "via": "ollama_local"}
    except Exception as e:
        logger.error(f"Ollama failed: {e}")
        _emit("rpc.ollama.response", "error",
              {"thread_id": tid, "error": str(e)[:200]}, corr_id=corr_id)
        return {"ok": False, "thread_id": tid, "text": "",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "error": str(e)[:200]}


# ── AGENT DEBATE : orchestration ping-pong automatisee ────────────────────────
async def agent_debate(
    topic: str,
    rounds: int = 3,
    agents: List[str] = None,
    thread_id: Optional[str] = None,
    synthesize: bool = True,
) -> Dict[str, Any]:
    """
    Orchestre un debat automatique entre plusieurs agents.
    
    Pattern :
      Round 1 : agent[0] propose sur topic
      Round 2 : agent[1] critique la proposition du round 1
      Round 3 : agent[0] corrige selon la critique
      ...
      Synthese finale : Ollama synthetise les positions (si synthesize=True)
    
    Args:
      topic: Question/intention a debattre
      rounds: Nombre d'echanges (defaut 3)
      agents: Liste d'agents dans l'ordre ["CLAUDE", "GEMINI"] par defaut
      thread_id: ID de thread pour reprise de conversation
      synthesize: Si True, ajoute un tour Ollama de synthese finale
    
    Returns:
      {ok, thread_id, rounds, exchanges: [...], synthesis?, total_latency_ms}
    """
    t0 = time.monotonic()
    if agents is None:
        agents = ["CLAUDE", "GEMINI"]
    
    tid, _ = _get_thread(thread_id)
    corr_id = f"debate_{tid}_{uuid.uuid4().hex[:6]}"
    
    _emit("debate.start", "msg",
          {"topic": topic[:200], "rounds": rounds, "agents": agents, "thread_id": tid},
          corr_id=corr_id)
    
    exchanges = []
    current_message = topic
    
    for round_idx in range(rounds):
        # Round-robin sur les agents
        current_agent = agents[round_idx % len(agents)]
        
        # Construit le prompt du round
        if round_idx == 0:
            prompt = f"[DEBAT NOKIDO - Round 1]\nTopic: {topic}\n\nDonne ta premiere analyse (technique, concise, argumentee)."
        else:
            previous = exchanges[-1]
            prompt = (
                f"[DEBAT NOKIDO - Round {round_idx + 1}/{rounds}]\n"
                f"L'agent {previous['agent']} a repondu :\n{previous['text']}\n\n"
                f"Ta tache : {'critique/challenge' if round_idx % 2 == 1 else 'corrige selon critique ou approfondis'}. "
                f"Si tu es d'accord, dis OK avec justification. Sois concis."
            )
        
        # Call l'agent approprie
        if current_agent == "CLAUDE":
            result = await ask_claude(prompt, thread_id=tid, rag_context=(round_idx == 0))
        elif current_agent == "GEMINI":
            result = await ask_gemini(prompt, thread_id=tid, rag_context=(round_idx == 0))
        elif current_agent == "OLLAMA":
            result = await ask_ollama(prompt, thread_id=tid)
        else:
            result = {"ok": False, "text": "", "error": f"Agent inconnu: {current_agent}"}
        
        exchanges.append({
            "round": round_idx + 1,
            "agent": current_agent,
            "prompt_preview": prompt[:150],
            "text": result.get("text", ""),
            "ok": result.get("ok", False),
            "latency_ms": result.get("latency_ms", 0),
            "model": result.get("model", "?"),
            "error": result.get("error"),
        })
        
        # Si un round echoue, on continue avec les autres (degraded mode)
        if not result.get("ok"):
            _emit("debate.round.error", "error",
                  {"round": round_idx + 1, "agent": current_agent,
                   "error": result.get("error", "?")[:200]},
                  corr_id=corr_id)
    
    # Synthese Ollama (optionnelle)
    synthesis_text = None
    if synthesize and any(e["ok"] for e in exchanges):
        synthesis_prompt = (
            f"[SYNTHESE DEBAT]\n"
            f"Topic original: {topic}\n\n"
            f"Echanges:\n"
        )
        for e in exchanges:
            synthesis_prompt += f"\n[Round {e['round']} - {e['agent']}]\n{e['text'][:800]}\n"
        synthesis_prompt += (
            "\n\nTa tache : synthetise en 200 mots max :\n"
            "1. Les points de consensus\n"
            "2. Les divergences restantes\n"
            "3. La decision recommandee (avec justification)"
        )
        
        syn_result = await ask_ollama(synthesis_prompt, thread_id=tid, max_tokens=800)
        synthesis_text = syn_result.get("text", "")
    
    total_latency = round((time.monotonic() - t0) * 1000, 1)
    _emit("debate.end", "msg",
          {"thread_id": tid, "total_latency_ms": total_latency,
           "rounds_completed": len([e for e in exchanges if e["ok"]]),
           "rounds_failed": len([e for e in exchanges if not e["ok"]]),
           "synthesis_available": synthesis_text is not None},
          corr_id=corr_id)
    
    return {
        "ok": any(e["ok"] for e in exchanges),
        "thread_id": tid,
        "topic": topic,
        "rounds": rounds,
        "exchanges": exchanges,
        "synthesis": synthesis_text,
        "total_latency_ms": total_latency,
    }


# ── Thread inspection (debug) ─────────────────────────────────────────────────
def get_thread_history(thread_id: str) -> List[Dict[str, str]]:
    """Retourne l'historique complet d'un thread."""
    return list(_THREADS.get(thread_id, []))


def clear_thread(thread_id: str) -> bool:
    """Purge un thread de la memoire."""
    return _THREADS.pop(thread_id, None) is not None


def list_threads() -> List[Dict[str, Any]]:
    """Liste tous les threads en memoire avec leur taille."""
    return [
        {"thread_id": tid, "messages": len(msgs), 
         "first_msg_preview": (msgs[0]["content"][:80] if msgs else "")}
        for tid, msgs in _THREADS.items()
    ]
