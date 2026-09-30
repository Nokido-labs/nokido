# -*- coding: utf-8 -*-
"""
app/collab_modes/dispatch.py — Point d'entrée unique @collab
============================================================
Orchestre l'appel aux différents modes de collaboration.
Supporte auto, ping, chef, debat, cline, gemini et history.
"""
from __future__ import annotations
import logging
from typing import Dict, Any

from .mode_auto import run_mode_auto
from .mode_ping import run_mode_ping, run_mode_ping_v2
from .mode_chef import run_mode_chef
from .mode_debat import run_mode_debat
from .mode_panel import run_mode_panel
from .mode_cline import run_mode_cline

logger = logging.getLogger("Nokido.Collab.Dispatch")


async def run_collab(
    chat: object,
    sub: str,
    task: str,
    opts: Dict[str, Any] = None,
) -> str:
    """
    Point d'entrée unique depuis @collab.
    """
    opts = opts or {}
    logger.info(f"[collab] dispatch sub={sub!r} task='{task[:50]}' opts={opts}")

    if sub == "auto":
        result = await run_mode_auto(chat, task, executor=opts.get("executor", "ollama:any"))
        chat.write(f"\n[bold]🤖 La Forge (auto) :[/] {result}")
        return result

    elif sub in ("ping", "collaboration"):
        return await run_mode_ping(chat, task, turns=int(opts.get("turns", 3)))

    elif sub in ("chef", "executant"):
        inverse = opts.get("inverse", False)
        return await run_mode_chef(chat, task, nokido_is_chef=not inverse)

    elif sub in ("debat", "these", "these_antithese"):
        return await run_mode_debat(chat, task, rounds=int(opts.get("rounds", 2)))

    elif sub in ("panel", "mas", "multi"):
        return await run_mode_panel(chat, task, opts)

    elif sub in ("cline", "plan_act"):
        return await run_mode_cline(chat, task, opts)

    elif sub in ("gemini", "gemini_ping"):
        from nokido_agent.app.forge_gemini_bridge import run_mode_gemini_ping, get_gemini_bridge

        bridge = get_gemini_bridge()
        if not bridge.api_key:
            chat.write("[yellow]⚠️ GEMINI_API_KEY manquant[/]")
            return ""
        mode = opts.get("mode", "ANALYZE").upper()
        turns = int(opts.get("turns", 3))
        await run_mode_gemini_ping(chat, task, turns=turns, mode=mode, session_id=opts.get("session", ""))
        return ""

    elif sub == "history":
        try:
            from nokido_agent.app.forge_task_bus import list_sessions, get_conversation

            session_filter = opts.get("session", "")
            if session_filter:
                msgs = get_conversation(session_filter, limit=100)
                if not msgs:
                    return ""
                chat.write(f"[bold #58a6ff]Conversation {session_filter} :[/]")
                for m in msgs:
                    chat.write(f"[dim]{m['agent_id']:<12}[/] {m['content'][:120]}")
            else:
                sessions = list_sessions(limit=20)
                for s in sessions:
                    chat.write(f"  [bold]{s['session_id'][:32]}[/] mode={s['mode']}")
        except Exception:
            pass
        return ""

    elif sub == "status":
        from nokido_agent.app.forge_task_bus import list_tasks, stats

        s = stats()
        chat.write(f"[bold]Bus de tâches — {s['total']} tâche(s)[/]")
        return ""

    else:
        chat.write("[bold #58a6ff]@collab[/] — modes: auto, ping, chef, debat, panel, cline, history, status")
        return ""
