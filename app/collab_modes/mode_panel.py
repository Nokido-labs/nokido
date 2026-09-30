# -*- coding: utf-8 -*-
"""Mode PANEL - text-MAS multi-LLM via agent_debate (opt-in)."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("Nokido.Collab.Panel")


async def run_mode_panel(chat: object, task: str, opts: Optional[Dict[str, Any]] = None) -> str:
    """Panel multi-LLM round-robin + synthese."""
    opts = opts or {}
    from nokido_agent.app.forge_agent_proxy import agent_debate

    rounds = int(opts.get("rounds", 3))
    agents = opts.get("agents") or ["groq", "ollama"]
    syn = opts.get("synthesis_provider", "groq")

    res = await agent_debate(topic=task, rounds=rounds, agents=agents, synthesize=True, synthesis_provider=syn)

    if not res.get("ok"):
        chat.write("panel echec : " + str(res.get("error", "?")))
        return ""

    for e in res.get("exchanges", []):
        chat.write("R%s - %s :" % (e.get("round"), e.get("display_name")))
        chat.write((e.get("text") or "")[:700])

    s = res.get("synthesis")
    if s:
        chat.write("Synthese :\n" + s)
    return s or ""
