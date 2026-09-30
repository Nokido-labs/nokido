# -*- coding: utf-8 -*-
"""
app.collab_modes._participants - Ask helpers (participants LLM) pour collab_modes.

7 fonctions pour router les calls vers les differents providers :
- _smart_ask : dispatcher role-based (ollama/nokido/gemini/claude)
- _nokido_ask : LLM local Nokido
- _ollama_ask : Ollama (local ou LiteLLM fallback) avec DLP
- _gemini_ask : Gemini API directe
- _claude_ask : Claude via bus synchro
- _forge_synthesize : synthese finale multi-tours
- _ask_participant : wrapper orchestration prompt + call + log

Voir docs/REFACTO_COLLAB_MODES_SPEC.md pour le refacto.
"""
from __future__ import annotations

import asyncio
import json
import time
import logging
from typing import Any, Dict, List

from app.core.settings import get_app_attr as _g

from ._core import _get_session_id, _log_end, _spl_log
from ._arbitration import _meta_eval, _snap_rag_state, _wait_for_agent

logger = logging.getLogger("Nokido.Collab.Participants")


async def _smart_ask(
    task: str,
    context: str = "",
    role: str = "agent",  # "chef" | "agent" | "ollama"
    collab_mode: str = "collaboration",
    max_tokens: int = 500,
    session_id: str = "",
) -> str:
    """
    Point d'entrée unifié pour les modes collab.
    Route via SmartRouter si disponible (Gemini ou Ollama selon provider_map),
    sinon fallback direct sur _ollama_ask / _nokido_ask.

    Injecte automatiquement :
      - system prompt identitaire Nokido
      - contexte RAG (si context fourni)
      - historique session via conv_log
    """
    # ── Pare-feu pre-flight ───────────────────────────────────────────────────
    _fw_mapping: dict = {}
    _fw_safe_task = task
    try:
        from nokido_agent.app.forge_semantic_firewall import get_firewall as _gfw

        _fw = _gfw()
        _is_cloud = collab_mode == "collaboration"
        _pf = _fw.pre_flight(
            task=task,
            context=context,
            ring=2,  # collab = ring 2 (code appli, pas Ring 0)
            session_id=session_id,
            provider="gemini" if _is_cloud else "local",
        )
        if not _pf.ok:
            logger.warning(f"[_smart_ask] pre_flight VETO: {_pf.reason}")
            _snap_rag_state(f"VETO pre_flight ({role}): {_pf.reason[:100]}")
            return f"[VETO_SECURITY] {_pf.reason}"
        _fw_safe_task = _pf.safe_task or task
        _fw_mapping = _pf.mapping
    except ImportError:
        pass  # firewall optionnel
    except Exception as _fwe:
        logger.debug(f"[_smart_ask] firewall pre skip: {_fwe}")

    # ── Essai SmartRouter — avec meta_eval + post-flight ─────────────────────
    try:
        from nokido_agent.app.forge_routing import get_router, HAS_ROUTING

        if HAS_ROUTING:
            router = get_router()
            if router is not None:
                result = await router.route(
                    user_input=_fw_safe_task,
                    mode=collab_mode,
                )
                if result and result.response and "[TERMINAL]" not in result.response:
                    resp = result.response
                    # ── Meta-eval drift ───────────────────────────────────
                    try:
                        _drift = _meta_eval(resp, task)
                        if _drift:
                            logger.warning(f"[_smart_ask] meta_eval drift: {_drift}")
                            _snap_rag_state(f"DRIFT détecté ({role}): {_drift[:120]}")
                    except Exception:
                        pass
                    # ── Post-flight firewall ──────────────────────────────
                    try:
                        _post = _fw.post_flight(resp, task=task, session_id=session_id)
                        if not _post.ok:
                            logger.warning(f"[_smart_ask] post_flight: {_post.tag} — {_post.reason}")
                            _snap_rag_state(f"POST_FLIGHT {_post.tag} ({role}): {_post.reason[:100]}")
                            if _post.tag in ("SSRF", "SOCIAL_ENG", "CANARY_LEAK"):
                                return f"[RÉPONSE_BLOQUÉE:{_post.tag}] Régénération locale..."
                            # Hallucination / format → meta_eval déjà loggué, on continue
                    except Exception:
                        pass
                    # ── Restore placeholders DLP ──────────────────────────
                    if _fw_mapping:
                        resp = _fw.restore(resp, _fw_mapping)
                    return resp
    except Exception as _re:
        import logging as _lg

        _lg.getLogger(__name__).debug(f"[_smart_ask] SmartRouter skip: {_re}")

    # Fallback direct — enrichit via RagCache si context vide
    if not context:
        try:
            from nokido_agent.app.forge_rag_cache import get_rag_cache as _grc
            from nokido_agent.app.forge_npu_embedder import get_npu_embedder as _gnpu
            import numpy as _np

            _npu = _gnpu()
            if _npu and _npu.available:
                _qvec = _npu.embed_one(task)
                if _qvec is not None:
                    _c = _grc()
                    _c.maybe_reload()  # sync si MCP a écrit dans la DB
                    _hits = _c.search(_np.array(_qvec, dtype=_np.float32), k=3, layer="auto")
                    if _hits:
                        context = "\n".join(
                            f"[{h.get('source', '')} {h.get('score', 0):.2f}] {h.get('text', '')[:300]}" for h in _hits
                        )
        except Exception:
            pass
    if role in ("chef", "laforge"):
        return await _nokido_ask(task, context=context, max_tokens=max_tokens)
    else:
        return await _ollama_ask(task, context=context, max_tokens=max_tokens, session_id=session_id)


async def _gemini_ask(task: str, context: str = "", mode: str = "STRICT", session_id: str = "") -> str:
    """
    Appel Gemini API via forge_gemini_bridge.
    Retourne '' si GEMINI_API_KEY absent ou erreur.
    """
    try:
        from nokido_agent.app.forge_gemini_bridge import gemini_ask

        return await gemini_ask(task, context=context, mode=mode, session_id=session_id)
    except ValueError as e:
        # Loopback block ou SSRF — on remonte l'erreur
        raise
    except Exception as e:
        import logging as _lg

        _lg.getLogger(__name__).warning(f"[collab] Gemini indisponible: {e}")
        return ""


async def _ollama_ask(
    task: str, context: str = "", system: str = "", max_tokens: int = 500, session_id: str = ""
) -> str:
    """
    Appel Ollama (ou LiteLLM en fallback).
    Ordre : forge_ollama_bridge (direct) → forge_litellm_bridge (LiteLLM).
    DLP : le contexte RAG est filtré avant envoi (ring=0 bloqué, redaction).
    Retourne '' si tous les backends sont indisponibles ou DLP bloque.
    """
    t0 = time.monotonic()
    # ── DLP : filtrer le contexte avant envoi cloud ────────────────────────
    safe_context = context
    if context:
        try:
            from nokido_agent.app.forge_conv_sanitizer import filter_rag_context_for_llm as _frc

            # context peut être une string brute (déjà assemblée) ou une liste de chunks
            if isinstance(context, list):
                _dlp = _frc(context, session_id=session_id)
                if not _dlp["ok"]:
                    logger.warning(f"[_ollama_ask] DLP bloqué : {_dlp['reason'][:80]}")
                    return ""
                safe_context = "\n".join(c["text"] for c in _dlp["chunks"])
            else:
                # String brute : redaction simple
                from nokido_agent.app.forge_conv_sanitizer import _redact

                safe_context = _redact(context)
        except Exception as _de:
            logger.debug(f"[_ollama_ask] DLP skip: {_de}")
    try:
        from nokido_agent.app.forge_litellm_bridge import ask as _ask

        resp = await _ask(task, context=safe_context, role="Agent Ollama", system_extra=system, max_tokens=max_tokens)
        dur = time.monotonic() - t0
        if resp:
            logger.debug(f"[ollama_ask] OK dur={dur:.1f}s chars={len(resp)}")
        else:
            logger.warning(f"[ollama_ask] tous backends vides dur={dur:.1f}s")
        return resp
    except Exception as e:
        logger.warning(f"[ollama_ask] erreur après {time.monotonic() - t0:.1f}s : {e}")
        return ""


async def _nokido_ask(task: str, context: str = "", system_extra: str = "", max_tokens: int = 500) -> str:
    """Appel Ollama local via le modèle Nokido (même instance)."""
    t0 = time.monotonic()
    try:
        from nokido_agent.app.forge_ollama import ollama_call
        from nokido_agent.app import forge_context as _fc_lf

        _settings_lf = _fc_lf.get_settings()
        model = (
            (getattr(_settings_lf, "ollama_model_default", None) or "qwen2.5-coder:latest")
            if _settings_lf
            else "qwen2.5-coder:latest"
        )
        rag_engine = _fc_lf.get_rag_engine()

        rag_ctx = context
        if rag_engine and not context:
            try:
                docs = await rag_engine.search(task, k=3)
                if isinstance(docs, list):
                    rag_ctx = "\n".join(
                        str(d.get("content", d.get("text", "")))[:200] for d in docs if isinstance(d, dict)
                    )
            except Exception as _rag_e:
                logger.warning(f"[_nokido_ask] RAG search skip: {_rag_e}")
                rag_ctx = ""

        # ── PromptGuard : blindage injection + conflit + identity anchor ────────
        # AB4 (2026-09-12) : `_canary` est initialise AVANT le try. Il etait
        # auparavant jete, mais surtout il n'existait pas du tout quand le garde
        # levait — et le geste aval ajoute plus bas aurait alors casse l'appel
        # sur un NameError, exactement la panne qu'un garde ne doit jamais causer.
        _canary = ""
        try:
            from nokido_agent.app.forge_prompt_guard import build_safe_system

            system, _canary, _warns = build_safe_system(
                role="La Forge, supercontrôleur IA DevOps",
                rag_ctx=rag_ctx,
                system_extra=system_extra,
            )
            if _warns:
                logger.warning(f"[nokido_ask] prompt_guard: {_warns}")
        except Exception as _pge:
            system = (
                "Tu es La Forge, supercontrôleur IA DevOps. Réponds en français, sois précis, technique, max 12 lignes."
            )
            if system_extra:
                system += f"\n\n{system_extra}"
            if rag_ctx:
                system += f"\n\nContexte RAG :\n{rag_ctx[:600]}"

        resp = await ollama_call(
            model=model,
            messages=[{"role": "user", "content": task}],
            system=system,
            max_tokens=max_tokens,
        )
        # AB4 — le canari pose dans le system prompt est enfin VERIFIE : sans ce
        # geste, la marque partait au modele et personne ne regardait si elle
        # revenait. `verifier_fuite` detecte, retire la marque de la reponse et
        # relache le registre ; il ne leve jamais.
        try:
            from nokido_agent.app.forge_prompt_guard import verifier_fuite

            resp, _fuite = verifier_fuite(resp, _canary, source="nokido_ask")
            if _fuite:
                logger.error("[nokido_ask] fuite de prompt detectee — marque retiree")
        except Exception as _vfe:  # noqa: BLE001  le garde ne casse jamais l'appel
            logger.error(f"[nokido_ask] verification de fuite ILLISIBLE: {_vfe}")
        logger.debug(f"[nokido_ask] OK dur={time.monotonic() - t0:.1f}s chars={len(resp)}")
        return resp
    except Exception as e:
        logger.warning(f"[nokido_ask] erreur après {time.monotonic() - t0:.1f}s : {e}")
        return f"[Erreur Nokido: {e}]"


async def _claude_ask(
    task_id_bus: str,
    task: str,
    context: str = "",
    timeout: int = 120,
) -> str:
    """
    Demande à Claude (instance CLAUDE via Nokido_Local MCP) de contribuer.
    Stratégie : crée une sous-tâche pour executor='CLAUDE',
    attend que Claude soumette son résultat via task_result,
    retourne le contenu ou '' si timeout.

    Claude participe en appelant depuis Cline / Claude Desktop :
      query(action='task_claim',  author='CLAUDE')
      query(action='task_result', q=<id>, text=<réponse>)
    """
    import time
    from nokido_agent.app.forge_task_bus import ACTEUR_FORGE, create_task, forge_review, get_task

    t = create_task(
        title=f"[CLAUDE] {task[:60]}",
        description=(
            f"Contribue à cette tâche collaborative.\n\n"
            f"{('Contexte RAG :\n' + context[:800] + chr(10) * 2) if context else ''}"
            f"Tâche : {task}\n\n"
            f"Réponds en 8 lignes max, sois concis et apporte ta perspective."
        ),
        executor="CLAUDE",
        task_type="research",
        priority=8,
        meta={"parent_task": task_id_bus, "agent": "CLAUDE"},
    )
    tid = t["id"]
    logger.info(f"[claude_ask] tâche créée id={tid}")

    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        row = get_task(tid)
        if row and row.get("status") in ("review", "done"):
            results = row.get("results", [])
            if isinstance(results, str):
                try:
                    results = __import__("json").loads(results)
                except Exception:
                    results = []
            if results:
                content = results[-1].get("content", "")
                # La Forge juge la contribution de CLAUDE : acteur explicite (AUTH-6).
                forge_review(tid, verdict="approved", notes="Contribution Claude validée",
                             acteur=ACTEUR_FORGE)
                logger.info(f"[claude_ask] réponse reçue {len(content)}chars")
                return content
        await asyncio.sleep(3)

    logger.warning(f"[claude_ask] timeout {timeout}s — pas de réponse CLAUDE")
    return ""


async def _forge_synthesize(chat: object, task_id: str, task: str, exchanges: List[Dict], mode: str) -> str:
    """La Forge produit la synthèse finale et l'archive dans le RAG."""
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    rag_engine = _ac.rag_engine
    from nokido_agent.app.forge_task_bus import submit_result, archive_to_rag

    history = "\n\n".join(f"[{e['agent']}] (tour {e['turn']}) :\n{e['content']}" for e in exchanges)
    synth_prompt = (
        f"Tu es le supercontrôleur. Synthétise cet échange [{mode}] "
        f"sur : {task}\n\n{history}\n\n"
        f"Produis une synthèse structurée avec :\n"
        f"- Points de consensus\n- Points de divergence\n"
        f"- Recommandation concrète finale\n- Max 15 lignes."
    )
    t0_synth = time.monotonic()
    synth = await _nokido_ask(
        synth_prompt,
        system_extra="Tu synthétises un débat multi-agents. Sois tranché et actionnable.",
        max_tokens=600,
    )
    logger.info(f"[collab:{mode}] synthèse produite dur={time.monotonic() - t0_synth:.1f}s chars={len(synth)}")

    chat.write("\n[bold #3fb950]📋 Synthèse La Forge :[/]")
    chat.write(f"[#3fb950]{synth}[/]")

    # Log dans shared_prompt_log (mode DEV) — tous les tours + synthèse
    _sid = _get_session_id()
    for e in exchanges:
        _spl_log(_sid, e["agent"], e["content"], role="assistant", mode=f"dev:collab:{mode}")
    _spl_log(_sid, "laforge", synth, role="assistant", mode=f"dev:collab:{mode}:synthese")

    # Archiver dans le bus et le RAG
    results = [{"turn": e["turn"], "agent": e["agent"], "content": e["content"], "ok": True} for e in exchanges]
    results.append({"turn": 99, "agent": "laforge-synthese", "content": synth, "ok": True})
    submit_result(task_id, results, status="review")
    # PAS d'auto-approbation (AUTH-6, SELF_REVIEW=0) : la synthese est produite PAR la
    # Forge, elle ne la juge pas. Consequence voulue : archive_to_rag n'archive que le
    # « done » et laisse donc cette synthese hors des « resultats valides » du RAG
    # tant qu'un juge distinct ne l'a pas revue.
    rag_engine = _g("rag_engine")
    if rag_engine:
        archived = archive_to_rag(task_id, rag_engine)
        logger.info(f"[collab:{mode}] archive RAG task={task_id} ok={archived}")

    _log_end(mode, task_id, "done", len(exchanges), len(synth))
    return synth


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
    """Appelle le bon agent selon le participant."""
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
    else:  # nokido / default
        return await _nokido_ask(enriched, context=context)
