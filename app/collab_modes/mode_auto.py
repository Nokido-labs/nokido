# -*- coding: utf-8 -*-
"""
app/collab_modes/mode_auto.py — Mode AUTO (Orchestration silencieuse)
=====================================================================
La Forge analyse la tâche, décide si elle la délègue à l'agent externe,
valide le résultat. Pas d'affichage intermédiaire.
"""
from __future__ import annotations
import logging
from ._participants import _nokido_ask, _ollama_ask
from app.core.settings import get_app_attr as _g

logger = logging.getLogger("Nokido.Collab.Auto")


async def run_mode_auto(
    chat: object,
    task: str,
    executor: str = "ollama:qwen2.5",
) -> str:
    """
    La Forge analyse la tâche, décide si elle la délègue à l'agent externe,
    valide le résultat.
    """
    from nokido_agent.app.forge_task_bus import (ACTEUR_FORGE, create_task, forge_review,
                                                 inject_rag_context, submit_result)

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

    t = create_task(title=task[:60], description=task, executor=executor, task_type="generic", priority=5)
    if rag_ctx:
        inject_rag_context(t["id"], rag_ctx)

    # Exécution par l'agent externe
    ext_resp = await _ollama_ask(task, context=rag_ctx)

    # La Forge valide ou corrige
    if ext_resp:
        verdict_prompt = (
            f"L'agent externe a répondu à : {task}\n\nRéponse : {ext_resp}\n\n"
            "Valide, corrige ou complète cette réponse en 3 lignes max."
        )
        forge_resp = await _nokido_ask(verdict_prompt, max_tokens=300)
        submit_result(t["id"], [{"step": 1, "output": ext_resp, "ok": True}])
        # La Forge juge le travail d'un agent EXTERNE : acteur explicite (AUTH-6).
        forge_review(t["id"], "approved", forge_resp, acteur=ACTEUR_FORGE)
        return forge_resp or ext_resp
    else:
        # Pas de réponse externe → La Forge répond seule
        resp = await _nokido_ask(task, context=rag_ctx)
        submit_result(t["id"], [{"step": 1, "output": resp, "ok": True}])
        # PAS de revue : c'est la Forge qui a produit cette reponse, elle ne la juge pas
        # elle-meme (AUTH-6, SELF_REVIEW=0). Le resultat reste « review », non valide.
        return resp
