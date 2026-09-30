# -*- coding: utf-8 -*-
"""
app/collab_modes/mode_debat.py — Mode DEBAT (Consensus Ledger)
==============================================================
Thèse / Antithèse / Réfutation / Synthèse.
Utilise un score de risque pour prononcer un VETO ou une VALIDATION.
"""
from __future__ import annotations
import asyncio
import logging
import json
import re
from typing import List, Dict

from ._core import _header, _log_mode, _get_session_id
from ._participants import _smart_ask, _nokido_ask, _ollama_ask, _forge_synthesize
from app.core.settings import get_app_attr as _g

logger = logging.getLogger("Nokido.Collab.Debat")


async def run_mode_debat(chat: object, task: str, rounds: int = 2) -> str:
    """Debat dialectique avec Consensus Ledger."""
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

    t = create_task(title=task[:60], description=task, task_type="research", executor="ollama:any")
    if rag_ctx:
        inject_rag_context(t["id"], rag_ctx)

    _log_mode("debat:ledger", task, rounds=rounds)
    _header(chat, f"Consensus Ledger — {task[:40]}", "These: Nokido  SBP: Ollama  Ledger: Veto|Validation")

    exchanges, sbp_total, red_alerts, risk_score = [], [], [], 0

    # These
    chat.write("\n[bold #58a6ff]These (La Forge) :[/]")
    these = await _nokido_ask(f"Defends cette idee (max 10 lignes) : {task}", context=rag_ctx, max_tokens=450)
    chat.write(f"[#58a6ff]{these}[/]")
    exchanges.append({"turn": 1, "agent": "laforge-these", "content": these})

    # Antithese + SBP
    chat.write("\n[bold #d2a8ff]Antithese + Security Breaking Points (Ollama) :[/]")
    sbp_prompt = (
        f"Refute cette these :\n{these}\n\nSujet : {task}\n\nFORMAT JSON : "
        + '{"antithese":"...","sbp":["..."],"red_alert":true|false,"risk_score":0-100}'
    )
    sbp_raw = await _smart_ask(sbp_prompt, context=rag_ctx, role="agent", collab_mode="collaboration", max_tokens=500)

    try:
        m = re.search(r"\{.*\}", sbp_raw, re.DOTALL)
        sbp_data = json.loads(m.group(0)) if m else {}
    except Exception:
        sbp_data = {}

    antithese = sbp_data.get("antithese", sbp_raw)
    sbp_list = sbp_data.get("sbp", [])
    is_red = bool(sbp_data.get("red_alert", False))
    risk_score = int(sbp_data.get("risk_score", 30))

    chat.write(f"[#d2a8ff]{antithese}[/]")
    sbp_total.extend(sbp_list)
    if sbp_list:
        chat.write("\n[bold yellow]Security Breaking Points :[/]")
        for sbp in sbp_list:
            chat.write(f"  [yellow]* {sbp}[/]")

    if is_red:
        red_alerts.append(antithese[:200])
        risk_score = max(risk_score, 70)
        chat.write(f"[bold red]RED_ALERT ! Score : {risk_score}/100[/]")
    else:
        chat.write(f"[dim]Risk score : {risk_score}/100[/]")

    exchanges.append(
        {
            "turn": 1,
            "agent": "ollama-antithese",
            "content": antithese,
            "sbp": sbp_list,
            "red_alert": is_red,
            "risk_score": risk_score,
        }
    )

    # Round 2
    if rounds >= 2:
        chat.write("\n[bold #58a6ff]Refutation (La Forge) :[/]")
        refutation = await _nokido_ask(
            f"Reponds aux SBP : {json.dumps(sbp_list, ensure_ascii=False)}\nREFUTE / CONCEDE / MITIGE. Sujet : {task}",
            context=rag_ctx,
            max_tokens=400,
        )
        chat.write(f"[#58a6ff]{refutation}[/]")
        exchanges.append({"turn": 2, "agent": "laforge-refutation", "content": refutation})

        chat.write("\n[bold #d2a8ff]Concession (Ollama) :[/]")
        concession = await _ollama_ask(
            f'Nokido a refute tes points :\n{refutation}\nRecalcule : {{"concession":"...","risk_score_final":0-100}}',
            context=rag_ctx,
            max_tokens=300,
        )
        try:
            m2 = re.search(r"\{.*\}", concession, re.DOTALL)
            conc_data = json.loads(m2.group(0)) if m2 else {}
            risk_score = int(conc_data.get("risk_score_final", risk_score))
            concession_txt = conc_data.get("concession", concession)
        except Exception:
            concession_txt = concession
        chat.write(f"[#d2a8ff]{concession_txt}[/]\n[dim]Risk score ajuste : {risk_score}/100[/]")
        exchanges.append(
            {"turn": 2, "agent": "ollama-concession", "content": concession_txt, "risk_score_final": risk_score}
        )

    # Verdict
    chat.write("\n[bold #3fb950]Consensus Ledger (La Forge) :[/]")
    verdict_prompt = (
        f"Synthese du debat sur : {task}\nSBP : {json.dumps(sbp_total[:5], ensure_ascii=False)}\nRED_ALERTS : {len(red_alerts)} Risk : {risk_score}/100\n"
        + '{"verdict":"VETO"|"VALIDATION","justification":"..."}'
    )
    verdict_raw = await _nokido_ask(verdict_prompt, system_extra="Tu es le juge final.", max_tokens=450)
    try:
        m3 = re.search(r"\{.*\}", verdict_raw, re.DOTALL)
        verdict_data = json.loads(m3.group(0)) if m3 else {}
    except Exception:
        verdict_data = {}

    final_verdict = verdict_data.get("verdict", "VETO" if (risk_score > 60 or red_alerts) else "VALIDATION")
    justification = verdict_data.get("justification", verdict_raw)

    color = "red" if final_verdict == "VETO" else "green"
    chat.write(f"[bold {color}]{final_verdict} — Risk : {risk_score}/100[/]\n[{color}]{justification}[/]")

    if final_verdict == "VETO":
        try:
            from nokido_agent.app.forge_conv_sanitizer import set_paranoid_mode

            sid = _get_session_id()
            if sid and sid != "collab":
                set_paranoid_mode(sid, True)
        except Exception:
            pass

    exchanges.append(
        {
            "turn": 99,
            "agent": "laforge-ledger",
            "content": f"{final_verdict}: {justification}",
            "verdict": final_verdict,
            "risk_score": risk_score,
        }
    )
    return await _forge_synthesize(chat, t["id"], task, exchanges, "debat:ledger")
