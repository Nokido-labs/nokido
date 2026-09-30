# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_handler_agents
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_handler_agents.py — Handlers agents, roles, collaboration
================================================================
Version 100% fonctionnelle — ne crash pas sans Ollama ni scoring.
Toutes les branches degradees sont gerees explicitement.
"""

import asyncio
import logging
from typing import Tuple, Any
from app.core.settings import get_app_attr as _g  # noqa

logger = logging.getLogger("Nokido.Handler.Agents")


# ── Helper escape safe (pas besoin de rich) ───────────────────────────────────
def _esc(text: str) -> str:
    """Esc.

    Args:
        text: Description.
    """
    try:
        from rich.markup import escape

        return escape(str(text))
    except Exception:
        return str(text).replace("[", "\\[")


# ─────────────────────────────────────────────────────────────────────────────
# _handle_role
# ─────────────────────────────────────────────────────────────────────────────
async def _handle_role(app, args: str) -> None:
    """
    @role [list|assign|detect <texte>|arch|score]
    Gestion des roles et modeles. Degrade proprement si scoring absent.
    """
    chat = app._chat_log()

    try:
        parts = args.split(maxsplit=1) if args.strip() else []
        sub = parts[0].lower() if parts else "list"

        # ── Mode scorer natif ─────────────────────────────────────────────
        scorer = getattr(app, "scorer", None)
        if scorer and _g("HAS_SCORING", False):
            if sub in ("list", "score"):
                arch = getattr(app, "arch", None)
                chat.write(scorer.report(arch))
                if arch:
                    chat.write(f"[dim]  Cible : {arch.summary()}[/]")
                return

            elif sub == "assign":
                chat.write("[dim]⏳ Re-scoring…[/]")
                try:
                    await scorer.refresh(bench=True)
                    arch = getattr(app, "arch", None)
                    from nokido_agent.app.forge_startup import auto_select_models, save_last_assignment

                    selected = await auto_select_models(scorer, arch)
                    app.model_chat = selected.get("chat", "")
                    app.model_action = selected.get("action", "")
                    app.model_rag = selected.get("rag", "")
                    if hasattr(app, "_update_sidebar_title"):
                        app._update_sidebar_title()
                    save_last_assignment(app.model_chat, app.model_action, app.model_rag)
                    chat.write(
                        f"[green]✅ Modeles assignes :[/]\n"
                        f"  💬 Chat   → {app.model_chat}\n"
                        f"  ⚡ Action → {app.model_action}\n"
                        f"  🗄 RAG    → {app.model_rag}"
                    )
                except Exception as e:
                    chat.write(f"[red]❌ Scoring : {_esc(e)}[/]")
                return

            elif sub == "arch":
                try:
                    app.arch = await scorer.get_arch(force=True)
                    if app.arch:
                        chat.write(f"[green]✅ Architecture :[/] {app.arch.summary()}")
                    else:
                        chat.write("[yellow]⚠ Architecture non detectee[/]")
                except Exception as e:
                    chat.write(f"[red]❌ {_esc(e)}[/]")
                return

            elif sub == "detect" and len(parts) > 1:
                text = parts[1]
                if _g("HAS_LOOPS", False):
                    try:
                        from nokido_agent.app.forge_agents import IntentRouter, ROLE_META

                        arch = getattr(app, "arch", None)
                        router = IntentRouter()
                        role, conf, secondary = router.route_with_confidence(text)
                        model = scorer.best_for(role, arch)
                        meta = ROLE_META.get(role, {})
                        chat.write(
                            f"[bold]Role :[/] {meta.get('icon', '?')} "
                            f"[bold]{meta.get('label', str(role))}[/] "
                            f"(conf={conf:.0%}) → {model}"
                        )
                    except Exception as e:
                        chat.write(f"[red]❌ detect : {_esc(e)}[/]")
                else:
                    chat.write("[yellow]⚠ roles.py non disponible[/]")
                return

        # ── Mode sans scorer — afficher config modeles courante ──────────
        if sub in ("list", "score", ""):
            chat.write(
                "[bold]Modeles actifs :[/]\n"
                f"  💬 Chat   → [bold]{getattr(app, 'model_chat', '—')}[/]\n"
                f"  ⚡ Action → [bold]{getattr(app, 'model_action', '—')}[/]\n"
                f"  🗄 RAG    → [bold]{getattr(app, 'model_rag', '—')}[/]\n"
                "[dim]  Scoring non disponible — @role assign non actif[/]"
            )
            return

        if sub == "assign":
            chat.write("[yellow]⚠ Scoring non disponible (HAS_SCORING=False)[/]")
            return

        if sub == "detect" and len(parts) > 1:
            chat.write("[yellow]⚠ Scoring non disponible pour la detection[/]")
            return

        # Aide
        chat.write(
            "[bold]@role[/] list|assign|detect <texte>|arch|score\n"
            "  list   — modeles actifs\n"
            "  assign — re-assigne par scoring\n"
            "  arch   — re-detecte l'architecture\n"
            "  detect <texte> — detecte le role"
        )

    except Exception as e:
        logger.error(f"_handle_role: {e}", exc_info=True)
        try:
            chat.write(f"[red]❌ _handle_role: {_esc(e)}[/]")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# _handle_mode
# ─────────────────────────────────────────────────────────────────────────────
async def _handle_mode(app, args: str) -> None:
    """
    @mode [autonome|collaboration|comite] [set] <tache>
    """
    chat = app._chat_log()

    try:
        MODES = ("autonome", "collaboration", "comite")
        ICONS = {"autonome": "🤖", "collaboration": "🤝", "comite": "⚖️"}
        DESCS = {
            "autonome": "Nokido pilote — Ollama execute",
            "collaboration": "Claude + Cline PLAN/ACT + Ollama",
            "comite": "Tous proposent — Nokido vote",
        }
        MODE_MAP = {
            "autonome": ("auto", {}),
            "collaboration": ("cline", {"timeout": 180}),
            "comite": ("debat", {"rounds": 2}),
        }
        COLORS = {"autonome": "#58a6ff", "collaboration": "#3fb950", "comite": "#d2a8ff"}

        parts = args.split(maxsplit=1) if args.strip() else []

        # Afficher mode actuel
        if not parts or parts[0].lower() in ("", "status"):
            m = getattr(app, "_collab_mode", "autonome")
            chat.write(
                f"[bold]Mode actuel :[/] {ICONS.get(m, '?')} [bold]{m}[/]\n"
                f"  {DESCS.get(m, '')}\n\n"
                "[bold]Disponibles :[/]\n"
                "  🤖 autonome      — @mode autonome <tache>\n"
                "  🤝 collaboration — @mode collaboration <tache>\n"
                "  ⚖️  comite        — @mode comite <tache>"
            )
            return

        # set mode
        if parts[0].lower() == "set" and len(parts) > 1:
            m = parts[1].strip().lower()
            if m in MODES:
                app._collab_mode = m
                try:
                    app._update_mode_buttons()
                except Exception:
                    pass
                chat.write(f"[green]✅ Mode → {ICONS.get(m, '')} [bold]{m}[/][/]")
            else:
                chat.write(f"[red]❌ Mode inconnu : {_esc(m)}[/]")
            return

        # Extraire mode + tache
        first = parts[0].lower()
        if first in MODES:
            mode = first
            task = parts[1].strip() if len(parts) > 1 else ""
        else:
            mode = getattr(app, "_collab_mode", "autonome")
            task = args.strip()

        if not task:
            chat.write(f"[red]❌ Tache manquante. Ex : @mode {mode} configurer AdGuard[/]")
            return

        collab_sub, collab_opts = MODE_MAP[mode]
        color = COLORS[mode]
        icon = ICONS[mode]
        chat.write(f"[bold {color}]{icon} Mode {mode.capitalize()}[/] → {_esc(task)}")
        try:
            app._set_status(f"[{color}]{icon} {mode.capitalize()}…[/]")
        except Exception:
            pass

        async def _run_mode() -> None:
            """Run mode."""
            try:
                from nokido_agent.app.forge_collab_modes import run_collab

                await run_collab(chat, collab_sub, task, collab_opts)
            except Exception as _e:
                import traceback as _tb

                chat.write(
                    f"[bold red]❌ Mode {mode} :[/]\n[red]{_esc(_e)}[/]\n[dim]{_esc(_tb.format_exc()[-400:])}[/]"
                )
            finally:
                try:
                    app._set_status("")
                except Exception:
                    pass

        asyncio.create_task(_run_mode())

    except Exception as e:
        logger.error(f"_handle_mode: {e}", exc_info=True)
        try:
            chat.write(f"[red]❌ _handle_mode: {_esc(e)}[/]")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# run_collaboration
# ─────────────────────────────────────────────────────────────────────────────
async def run_collaboration(app, task: str) -> Tuple[str, str]:
    """
    Mode collaboration : delegue a forge_collab_modes.
    Retourne ("ok", task) ou ("error", message).
    """
    try:
        from nokido_agent.app.forge_collab_modes import run_collab

        await run_collab(app._chat_log(), "cline", task, {})
        return ("ok", task)
    except Exception as e:
        logger.warning(f"run_collaboration: {e}")
        return ("error", str(e))


# ─────────────────────────────────────────────────────────────────────────────
# run_comite
# ─────────────────────────────────────────────────────────────────────────────
async def run_comite(app, task: str) -> Tuple[str, str]:
    """
    Mode comite : plusieurs agents proposent, Nokido vote.
    Delegue a forge_collab_modes en mode debat.
    Retourne ("ok", task) ou ("error", message).

    Protection tasks orphelines :
    - asyncio.wait_for avec timeout strict
    - Les tasks internes lancees par run_collab sont collectees
      et annulees si elles n'ont pas fini avant le timeout.
    """
    chat = app._chat_log()
    _tasks_before = set(asyncio.all_tasks())
    try:
        from nokido_agent.app.forge_collab_modes import run_collab

        await asyncio.wait_for(run_collab(chat, "debat", task, {"rounds": 2}), timeout=10.0)
        return ("ok", task)
    except asyncio.TimeoutError:
        logger.info("run_comite: timeout (Ollama indisponible)")
        chat.write("[yellow]⚠ run_comite: timeout (Ollama indisponible)[/]")
        return ("error", "timeout")
    except BaseException as e:
        logger.warning(f"run_comite: {type(e).__name__}: {e}")
        try:
            chat.write(f"[yellow]⚠ run_comite: {_esc(e)}[/]")
        except Exception:
            pass
        return ("error", str(e))
    finally:
        # Annuler les tasks orphelines creees pendant l'appel
        _tasks_after = set(asyncio.all_tasks())
        _orphans = _tasks_after - _tasks_before - {asyncio.current_task()}
        for _t in _orphans:
            _t.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(_t), timeout=0.5)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Reexportations — requis par forge_handlers.py L2761
# Ces fonctions sont implementees dans forge_handlers.py et forge_orchestrator.py
# forge_handler_agents les reexporte pour eviter l'ImportError au boot.
# ─────────────────────────────────────────────────────────────────────────────

try:
    from nokido_agent.app.forge_handlers import (
        generate_response as generate_response,  # noqa: F401
        _heuristic_analysis as _heuristic_analysis,  # noqa: F401
        process_user_input as process_user_input,  # noqa: F401
    )
except ImportError:
    # Stubs de secours si forge_handlers n'est pas encore charge
    # (evite les imports circulaires au premier boot)
    from typing import Dict, Any

    async def generate_response(app, context: Dict[str, Any]) -> str:  # type: ignore[misc]
        """Stub — implementation dans forge_handlers.generate_response."""
        logger.warning("generate_response: forge_handlers non charge, stub actif")
        return "[generate_response stub]"

    def _heuristic_analysis(app, text: str):  # type: ignore[misc]
        """Stub — implementation dans forge_handlers._heuristic_analysis."""
        logger.warning("_heuristic_analysis: forge_handlers non charge, stub actif")
        return None

    async def process_user_input(app, user_input: str, raw_input=None):  # type: ignore[misc]
        """Stub — implementation dans forge_handlers.process_user_input."""
        logger.warning("process_user_input: forge_handlers non charge, stub actif")
        return None
