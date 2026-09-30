# -*- coding: utf-8 -*-
"""
app/collab_modes/mode_cline.py — Mode CLINE (Double-Blind Validation)
=====================================================================
Validation Double-Blind PLAN / ACT.
PLAN voit tout (RAG complet). ACT ne voit que les instructions (Blind).
La Forge valide le résultat final par comparaison.
"""
from __future__ import annotations
import asyncio
import logging
import json
import re
import uuid
from typing import List, Dict, Any

from ._core import _header, _log_mode
from ._participants import _nokido_ask, _ollama_ask, _forge_synthesize, _wait_for_agent
from app.core.settings import get_app_attr as _g

logger = logging.getLogger("Nokido.Collab.Cline")


async def run_mode_cline(chat: object, task: str, opts: Dict[str, Any] = None) -> str:
    """Double-Blind Validation PLAN/ACT."""
    from nokido_agent.app.forge_task_bus import ACTEUR_FORGE, create_task, forge_review, inject_rag_context

    opts = opts or {}
    timeout = int(opts.get("timeout", 120))
    dry_run = bool(opts.get("dry_run", False))
    session_id = f"blind-{uuid.uuid4().hex[:8]}"

    _log_mode("cline:blind", task, session=session_id, dry_run=dry_run)
    _header(chat, "Double-Blind PLAN/ACT", f"session={session_id}  timeout={timeout}s")

    rag_engine = _g("rag_engine")
    rag_ctx_plan = ""
    if rag_engine:
        docs = await rag_engine.search(task, k=5)
        rag_ctx_plan = "\n".join(d.get("content", "")[:400] for d in docs)

    # Phase PLAN
    chat.write("\n[bold #58a6ff]Phase PLAN (contexte complet) :[/]")
    t_plan = create_task(
        title=f"[PLAN] {task[:55]}",
        description=(
            f"CONTEXTE RAG :\n{rag_ctx_plan[:800]}\n\nTACHE : {task}\n\n"
            f"Produis un plan JSON :\n"
            f'[{"step":1,"action":"...","success_criteria":"...","blind_instruction":"..."}]'
        ),
        executor="CLINE_PLAN",
        task_type="planning",
        priority=9,
    )
    inject_rag_context(t_plan["id"], rag_ctx_plan)

    plan_result = await _wait_for_agent(t_plan["id"], timeout, chat, "CLINE_PLAN")
    if not plan_result:
        chat.write("[yellow]CLINE_PLAN absent -> Nokido genere le plan[/]")
        plan_result = await _nokido_ask(f"Plan JSON : {task}", context=rag_ctx_plan, max_tokens=400)

    try:
        m = re.search(r"\[.*\]", plan_result, re.DOTALL)
        steps = json.loads(m.group(0)) if m else []
    except Exception:
        steps = [{"step": 1, "action": task, "success_criteria": "tache realisee", "blind_instruction": task}]

    # La Forge juge le plan produit par CLINE_PLAN : acteur explicite (AUTH-6).
    forge_review(t_plan["id"], "approved", f"{len(steps)} etapes", acteur=ACTEUR_FORGE)
    for s in steps:
        chat.write(f"  [dim]{s.get('step', '?')}.[/] {s.get('action', '')[:60]}")

    if dry_run:
        return plan_result

    # Phase ACT
    chat.write("\n[bold #d2a8ff]Phase ACT (blind - sans RAG) :[/]")
    blind_instrs = [s.get("blind_instruction", s.get("action", "")) for s in steps]
    act_desc = "TACHE ACT (sans RAG) :\n" + "\n".join(f"{i + 1}. {instr}" for i, instr in enumerate(blind_instrs))

    t_act = create_task(
        title=f"[ACT] {task[:55]}", description=act_desc, executor="CLINE_ACT", task_type="execution", priority=9
    )
    act_result = await _wait_for_agent(t_act["id"], timeout, chat, "CLINE_ACT")

    if not act_result:
        chat.write("[yellow]CLINE_ACT absent -> Ollama simule (blind)[/]")
        act_result = await _ollama_ask(act_desc, context="", max_tokens=500)

    forge_review(t_act["id"], "approved", "resultats recus", acteur=ACTEUR_FORGE)
    chat.write(f"[{'#d2a8ff'}]{(act_result or '')[:400]}[/]")

    # Validation
    chat.write("\n[bold #3fb950]Validation croisee PLAN vs ACT :[/]")
    cross = await _nokido_ask(
        f"Compare plan vs resultats :\nCRITERES : {json.dumps(steps, ensure_ascii=False)}\nRESULTATS : {act_result[:600]}",
        max_tokens=350,
    )
    chat.write(f"[#3fb950]{cross}[/]")

    exchanges = [
        {"turn": 1, "agent": "cline_plan", "content": plan_result or ""},
        {"turn": 2, "agent": "cline_act", "content": act_result or ""},
        {"turn": 3, "agent": "laforge-xcheck", "content": cross},
    ]
    return await _forge_synthesize(chat, t_plan["id"], task, exchanges, "cline:blind")
