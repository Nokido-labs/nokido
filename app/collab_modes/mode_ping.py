# -*- coding: utf-8 -*-
"""
app/collab_modes/mode_ping.py — Mode PING (Dialogue & Distillation)
===================================================================
Ping-pong : chaque LLM enrichit l'autre en alternance.
Contient aussi la distillation convergente (réduction entropique).
"""
from __future__ import annotations
import asyncio
import logging
import datetime
import uuid
from pathlib import Path
from dataclasses import dataclass, field as _dc_field
from typing import Optional, List, Dict

from ._core import _spl_log, _header, _turn_header, _log_mode, _log_end
from ._participants import _smart_ask, _nokido_ask, _ollama_ask, _gemini_ask, _claude_ask, _forge_synthesize
from app.core.settings import get_app_attr as _g

logger = logging.getLogger("Nokido.Collab.Ping")


@dataclass
class CollabSession:
    """Parametres d une session de collaboration orchestree par Nokido."""

    prompt: str
    mode: str = "ping"
    chef_model: str = "auto"
    participants: list = _dc_field(default_factory=lambda: ["ollama"])
    turns: int = 3
    delay_claude: float = 2.5
    delay_gemini: float = 1.0
    delay_ollama: float = 0.3
    session_id: str = ""


async def detect_best_model(role: str = "chef") -> str:
    """Detecte le meilleur modele Ollama disponible."""
    PREFERRED = {
        "chef": ["qwen2.5-coder:32b", "qwen2.5-coder:14b", "qwen2.5-coder:latest", "llama3.3:70b", "llama3.1:8b"],
        "coder": ["qwen2.5-coder:latest", "deepseek-coder:latest", "codellama:latest"],
        "analyst": ["llama3.1:8b", "qwen2.5:latest", "mistral:latest"],
    }
    preferred = PREFERRED.get(role, PREFERRED["chef"])
    try:
        import aiohttp

        async with aiohttp.ClientSession() as s:
            async with s.get("http://localhost:11434/api/tags", timeout=aiohttp.ClientTimeout(total=3)) as r:
                data = await r.json()
                available = {m["name"] for m in data.get("models", [])}
                for p in preferred:
                    if p in available:
                        return p
                if available:
                    return sorted(available)[0]
    except Exception:
        pass
    return ""


PARTICIPANT_DELAYS = {"claude": 2.5, "gemini": 1.0, "ollama": 0.3, "laforge": 0.3}
PARTICIPANT_LABELS = {
    "claude": ("#f0e68c", "Claude"),
    "gemini": ("#d2a8ff", "Gemini"),
    "ollama": ("#79c0ff", "Ollama"),
    "laforge": ("#58a6ff", "Nokido"),
}


async def _ask_participant(
    participant: str,
    task: str,
    context: str,
    turn: int,
    total_turns: int,
    prev_response: str,
    session_id: str,
    task_id_bus: str,
) -> str:
    enriched = task
    if prev_response:
        enriched = (
            f"Tour {turn}/{total_turns} — Sujet : {task}\n\n"
            f"Reponse precedente :\n{prev_response}\n\n"
            f"Enrichis, critique ou complete en apportant ta perspective unique."
        )
    if participant == "gemini":
        return await _gemini_ask(enriched, context=context, session_id=session_id)
    elif participant == "claude":
        return await _claude_ask(task_id_bus, enriched, context=context, timeout=90)
    elif participant == "ollama":
        return await _ollama_ask(enriched, context=context, session_id=session_id)
    else:
        return await _nokido_ask(enriched, context=context)


async def run_mode_ping_v2(chat: object, task: str, session: CollabSession | None = None) -> str:
    """Ping orchestre par Nokido."""
    from nokido_agent.app.forge_task_bus import create_task

    if session is None:
        session = CollabSession(prompt=task)
    sid = session.session_id or f"collab_{uuid.uuid4().hex[:8]}"
    session.session_id = sid

    chef_model = session.chef_model
    if chef_model == "auto":
        chef_model = await detect_best_model("chef") or "qwen2.5-coder:latest"
    chat.write(f"[bold #58a6ff]🤖 Chef:[/] [cyan]{chef_model}[/]")

    parts_str = " · ".join(
        f"[{PARTICIPANT_LABELS.get(p, ('#fff', '?'))[0]}]{PARTICIPANT_LABELS.get(p, ('#fff', p))[1]}[/]"
        for p in session.participants
    )
    chat.write(
        f"[bold]👥 Participants:[/] {parts_str}\n[bold]💬 Sujet:[/] [dim]{task[:80]}[/]\n[dim]📋 Session: {sid}[/]\n"
        + "─" * 50
    )

    _spl_log(
        sid,
        "laforge",
        f"[COLLAB START] mode=ping participants={session.participants} prompt={task[:200]}",
        role="system",
        mode="collab:ping",
    )

    rag_ctx = ""
    try:
        from nokido_agent.app.forge_app_context import get_rag

        re_eng = get_rag()
        if re_eng:
            docs = await re_eng.search(task, k=3)
            rag_ctx = "\n".join(d.get("text", d.get("content", ""))[:300] for d in docs)
    except Exception:
        pass

    t = create_task(title=task[:60], description=task, task_type="research", executor="laforge")
    task_id = t["id"]
    exchanges, prev_response = [], ""

    for turn in range(1, session.turns + 1):
        chat.write(f"\n[bold]Tour {turn}/{session.turns}[/]")
        for participant in session.participants:
            color, label = PARTICIPANT_LABELS.get(participant, ("#fff", participant))
            delay = PARTICIPANT_DELAYS.get(participant, 1.0)
            chat.write(f"[{color}]● {label} reflechit...[/]")
            try:
                resp = await _ask_participant(
                    participant, task, rag_ctx, turn, session.turns, prev_response, sid, task_id
                )
                resp = resp or f"[{label}] Pas de reponse."
            except Exception as e:
                resp = f"[{label}] Erreur: {e}"
            chat.write(f"[{color}][bold]{label}:[/][/] {resp[:600]}")
            _spl_log(sid, participant, resp, role="assistant", mode=f"collab:ping:t{turn}")
            exchanges.append(
                {
                    "turn": turn,
                    "agent": participant,
                    "label": label,
                    "content": resp,
                    "timestamp": datetime.datetime.now().isoformat(),
                }
            )
            prev_response = resp
            await asyncio.sleep(delay)

    return await _forge_synthesize(chat, task_id, task, exchanges, "ping")


async def run_mode_ping(chat: object, task: str, turns: int = 3) -> str:
    """Distillation convergente (réduction entropique)."""
    rag_engine = _g("rag_engine")
    rag_ctx = ""
    if rag_engine:
        _raw_docs = await rag_engine.search(task, k=8)
        try:
            from nokido_agent.app.forge_cognitive_router import prune_rag_context

            _intent = "code" if ".py" in task or "def " in task or "class " in task else "general"
            docs = prune_rag_context(_raw_docs, intent=_intent, k=3)
            rag_ctx = "\n".join(d.get("content", "")[:300] for d in docs)
        except Exception:
            pass

    from nokido_agent.app.forge_task_bus import create_task, inject_rag_context

    t = create_task(title=task[:60], description=task, task_type="research", executor="ollama:any")
    if rag_ctx:
        inject_rag_context(t["id"], rag_ctx)

    _log_mode("ping:distill", task, turns=turns)
    _header(chat, f"Distillation — {task[:43]}", f"{turns} tours convergents")

    TOKEN_BUDGET = {1: 500, 2: 200, 3: 50}
    INSTRUCTIONS = {1: "Explore.", 2: "Garde l'essentiel.", 3: "Une phrase. La verite."}
    exchanges, prev_ol = [], ""

    for turn in range(1, turns + 1):
        budget = TOKEN_BUDGET.get(turn, 50)
        _turn_header(chat, turn, turns, f"La Forge [t{turn}]", "#58a6ff", "o")
        lf_resp = await _smart_ask(
            f"DISTILLATION {turn}/{turns}. {task}\n{f'Ollama : {prev_ol}' if prev_ol else ''}\nREGLE : {INSTRUCTIONS[turn]}",
            context=rag_ctx,
            role="chef",
            collab_mode="collaboration",
            max_tokens=budget,
        )
        chat.write(f"[#58a6ff]{lf_resp}[/]")
        exchanges.append({"turn": turn, "agent": "laforge", "content": lf_resp, "chars": len(lf_resp)})

        _turn_header(chat, turn, turns, f"Agent [t{turn}]", "#d2a8ff", "o")
        ol_resp = await _smart_ask(
            f"DISTILLATION {turn}/{turns}. {task}\nNokido : {lf_resp}\nREGLE : {INSTRUCTIONS[turn]}",
            context=rag_ctx,
            role="agent",
            collab_mode="collaboration",
            max_tokens=budget,
        )
        chat.write(f"[#d2a8ff]{ol_resp or lf_resp}[/]")
        exchanges.append(
            {"turn": turn, "agent": "ollama", "content": ol_resp or lf_resp, "chars": len(ol_resp or lf_resp)}
        )
        prev_ol = ol_resp or lf_resp

    return await _forge_synthesize(chat, t["id"], task, exchanges, "ping:distill")
