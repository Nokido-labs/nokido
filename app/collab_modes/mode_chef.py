# -*- coding: utf-8 -*-
"""
app/collab_modes/mode_chef.py — Mode CHEF (Hiérarchie & Chaos Check)
====================================================================
Le chef planifie, l'autre exécute step by step.
Vérification de l'état système (RAM, CPU, AST) entre chaque étape.
"""
from __future__ import annotations
import asyncio
import logging
import re
import time
import json
from typing import List, Dict

from ._core import _header, _log_mode
from ._participants import _smart_ask, _nokido_ask, _forge_synthesize
from app.core.settings import get_app_attr as _g

logger = logging.getLogger("Nokido.Collab.Chef")


async def run_mode_chef(chat: object, task: str, nokido_is_chef: bool = True) -> str:
    """Hierarchie + Chaos Engineering."""
    from nokido_agent.app.forge_task_bus import create_task, inject_rag_context

    rag_engine = _g("rag_engine")
    rag_ctx = ""
    if rag_engine:
        _raw_docs = await rag_engine.search(task, k=8)
        try:
            from nokido_agent.app.forge_cognitive_router import prune_rag_context

            _intent = "code" if ".py" in task or "def " in task or "class " in task else "general"
            docs = prune_rag_context(_raw_docs, intent=_intent, k=3)
        except Exception:
            docs = _raw_docs[:3]
        rag_ctx = "\n".join(d.get("content", "")[:300] for d in docs)

    chef_name = "La Forge" if nokido_is_chef else "Ollama"
    exec_name = "Ollama" if nokido_is_chef else "La Forge"
    chef_color = "#58a6ff" if nokido_is_chef else "#d2a8ff"
    exec_color = "#d2a8ff" if nokido_is_chef else "#58a6ff"

    t = create_task(title=task[:60], description=task, task_type="devops", executor="ollama:any")
    if rag_ctx:
        inject_rag_context(t["id"], rag_ctx)

    _log_mode("chef:runtime", task, chef=chef_name)
    _header(chat, f"Chef/Runtime — {task[:43]}", f"Chef : {chef_name}  Exec : {exec_name}  chaos=ON")

    def _snap() -> dict:
        try:
            from nokido_agent.app.forge_health import get_vitals

            v = get_vitals()
            return {
                "rss_mb": round(v.get("system", {}).get("rss_mb", 0) or 0, 1),
                "cpu_pct": round(v.get("system", {}).get("cpu_pct", 0) or 0, 1),
            }
        except Exception:
            return {"rss_mb": 0, "cpu_pct": 0}

    snap_init = _snap()
    chat.write(f"[dim]Baseline : RAM={snap_init['rss_mb']}MB  CPU={snap_init['cpu_pct']}%[/]")

    plan_prompt = (
        f"Decompose en 3-5 etapes JSON : {task}\nFormat : " + '[{"step":1,"action":"...","why":"...","expected":"..."}]'
    )
    plan_raw = await _smart_ask(
        plan_prompt,
        context=rag_ctx,
        role="chef" if nokido_is_chef else "agent",
        collab_mode="collaboration",
        max_tokens=400,
    )

    try:
        m = re.search(r"\[.*\]", plan_raw, re.DOTALL)
        steps = json.loads(m.group(0)) if m else []
    except Exception:
        steps = [{"step": 1, "action": task, "why": "tache complete", "expected": "resultat"}]

    chat.write(f"\n[bold {chef_color}]Plan ({len(steps)} etapes) :[/]")
    for s in steps:
        chat.write(f"  [dim]{s.get('step', '?')}.[/] {s.get('action', '')[:70]}")

    exchanges, all_ok = [], True
    for s in steps:
        step_num = s.get("step", "?")
        action = s.get("action", "")
        chat.write(f"\n[bold {exec_color}]Etape {step_num} : {action[:60]}[/]")

        snap_before = _snap()
        t0 = time.monotonic()
        exec_resp = await _smart_ask(
            f"Execute : {action}\nContexte : {task}",
            context=rag_ctx,
            role="agent" if nokido_is_chef else "chef",
            collab_mode="collaboration",
            max_tokens=450,
        )
        elapsed = time.monotonic() - t0
        snap_after = _snap()

        delta_ram = round(snap_after["rss_mb"] - snap_before["rss_mb"], 1)
        delta_cpu = round(snap_after["cpu_pct"] - snap_before["cpu_pct"], 1)
        chat.write(f"[{exec_color}]{exec_resp or '[pas de reponse]'}[/]")

        chaos_flags = []
        if delta_ram > 50:
            chaos_flags.append(f"RAM +{delta_ram}MB")
        if delta_cpu > 80:
            chaos_flags.append(f"CPU +{delta_cpu}%")

        if chaos_flags:
            chat.write(f"[bold red]CHAOS FAIL : {' | '.join(chaos_flags)}[/]")
            all_ok = False
            if nokido_is_chef:
                decide = await _nokido_ask(f"Continuer malgre {chaos_flags} ? OUI/NON", max_tokens=20)
                if "non" in decide.lower():
                    break
        else:
            chat.write(f"[dim]Chaos OK  RAM d{delta_ram:+}MB  CPU d{delta_cpu:+}%  {elapsed:.1f}s[/]")

        exchanges.append(
            {
                "turn": step_num,
                "agent": exec_name.lower(),
                "content": exec_resp or "",
                "chaos_ok": not bool(chaos_flags),
            }
        )

    return await _forge_synthesize(chat, t["id"], task, exchanges, "chef:runtime")
