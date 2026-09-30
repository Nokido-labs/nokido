# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_agentic
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""forge_agentic.py — Handlers agentic/evolve extraits de Nokido.py (v16.5)"""

import asyncio, json
from rich.markup import escape
import logging

# ── Chemins Nokido ────────────────────────────────────────────────────────
_ROOT_P = __import__("pathlib").Path(__file__).resolve().parent.parent
_ROOT_DIR = _ROOT_P
_APP_DIR = _ROOT_P / "app"
_DATA_DIR = _ROOT_P / "data"
_LOGS_DIR = _ROOT_P / "logs"
_DATA_DIR.mkdir(exist_ok=True)
_LOGS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)
from app.core.settings import get_app_attr as _g  # centralisé
from app.forge_agentic_engine import EvolutionOrchestrator
from app.forge_code import get_sandbox


# ── _handle_agentic ─────────────────────────────────────────────────


async def handle_agentic(app, cmd_line: str) -> None:
    # ── Analyse agentic par compétences ─────────────────────────
    """Handle agentic.

    Args:
        app: Description.
        cmd_line: Description.
    """
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    agentic_engine = _ac.agentic_engine
    parts_ag = cmd_line[9:].strip().split(None, 1)
    sub_ag = parts_ag[0].lower() if parts_ag else "help"
    chat = app._chat_log()
    arg_ag = parts_ag[1] if len(parts_ag) > 1 else ""

    if sub_ag == "skills":
        if agentic_engine:
            skills = agentic_engine.get_skill_summary()
            if skills:
                chat.write("[bold #a371f7]🧠 Compétences RAG :[/]")
                for s in skills:
                    v = "🏆" if s["verified"] else ("✅" if s["status"] == "mastered" else "🧪")
                    chat.write(
                        f"  {v} [bold]{s['name']:<12}[/] "
                        f"score=[cyan]{s['score']:.2f}[/] "
                        f"uses={s['uses']} "
                        f"{'[green]VERIFIED[/]' if s['verified'] else '[yellow]UNVERIFIED[/]'}"
                    )
            else:
                chat.write("[dim]Aucune compétence enregistrée. @agentic run <tâche>[/dim]")
        else:
            chat.write("[yellow]AgenticEngine non initialisé[/]")

    elif sub_ag == "clear":
        if agentic_engine:
            agentic_engine._skills.clear()
            agentic_engine._save_skills()
            app.skill_panel.clear_skills()
            chat.write("[dim]Registre de compétences vidé.[/dim]")

    elif sub_ag == "verify":
        # Forcer re-vérification de toutes les compétences
        if agentic_engine:

            async def _reverify() -> None:
                """Reverify."""
                for skill in list(agentic_engine._skills.keys()):
                    score = await agentic_engine.check_competence(skill)
                    agentic_engine._skills[skill].score = score
                agentic_engine._save_skills()
                app.skill_panel.render_summary(agentic_engine.get_skill_summary())
                chat.write("[green]✅ Re-vérification terminée[/]")

            asyncio.create_task(_reverify())
        else:
            chat.write("[yellow]AgenticEngine non initialisé[/]")

    elif sub_ag in ("run", "") or (sub_ag not in ("skills", "clear", "verify", "help") and sub_ag):
        # @agentic <tâche> — analyser et préparer les compétences
        task_text = cmd_line[9:].strip()
        if sub_ag == "run":
            task_text = arg_ag
        if not task_text:
            chat.write(
                "[bold]@agentic[/] <tâche>  — analyse les compétences requises\n"
                "  skills  — liste les compétences enregistrées\n"
                "  verify  — re-vérifie tous les scores\n"
                "  clear   — remet à zéro le registre\n"
                "[dim]Exemple : @agentic configure un VPN WireGuard avec authentification[/dim]"
            )
        elif not agentic_engine:
            chat.write("[red]❌ AgenticEngine non initialisé[/]")
        else:

            async def _run_agentic(_t=task_text) -> None:
                """Run agentic.

                Args:
                    _t: Description.
                """
                try:
                    result = await agentic_engine.process_complex_task(_t)
                    s_list = ", ".join(result["skills"])
                    miss = ", ".join(result["missing"]) if result["missing"] else "aucune"
                    chat.write(
                        f"[bold]Compétences analysées :[/] {s_list}\n"
                        f"  Manquantes : [yellow]{miss}[/]\n"
                        f"  Prêt : {'[green]OUI ✅[/]' if result['ready'] else '[yellow]NON — apprentissage en cours[/]'}"
                    )
                    # Rafraîchir le panneau
                    app.skill_panel.render_summary(agentic_engine.get_skill_summary())
                except Exception as _err:
                    chat.write(f"[red]❌ @agentic : {escape(str(_err))}[/]")

            asyncio.create_task(_run_agentic())

    else:
        chat.write(
            "[bold]@agentic[/] <tâche> | skills | verify | clear\n"
            "[dim]Analyse les compétences RAG requises pour une tâche complexe.\n"
            "Déclenche l'apprentissage automatique si une compétence est insuffisante.[/dim]"
        )

    # ── _handle_evolve ──────────────────────────────────────────────────

    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    rag_engine = _ac.rag_engine
    settings = _ac.settings
    version_manager = _ac.version_manager


async def handle_evolve(app, cmd_line: str) -> None:
    # ── Cycle auto-évolution RAG ─────────────────────────────────
    """Handle evolve.

    Args:
        app: Description.
        cmd_line: Description.
    """
    from nokido_agent.app.forge_app_context import get_settings as _gset

    settings = _gset()
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    rag_engine = _ac.rag_engine
    version_manager = _ac.version_manager
    parts_ev = cmd_line[7:].strip().split(None, 1)
    sub_ev = parts_ev[0].lower() if parts_ev else "start"
    arg_ev = parts_ev[1] if len(parts_ev) > 1 else ""
    chat = app._chat_log()

    if sub_ev in ("start", "") or (sub_ev not in ("status", "bench", "scores", "help") and sub_ev):
        # @evolve <query> — lancer le cycle avec la query donnée
        query_ev = cmd_line[7:].strip() if sub_ev not in ("start", "status", "bench", "scores", "help") else arg_ev
        if not query_ev:
            chat.write(
                "[bold]@evolve[/] <requête>  — cycle auto-évolution RAG\n"
                "  Exemple : @evolve comment mieux détecter les switches Cisco\n"
                "  [dim]status — état · bench — lancer benchmark · scores — afficher scores[/dim]"
            )
        else:
            if not rag_engine:
                chat.write("[red]❌ RAG non initialisé[/]")
            else:
                _evo = EvolutionOrchestrator(
                    ollama_url=settings.ollama_url,
                    vm=version_manager,
                    rag=rag_engine,
                    sandbox=get_sandbox(settings.ollama_url, rag_engine) if _g("HAS_SANDBOX", False) else None,
                    log_fn=lambda m: chat.write(m),
                )

                async def _run_evo(_q=query_ev, _e=_evo) -> None:
                    """Run evo.

                    Args:
                        _q: Description.
                        _e: Description.
                    """
                    try:
                        result = await _e.run_full_cycle(_q)
                        scores = result.get("scores", {})
                        if scores:
                            chat.write(
                                f"[dim]Scores benchmark : "
                                f"avant={scores.get('old', 0):.3f} "
                                f"après={scores.get('new', 0):.3f}[/dim]"
                            )
                    except Exception as _err:
                        chat.write(f"[red]❌ @evolve : {escape(str(_err))}[/]")

                asyncio.create_task(_run_evo())

                from nokido_agent.app.forge_app_context import app_ctx as _actx

                _ac = _actx()
                rag_engine = _ac.rag_engine
                settings = _ac.settings
                version_manager = _ac.version_manager
    elif sub_ev == "bench":
        if not rag_engine:
            chat.write("[red]❌ RAG non initialisé[/]")
        else:
            chat.write("[dim]⏳ Benchmark RAG en cours…[/dim]")

            async def _bench_only() -> None:
                """Bench only."""
                from nokido_agent.app.forge_app_context import get_settings as _gset

                settings = _gset()
                _e = EvolutionOrchestrator(
                    ollama_url=settings.ollama_url,
                    vm=version_manager,
                    rag=rag_engine,
                    log_fn=lambda m: chat.write(m),
                )
                score = await _e._run_benchmark()
                chat.write(f"[bold]Score benchmark RAG : {score:.3f}[/bold]")

            asyncio.create_task(_bench_only())

    elif sub_ev == "scores":
        _sf = _DATA_DIR / "last_scores.json"
        if _sf.exists():
            try:
                _sc = json.loads(_sf.read_text())
                chat.write(f"[bold]Dernier score benchmark :[/bold] {_sc.get('avg', 0):.3f}")
            except Exception:
                chat.write("[dim]Fichier scores illisible[/dim]")
        else:
            chat.write("[dim]Aucun score benchmark enregistré — @evolve bench[/dim]")

    else:
        chat.write(
            "[bold]@evolve[/] <requête>\n"
            "  @evolve <query>  — cycle complet (disco→audit→sandbox→bench→merge)\n"
            "  @evolve bench    — lancer le benchmark seul\n"
            "  @evolve scores   — afficher le dernier score\n"
            "[dim]Le cycle modifie le code source et le ré-ingère dans le RAG.[/dim]"
        )
