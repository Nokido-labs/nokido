"""Route une saisie utilisateur de la TUI vers le chat rapide, le SmartRouter ou
l'orchestrateur, affiche la reponse et injecte dans le terminal PTY la commande shell.

Entree unique : dispatch_ai(app, user_input), coroutine appelee par Nokido.py.
Etapes : anti-rebond 3 s, garde app.ai_busy, filtre de resonance, NLU hybride
(forge_nlu), puis modes autonome, collaboration ou comite de l'orchestrateur.
Commande extraite de la reponse (blocs bash ou lignes en $) : DangerGuard, puis
confirmation (ConfirmScreen) ou app.terminal.inject ; le langage naturel est ecarte.
Effets : recherche web optionnelle (_web_search_fn), heartbeat CLAUDE, etat swarm,
contexte mmap, record_success des competences de l'AgenticEngine.
"""
from __future__ import annotations

# Import oublie, mesure le 2026-09-08 : uuid.uuid4() L765.
import uuid

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_060529_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: docstrings Args/Returns/Raises
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_dispatch_ai.py — Dispatch IA central (extrait de Nokido.py v16.5)
=========================================================================
Contient _dispatch_ai : routing intelligent user_input → agent IA.

Flux :
  user_input
    → debounce + ai_busy guard
    → NLU hybride (prédictif < 1ms + regex fallback)
    → fast-path CHAT ou SmartRouter
    → collab mode (collaboration/comite)
    → fallback orchestrateur
    → injection PTY si commande shell détectée

Appelé depuis Nokido.py via wrapper 3 lignes :
  async def _dispatch_ai(self, user_input):
      import forge_dispatch_ai as _fda
      await _fda.dispatch_ai(self, user_input)
"""

import asyncio
import re
import time
from rich.markup import escape


import logging as _logging

logger = _logging.getLogger("Nokido.DispatchAI")
from app.core.settings import get_app_attr as _g
from nokido_agent.app import forge_context  # noqa: F401
from app.forge_llm import SHELL_COMMANDS
from app.forge_rag_engine import _web_search_fn
from app.forge_ui_widgets import ConfirmScreen
from app.forge_ui_widgets import EntropyGauge

try:
    from nokido_agent.app.forge_core_models import AgentType
except Exception:
    from enum import Enum

    class AgentType(Enum):
        """Agenttype."""

        CHAT = "chat"
        ACTION = "action"
        RAG = "rag"


# ─────────────────────────────────────────────────────────────────────────────
# Aliases lisibles — résolus au runtime
# ─────────────────────────────────────────────────────────────────────────────
"""Logger."""
# Context:


# Context:


def _logger() -> object | None:
    """Return the logger if available, otherwise None."""
    return getattr(__import__("forge_logging"), "logger", None)


def _debug_log(*a, **k) -> None:
    """Debug log."""
    fn = getattr(__import__("forge_logging"), "debug_log", None)
    if fn:
        fn(*a, **k)


"""Agentic."""
"""Agentic."""
"""Agentic."""


def _agentic() -> object:
    """agentic."""
    return (
        __import__("forge_agentic").get_agentic_engine()
        if hasattr(__import__("forge_agentic"), "get_agentic_engine")
        else None
    )


"""Get orc."""
"""Get orc."""
"""Get orc."""


def _get_orc() -> object:
    """get orc."""
    return forge_context.get_orchestrator()() if forge_context.get_orchestrator() else None


"""Agent meta."""
"""Agent meta."""
"""Agent meta."""


def _agent_meta() -> object:
    """agent meta."""
    return _g("AGENT_META", {})


"""Agent type."""
"""Agent type."""
"""Agent type."""


def _agent_type() -> object:
    """agent type."""
    return _g("AgentType")


"""Danger level."""
"""Danger level."""
"""Danger level."""


def _danger_level() -> object:
    """danger level."""
    return _g("DangerLevel")


# ─────────────────────────────────────────────────────────────────────────────
# Fonction principale
# ─────────────────────────────────────────────────────────────────────────────


async def dispatch_ai(app, user_input: str):
    """
    Dispatch vers le singleton OrchestratorManager.
    - Debounce 3s : protège contre les doubles Enter
    - ai_busy guard : avertit l'utilisateur au lieu d'ignorer
    - Injection PTY automatique si commande extraite par NLU
    - Ne change JAMAIS l'agent UI (_set_agent)
    """
    # ── Résolution des globals Nokido au runtime ─────────────────────────
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    agentic_engine = _ac.agentic_engine
    rag_engine = _ac.rag_engine
    settings = _ac.settings
    version_manager = _ac.version_manager
    debug_log = _debug_log  # utilise la fonction module-level toujours callable
    agentic_engine = (
        __import__("forge_agentic").get_agentic_engine()
        if hasattr(__import__("forge_agentic"), "get_agentic_engine")
        else None
    )
    _orc_instance = forge_context.get_orchestrator()
    # AgentType deja importe en tete depuis forge_core_models — pas de reassignation
    AGENT_META = _g("AGENT_META", {})
    AGENT_BY_KEY = _g("AGENT_BY_KEY", {})
    HAS_PREDICTIF = _g("HAS_PREDICTIF", False)
    HAS_ROUTAGE = _g("HAS_ROUTAGE", False)
    rag_engine = forge_context.get_rag_engine()
    try:
        from nokido_agent.app.forge_nlu import load_router as _lr_init

        intent_classifier = _lr_init()
    except Exception:
        intent_classifier = None
    ollama_stream = __import__("forge_ollama").ollama_stream
    ollama_call = __import__("forge_ollama").ollama_call
    settings = forge_context.get_settings()
    version_manager = forge_context.get_version_manager()

    # ── Debounce ──────────────────────────────────────────────────────
    now = time.monotonic()
    if user_input == getattr(app, "_last_input", "") and now - getattr(app, "_last_input_ts", 0) < 3.0:
        return
    app._last_input = user_input
    app._last_input_ts = now

    # ── Guard ai_busy ─────────────────────────────────────────────────
    if app.ai_busy:
        app._chat_log().write("[yellow]⏳ IA en cours — attends ou tape [bold]@reset[/][/]")
        return

    _debug_log(hypothesis_id="H3", location="_dispatch_ai", message="Dispatch IA", data={"input": user_input[:80]})

    app.ai_busy = True

    class _Chat:
        """Write.

        Args:
            msg: Description.
        """

        """Write.

        Args:
            msg: Description.
        """
        """Write.

        Args:
            msg: Description.
        """

        def write(self, msg) -> None:
            """Write."""
            app._chat_log().write(msg)

    chat = _Chat()

    # ── Heartbeat collab — signale que CLAUDE est actif ──────────────────────
    try:
        from nokido_agent.app.forge_heartbeat import beat as _hb_beat

        _mode = getattr(app, "_collab_mode", "autonome")
        _hb_beat("CLAUDE", status="working", task=user_input[:60])
    except Exception:
        pass

    # ── Swarm state machine — THINKING ──────────────────────────────────
    try:
        from nokido_agent.app.forge_swarm import swarm as _swarm

        _swarm.sm.set_thinking("CLAUDE", user_input[:40])
    except Exception:
        pass

    # ── Filtre de Résonance — vérifie dérive + répétition ──────────────
    _resonance_result = {"action": "pass", "enriched_prompt": user_input, "correction": "", "drift_score": 0.0}
    try:
        from nokido_agent.app.forge_resonance_filter import resonance_check as _rc

        _resonance_result = _rc(
            agent_id="CLAUDE",
            proposal=user_input,
            context=getattr(app, "_collab_mode", "autonome"),
        )
        if _resonance_result["action"] == "block":
            chat.write("[yellow]🚫 Correction de Cap :[/] " + _resonance_result["correction"][:300])
            return
        elif _resonance_result["action"] in ("correct", "warn"):
            # Enrichir l'input avec le contexte ADR
            user_input = _resonance_result["enriched_prompt"]
    except Exception:
        pass

    # ── MMap Context — agent écrit sa pensée en cours ───────────────────
    _agent_ctx = None
    try:
        from nokido_agent.app.forge_mmap_context import AgentContext as _AC

        _agent_ctx = _AC("CLAUDE")
        _agent_ctx.start_thinking(user_input[:60])
    except Exception:
        pass

    try:
        app._set_status("[cyan]🤖 Traitement…[/]")
        app.role_panel.reset()  # éteindre tous les rôles

        # ── Annuler confirmation RAG en attente si autre commande ─
        if app._rag_pending_confirm and not user_input.strip().startswith("@rag"):
            app._rag_pending_confirm = {}

        debug_log(
            "ROUTE",
            "DevOpsApp._dispatch_ai",
            "Input reçu (pré-routage)",
            {"raw_input": user_input, "len": len(user_input), "agent_ui": app.current_agent.value},
        )

        # ── NLU hybride (predictif < 1ms + regex fallback) ────────
        if intent_classifier is None:
            try:
                from nokido_agent.app.forge_nlu import load_router as _lr

                intent_classifier = _lr()
            except Exception:
                intent_classifier = None
        if intent_classifier is None:
            # Fallback minimal
            from nokido_agent.app.forge_nlu import IntentVote as _IV

            class _NullNLU:
                """Classify hybrid.

                Args:
                    t: Description.
                """

                """Classify hybrid.

                Args:
                    t: Description.
                """
                """Classify hybrid.

                Args:
                    t: Description.
                """

                def classify_hybrid(self, t) -> object:
                    """Classify hybrid."""
                    return (_IV.CHAT, None, 0.5)

            intent_classifier = _NullNLU()
        try:
            from nokido_agent.app.forge_nlu import hybrid_classify as _hc

            """Static fn.

            Args:
                t: Description.
                _AT: Description.
            """
            """Static fn.

            Args:
                t: Description.
                _AT: Description.
            """
            """Static fn.

            Args:
                t: Description.
                _AT: Description.
            """

            def _static_fn(t, _AT=AgentType) -> object:
                """static fn."""
                return (_AT.CHAT, None)

            _res = _hc(user_input, _static_fn, router=intent_classifier)
            _istr, cmd_hint, _nlu_conf = _res if _res else ("chat", None, 0.5)
            intent = next((a for a in AgentType if a.value == _istr), AgentType.CHAT)
        except Exception:
            intent, cmd_hint, _nlu_conf = AgentType.CHAT, None, 0.5
        _conf_icon = "🎯" if _nlu_conf >= 0.72 else ("~" if _nlu_conf >= 0.52 else "?")
        debug_log(
            "ROUTE",
            "_dispatch_ai",
            "NLU hybride",
            {"intent": intent.value, "conf": round(_nlu_conf, 2), "text": user_input[:60]},
        )

        if intent == AgentType.ACTION:
            app.role_panel.activate("action_exec", "planner")
        elif intent == AgentType.RAG:
            app.role_panel.activate("rag")
            app.role_panel.set_rag(True)
        else:
            app.role_panel.activate("planner", "memory")

        # ── Agentic background : compétences RAG ────────────────────
        # Sur les requêtes complexes (score faible ou multi-domaines),
        # AgenticEngine pilote en amont via prepare_rag_context (étape 4)

        # ── Fast-path CHAT (< 100ms, sans pipeline lourd) ────────────
        # Predictif tres confiant + mode autonome + pas de commande
        response = ""
        agent_used = "dialogue"
        cmd_to_inject = cmd_hint

        _fast_chat = intent == AgentType.CHAT and _nlu_conf >= 0.72 and not cmd_hint and app._collab_mode == "autonome"
        if _fast_chat:
            app._set_status("[cyan]💬 Chat…[/]")
            orc = _orc_instance
            orc.state.current_session = app.session_name
            # AgenticEngine pilote le RAG même en fast-path
            if agentic_engine:
                rag_docs, _ = await agentic_engine.prepare_rag_context(user_input, k=4, role_hint="chat")
            else:
                rag_docs = await orc.agents["rag"].search_context(user_input, k=4)
            rag_text = orc.agents["rag"].format_docs(rag_docs) if rag_docs else ""
            if app.arch:
                rag_text = f"[Cible: {app.arch.context_hint()[:160]}]\n{rag_text}"
            ctx = {
                "user_input": user_input,
                "rag_context": rag_text,
                "conversation_history": orc._context_window[-6:],
            }
            response = await orc.agents["dialogue"].generate_response(ctx)
            meta = AGENT_META.get(app.current_agent, {"color": "#58a6ff", "icon": "🤖", "label": "Nokido"})
            chat.write(f"[bold {meta['color']}]{meta['icon']} {meta['label']}:[/] [dim]{_conf_icon}[/] {response}")
            if _g("HAS_PREDICTIF", False):
                try:
                    from nokido_agent.app.forge_nlu import get_router_if_ready as _pred_get_router

                    r = _pred_get_router()
                    if r:
                        r.feedback(user_input, "chat", "chat", weight=0.2)
                except Exception:
                    pass
            orc._push_context("user", user_input)
            orc._push_context("assistant", response)
            if app.context:
                app.context.add("user", user_input)
                app.context.add("assistant", response)
            return  # sort proprement du bloc try de _dispatch_ai

        # ────────────────────────────────────────────────────────
        # ROUTAGE — SmartRouter si disponible, sinon OrchestratorManager
        # ────────────────────────────────────────────────────────

        if _g("HAS_ROUTAGE", False) and app._smart_router:
            # ── SmartRouter (routage.py) ──────────────────────────────
            def _light(role_key: str):
                """Light.

                Args:
                    role_key: Description.
                """
                try:
                    app.role_panel.activate(role_key)
                except Exception:
                    pass

            app._set_status(f"[cyan]🧠 Routage {app._collab_mode}…[/]")
            route_result = None
            _raw_demande = user_input.strip()
            try:
                # FIX : passer _raw_demande (brut, sans [CONTEXTE CIBLE])
                # au SmartRouter → classify() reçoit la phrase réelle.
                # Le contexte enrichi (arch/web) est reconstruit
                # en interne par SmartRouter via arch=app.arch.
                route_result = await app._smart_router.route(
                    user_input=_raw_demande,
                    mode=app._collab_mode,
                    arch=app.arch,
                    on_role_light=_light,
                )
            except AttributeError as _sr_ae:
                # Version incompatible (ex: should_search manquant) → fallback
                logger.warning(f"SmartRouter incompatible ({_sr_ae}) — fallback OrchestratorManager")
                app._smart_router = None  # désactiver pour cette session
            except Exception as _sr_err:
                logger.warning(f"SmartRouter erreur: {_sr_err}")

            if route_result is not None:
                if route_result.response == "[TERMINAL]":
                    # Commande directe → injection PTY (cmd_to_inject déjà OK)
                    agent_used = "action"
                    if not cmd_to_inject:
                        # IMPORTANT : jamais injecter [CONTEXTE CIBLE] dans le PTY
                        # Extraire seulement la [DEMANDE] brute
                        _dm = re.search(r"\[DEMANDE\]\n(.+)", user_input, re.S)
                        cmd_to_inject = _dm.group(1).strip() if _dm else user_input.strip()
                        # Si la "commande" est en langage naturel sans
                        # vrai caractère shell → ne pas injecter, laisser
                        # le LLM répondre en dialogue
                        _real_sh = {"|", ">", "<", "&", ";", "$", "`", "\\\\", "*"}
                        _first_w = cmd_to_inject.split()[0].lower() if cmd_to_inject else ""
                        _is_natural = not any(c in cmd_to_inject for c in _real_sh) and _first_w not in SHELL_COMMANDS
                        if _is_natural:
                            agent_used = "dialogue"
                            cmd_to_inject = None
                else:
                    response = route_result.response
                    agent_used = route_result.agents_used[0] if route_result.agents_used else "dialogue"

                # Badges enrichissement
                badges = ""
                if route_result.web_used:
                    badges += " [dim]🌐[/]"
                    chat.write(f"[dim]  🌐 Web enrichi ({route_result.category.value})[/]")
                if route_result.rag_used:
                    badges += " [dim]🗄[/]"
                if len(route_result.agents_used) > 1:
                    icons = " ".join(AGENT_BY_KEY.get(k, {}).get("icon", "") for k in route_result.agents_used[:4])
                    badges += f" [dim]{icons}[/]"

                if response:
                    meta = AGENT_META[app.current_agent]
                    chat.write(f"[bold {meta['color']}]{meta['icon']} {meta['label']}:[/]{badges} {response}")

                # Afficher contributions en mode comité
                if app._collab_mode in ("collaboration", "comite"):
                    for c in route_result.contribs:
                        if not c.error and c.response:
                            chat.write(f"  [dim]{c.icon} {c.agent_name}:[/] [dim italic]{c.response[:150]}…[/]")

        if not (_g("HAS_ROUTAGE", False) and app._smart_router) or route_result is None:
            web_ctx = ""
            # Déclencheurs web : explicites ("cherche sur internet") + sujets
            _web_explicit = any(
                kw in user_input.lower()
                for kw in (
                    "cherche sur internet",
                    "google",
                    "recherche sur le web",
                    "cherche en ligne",
                    "trouve sur internet",
                    "recherche internet",
                    "sur le net",
                    "sur internet",
                )
            )
            _web_topic = any(
                kw in user_input.lower()
                for kw in (
                    "cve",
                    "exploit",
                    "actualité",
                    "news",
                    "dernière version",
                    "récent",
                    "vulnerability",
                    "changelog",
                    "release",
                )
            )
            if _g("HAS_WEB_SEARCH", False) and (_web_explicit or _web_topic):
                try:
                    app.role_panel.activate("discovery")
                    app._set_status("[cyan]🌐 Recherche web…[/]")
                    results = await _web_search_fn(user_input, max_results=3)
                    if results:
                        web_ctx = "\n".join(r[:500] for r in results if isinstance(r, str) and r)[:1500]
                        chat.write(f"[dim]🌐 {len([r for r in results if r])} résultats[/]")
                except Exception as we:
                    logger.debug(f"web_search fallback: {we}")
                app._set_status("[cyan]🤖 Traitement…[/]")

            orc = _orc_instance
            orc.state.current_session = app.session_name

            # ── CLEF : raw_demande extrait AVANT tout enrichissement ────
            # user_input ici = demande brute, pas encore de [CONTEXTE CIBLE]
            # On le capture maintenant pour ne JAMAIS passer le texte
            # enrichi au NLU (classify_with_cmd / classify_hybrid).
            _raw_demande = user_input.strip()

            arch_ctx = app.arch.context_hint() if app.arch else ""
            enriched = _raw_demande
            if arch_ctx:
                enriched = f"[CONTEXTE CIBLE]\n{arch_ctx}\n\n[DEMANDE]\n{_raw_demande}"
            if web_ctx:
                enriched += f"\n\n[RÉSULTATS WEB]\n{web_ctx}"

            debug_log(
                "ROUTE",
                "_dispatch_ai",
                "Enrichissement ctx",
                {
                    "raw_demande": _raw_demande[:60],
                    "has_arch": bool(arch_ctx),
                    "has_web": bool(web_ctx),
                    "enriched_len": len(enriched),
                },
            )

            # Respecter le mode collaboration/comite aussi en fallback
            _fb_mode = getattr(app, "_collab_mode", "autonome")
            if _fb_mode == "collaboration":
                app.role_panel.activate("planner", "devops", "security", "network", "rag")
                app.role_panel.set_rag(True)
                try:
                    from nokido_agent.app.forge_swarm import swarm as _sw

                    _sw.sm.set_streaming("CLAUDE")
                except Exception:
                    pass
                response, agent_used = await orc.run_collaboration(enriched)
                cmd_to_inject = cmd_hint
            elif _fb_mode == "comite":
                app.role_panel.activate("planner", "devops", "security", "memory")
                try:
                    from nokido_agent.app.forge_swarm import swarm as _sw

                    _sw.sm.set_streaming("CLAUDE")
                except Exception:
                    pass
                response, agent_used = await orc.run_comite(enriched)
                cmd_to_inject = cmd_hint
            else:
                # autonome — raw_demande GARANTI sans [CONTEXTE CIBLE]
                debug_log(
                    "ROUTE",
                    "_dispatch_ai",
                    "ORC process_user_input",
                    {"raw_demande": _raw_demande[:60], "enriched_has_ctx": "[CONTEXTE CIBLE]" in enriched},
                )
                result = await orc.process_user_input(enriched, raw_input=_raw_demande)
                if len(result) == 3:
                    response, agent_used, cmd_to_inject = result
                else:
                    response, agent_used = result
                    cmd_to_inject = cmd_hint

            meta = AGENT_META[app.current_agent]
            icons_map = {
                "action": "⚡",
                "rag": "🗄",
                "dialogue": "💬",
                "collaboration": "🤝",
                "comite": "⚖",
            }
            hint = f" [dim]{icons_map.get(agent_used, '')}[/]"
            chat.write(f"[bold {meta['color']}]{meta['icon']} {meta['label']}:[/]{hint} {response}")

        # ── Extraction commandes depuis la réponse LLM ─────────────
        # Si agent=dialogue/chat et réponse contient des blocs ```bash
        # → extraire la première commande et l'injecter dans le terminal
        # Sanity check : si cmd_to_inject contient [CONTEXTE CIBLE], le purger
        if cmd_to_inject and "[CONTEXTE CIBLE]" in cmd_to_inject:
            _dm2 = re.search(r"\[DEMANDE\]\n(.+)", cmd_to_inject, re.S)
            cmd_to_inject = _dm2.group(1).strip() if _dm2 else None
        if not cmd_to_inject and agent_used in ("dialogue", "rag", "collaboration", "comite"):
            _cmd_blocks = re.findall(r"```(?:bash|sh|shell)\s*\n([^`]+?)\n```", response, re.DOTALL | re.IGNORECASE)
            if not _cmd_blocks:
                # Fallback : ligne commençant par $ ou #
                _cmd_blocks = re.findall(r"^\s*\$\s+(.+)$", response, re.MULTILINE)
            if _cmd_blocks:
                # Prendre toutes les commandes non vides, filtrer les commentaires
                _cmds = [
                    l.strip()
                    for block in _cmd_blocks
                    for l in block.split("\n")
                    if l.strip() and not l.strip().startswith("#")
                ]
                if _cmds:
                    # Une commande → injection directe
                    # Plusieurs → on injecte séquentiellement avec &&
                    if len(_cmds) == 1:
                        cmd_to_inject = _cmds[0]
                    else:
                        cmd_to_inject = " && ".join(_cmds[:5])  # max 5 cmds
                    debug_log(
                        "ROUTE",
                        "_dispatch_ai",
                        "CMD extrait du reply LLM",
                        {"cmd": cmd_to_inject[:80], "blocks": len(_cmd_blocks)},
                    )

        # ── DangerGuard sur cmd_to_inject ─────────────────────────────
        if cmd_to_inject and app.guard and _g("HAS_DANGER_GUARD", False):
            from danger_guard import DangerLevel, should_auto_block, danger_confirmation_message

            _gc = app.guard.check(cmd_to_inject)
            if should_auto_block(_gc):
                chat.write(f"[bold red]☠ BLOQUÉ (IA) — {_gc.rule_name}[/]\n{_gc.explanation}")
                cmd_to_inject = None
            elif _gc.level >= DangerLevel.WARNING:
                _inject_cmd = cmd_to_inject
                cmd_to_inject = None  # on ne l'injecte pas encore

                async def _confirmed_inject(ok: bool):
                    """Confirmed inject.

                    Args:
                        ok: Description.
                    """
                    if not ok:
                        app._chat_log().write("[dim]Injection annulée.[/]")
                        return
                    if app.terminal._connected:
                        await app.terminal.inject(_inject_cmd)
                        app._chat_log().write(f"[dim]  ↳ [/][bold #3fb950]{escape(_inject_cmd)}[/][dim] → terminal[/]")
                    else:
                        app._chat_log().write(f"[yellow]⚡ {escape(_inject_cmd)}[/] [dim](terminal non connecté)[/]")

                app.push_screen(
                    ConfirmScreen(
                        danger_confirmation_message(_g),
                        lambda ok: asyncio.create_task(_confirmed_inject(ok)),
                    )
                )

        # ── Injection PTY automatique + suggestions dans la queue terminal ──
        if cmd_to_inject:
            # FIX BUG PTY : vérifier que cmd_to_inject est une vraie commande
            # et non une phrase en langage naturel avant d'injecter dans le PTY.
            # Si c'est du langage naturel → afficher dans le chat uniquement.
            _real_sh_chars = {"|", ">", "<", "&", ";", "$", "`", "\\", "*"}
            _inj_first_w = cmd_to_inject.split()[0].lower() if cmd_to_inject else ""
            _is_natural_lang = (
                not any(c in cmd_to_inject for c in _real_sh_chars)
                and _inj_first_w not in SHELL_COMMANDS
                and len(cmd_to_inject.split()) > 2  # 1-2 mots = peut être une cmd
            )
            if _is_natural_lang:
                # Langage naturel → NE PAS injecter dans le PTY
                debug_log(
                    "ROUTE", "_dispatch_ai", "PTY injection bloquée (langage naturel)", {"cmd": cmd_to_inject[:60]}
                )
                cmd_to_inject = None

        if cmd_to_inject:
            # Pousser cmd_to_inject + alternatives dans la queue d'autocomplete terminal
            _ac_eng = getattr(app, "_autocomplete_engine", None)
            if _ac_eng is None:
                try:
                    _ac_eng = app.query_one("#chat-input", _g("AutocompleteInput"))._engine
                except Exception:
                    _ac_eng = None

            if app.terminal._connected:
                await app.terminal.inject(cmd_to_inject)
                chat.write(f"[dim]  ↳ [/][bold #3fb950]{escape(cmd_to_inject)}[/][dim] → terminal[/]")
                # Enregistrer dans la queue terminal (↑ dans le terminal)
                if _ac_eng:
                    _ac_eng.push_terminal_suggestion(cmd_to_inject)
                # Commandes alternatives : enregistrer aussi (pas d'echo parasite)
                _all_cmds = app._extract_commands_from_response(response) if response else []
                _alt_cmds = [c for c in _all_cmds if c != cmd_to_inject]
                for _ac in _alt_cmds[:5]:
                    if _ac_eng:
                        _ac_eng.push_terminal_suggestion(_ac)
                if _alt_cmds:
                    chat.write(
                        "[dim]  💡 Alternatives (↑ dans terminal) : "
                        + ", ".join(f"[bold]{escape(c[:40])}[/]" for c in _alt_cmds[:4])
                        + "[/]"
                    )
            else:
                # Terminal non connecté — lister toutes les commandes dans le chat
                _all_cmds = app._extract_commands_from_response(response) if response else []
                if _all_cmds:
                    chat.write("[dim]💡 Commandes suggérées :[/]")
                    for i, c in enumerate(_all_cmds[:6]):
                        chat.write(f"  [bold #3fb950]{i + 1}.[/] [bold]{escape(c)}[/]")
                chat.write(
                    f"[yellow]⚡ Commande : [bold]{escape(cmd_to_inject)}[/] [dim](terminal non connecté — Ctrl+T)[/]"
                )

        # ── Allumage du rôle RAG si utilisé ─────────────────────────
        if agent_used == "rag":
            app.role_panel.activate("rag")
            app.role_panel.set_rag(True)
        elif agent_used == "action":
            app.role_panel.activate("action_exec")
        else:
            app.role_panel.activate("memory")

        # ── Session ────────────────────────────────────────────────────
        if app.context:
            app.context.add("user", user_input)
            app.context.add("assistant", response)

    except Exception as e:
        chat.write(f"[red]❌ Erreur : {escape(str(e))}[/]")
        logger.error(f"Erreur orchestrateur: {e}", exc_info=True)
    finally:
        app.ai_busy = False
        # MMap Context — done
        try:
            if _agent_ctx:
                _agent_ctx.done()
        except Exception:
            pass
        # Swarm — garantir retour IDLE
        try:
            from nokido_agent.app.forge_swarm import swarm as _swarm

            if _swarm.sm.active_agent == "CLAUDE":
                _swarm.sm.force_idle()
        except Exception:
            pass
        app._set_status("")
        # record_success + refresh SkillTree
        if agentic_engine and getattr(agentic_engine, "_current_skills", []) and response:
            _task_id = uuid.uuid4().hex[:8]
            for _sk in agentic_engine._current_skills:
                agentic_engine.record_success(_sk, _task_id)
            agentic_engine._current_skills = []
        try:
            app.skill_panel.render_summary(agentic_engine.get_skill_summary())
            _gauge = app.query_one("#entropy-gauge", EntropyGauge)
            _gauge.refresh_entropy(agentic_engine.entropy_level(), agentic_engine.entropy_color())
        except Exception:
            pass

        # Laisser les rôles allumés 3s puis éteindre
        async def _fade_roles() -> None:
            """Fade roles."""
            await asyncio.sleep(3)
            app.role_panel.reset()

        asyncio.create_task(_fade_roles())
