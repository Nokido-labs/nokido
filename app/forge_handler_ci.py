"""Implémente les handlers de chat TUI @workflow, @ci, @loop et @audit, qui pilotent le
gestionnaire Prefect, des commandes SSH distantes et la boucle d'amélioration.

Entrées : _handle_workflow, _handle_ci, _handle_loop, _handle_audit (coroutines
prenant l'app TUI et, sauf _handle_audit, la chaîne d'arguments).
Utilisé par forge_dispatch.py (@workflow, @ci), forge_commands.py et forge_handlers.py.
Effets : commandes SSH via get_prefect_manager().run_ssh_command (flake8, shellcheck,
eslint, pytest, git, uname...) ; sous-processus locaux pylint, black et mypy ;
requêtes LLM via forge_ollama ; rapports ajoutés au RAG (add_session_message) ;
écrit logs/loop_error_<id>.log en cas d'échec de @loop.
"""
from __future__ import annotations

# Import oublie, mesure le 2026-09-08 : uuid.UUID() L215.
import uuid

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_165156_astdoc
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: fallback
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_handler_ci.py — Handlers CI/CD, workflow, loop
=====================================================
Extrait de forge_handlers.py — Phase 3 refactor.
Importez depuis ce module plutôt que forge_handlers pour ce domaine.
"""

import datetime
import re
import asyncio
import logging
import traceback
from pathlib import Path
from app.core.settings import get_app_attr as _g
from nokido_agent.app import forge_context as _forge_ctx_ci

_g_rag_ci = lambda: _forge_ctx_ci.rag_engine  # noqa — requis par handlers
from rich.markup import escape
from nokido_agent.app.forge_context import get_version_manager as _gvm_global
from nokido_agent.app import forge_context  # noqa — requis par _handle_workflow bare refs
from app.forge_ui_widgets import EntropyGauge

logger = logging.getLogger("Nokido.Forge.Handler.Ci")


async def _handle_workflow(app, args: str):
    """
    chat = app._chat_log()
    @workflow                           — aide
    @workflow list                      — workflows locaux + Prefect
    @workflow run <nom>                 — exécuter un workflow local
    @workflow add <nom> <c1>|<c2>…     — créer (étapes séparées par |)
    @workflow del <nom>                 — supprimer
    @workflow show <nom>                — afficher les étapes
    @workflow deploy <svc> [stratégie]  — restart|compose|systemd|docker|rollback
    @workflow history                   — historique des exécutions
    @workflow cancel <id>               — annuler un run Prefect
    @workflow logs <id>                 — logs d'un run Prefect
    """
    from nokido_agent.app.forge_prefect import get_client

    chat = app._chat_log()
    parts = args.split()
    sub = parts[0].lower() if parts else ""

    if not sub:
        chat.write(
            "[bold #58a6ff]@workflow[/] — sous-commandes :\n"
            "  [bold]list[/]                          workflows locaux + Prefect\n"
            "  [bold]run[/] [dim]<nom>[/]                      exécuter un workflow local\n"
            "  [bold]add[/] [dim]<nom> <cmd1>|<cmd2>…[/]        créer/modifier\n"
            "  [bold]del[/] [dim]<nom>[/]                      supprimer\n"
            "  [bold]show[/] [dim]<nom>[/]                     voir les étapes\n"
            "  [bold]deploy[/] [dim]<service> [restart|compose|systemd|docker|rollback][/]\n"
            "  [bold]history[/]                       historique des exécutions\n"
            "  [bold]cancel[/] [dim]<id>[/]  [bold]logs[/] [dim]<id>[/]  (Prefect)"
        )
        return

    # ── list ────────────────────────────────────────────────────────
    elif sub == "list":
        local = forge_context.get_prefect_manager().workflow_list()
        if local:
            chat.write("[bold]Workflows locaux :[/]")
            for wf in local:
                steps = forge_context.get_prefect_manager()._custom_workflows[wf]
                chat.write(f"  [bold #3fb950]{wf}[/] [dim]({len(steps)} étapes)[/]")
        else:
            chat.write("[dim]Aucun workflow local. Crée-en un avec @workflow add …[/]")
        if _g("HAS_PREFECT", False) and forge_context.get_prefect_manager().client:
            try:
                async with get_client() as client:
                    runs = await client.read_flow_runs(limit=10)
                    if runs:
                        chat.write("[bold]Runs Prefect récents :[/]")
                        for r in runs:
                            icon = "✅" if r.state.type == "COMPLETED" else "❌" if r.state.type == "FAILED" else "⏳"
                            chat.write(f"  {icon} [bold]{r.name}[/] [dim]{r.state.type} — {str(r.id)[:8]}[/]")
            except Exception as e:
                chat.write(f"[dim]Prefect: {e}[/]")

    # ── run ─────────────────────────────────────────────────────────
    elif sub == "run" and len(parts) >= 2:
        wf_name = parts[1]
        if wf_name not in forge_context.get_prefect_manager()._custom_workflows:
            known = forge_context.get_prefect_manager().workflow_list()
            chat.write(f"[yellow]⚠ Workflow '{wf_name}' inconnu.[/]  Connus : {', '.join(known) or 'aucun'}")
            return
        chat.write(f"[dim]▶ Exécution du workflow [bold]{wf_name}[/]…[/]")

        async def do_wf(_n=wf_name) -> None:
            """Do wf.

            Args:
                _n: Description.
            """
            """Step.

            Args:
                icon: Description.
                msg: Description.
            """

            def _step(icon, msg) -> None:
                """step."""
                chat.write(f"{icon} {msg}")

            try:
                result = await forge_context.get_prefect_manager().run_workflow(_n, on_step=_step)
                chat.write(result)
            except Exception as e:
                chat.write(f"[red]❌ {e}[/]")

        asyncio.create_task(do_wf())

    # ── add ─────────────────────────────────────────────────────────
    elif sub == "add" and len(parts) >= 3:
        wf_name = parts[1]
        raw_steps = args[len("add ") + len(wf_name) + 1 :]
        steps = [s.strip() for s in raw_steps.split("|") if s.strip()]
        if not steps:
            chat.write(
                "[yellow]⚠ Indique au moins une étape séparée par |[/]\n  Ex: @workflow add deploy cd /app | git pull | make restart"
            )
            return
        forge_context.get_prefect_manager()._custom_workflows[wf_name] = steps
        chat.write(f"[green]✅ Workflow [bold]{wf_name}[/] enregistré — {len(steps)} étape(s) :[/]")
        for i, s in enumerate(steps, 1):
            chat.write(f"  [dim]{i}.[/] {s}")

    # ── del ─────────────────────────────────────────────────────────
    elif sub == "del" and len(parts) >= 2:
        wf_name = parts[1]
        if wf_name in forge_context.get_prefect_manager()._custom_workflows:
            del forge_context.get_prefect_manager()._custom_workflows[wf_name]
            chat.write(f"[green]✅ Workflow '{wf_name}' supprimé.[/]")
        else:
            chat.write(f"[yellow]⚠ '{wf_name}' introuvable.[/]")

    # ── show ────────────────────────────────────────────────────────
    elif sub == "show" and len(parts) >= 2:
        wf_name = parts[1]
        steps = forge_context.get_prefect_manager()._custom_workflows.get(wf_name)
        if not steps:
            chat.write(f"[yellow]⚠ Workflow '{wf_name}' inconnu.[/]")
            return
        chat.write(f"[bold]Workflow [#3fb950]{wf_name}[/] — {len(steps)} étapes :[/]")
        for i, s in enumerate(steps, 1):
            chat.write(f"  [dim]{i}.[/] [bold]{s}[/]")

    # ── deploy ──────────────────────────────────────────────────────
    elif sub == "deploy" and len(parts) >= 2:
        service = parts[1]
        strategy = parts[2].lower() if len(parts) >= 3 else "restart"
        valid = {"restart", "compose", "systemd", "docker", "rollback"}
        if strategy not in valid:
            chat.write(f"[yellow]⚠ Stratégie '{strategy}' inconnue.[/]  Disponibles : {', '.join(sorted(valid))}")
            return
        chat.write(f"[dim]🚀 Déploiement [bold]{service}[/] [{strategy}]…[/]")

        async def do_deploy(_svc=service, _strat=strategy) -> None:
            """Do deploy.

            Args:
                _svc: Description.
                _strat: Description.
            """
            """Step.

            Args:
                icon: Description.
                msg: Description.
            """

            def _step(icon, msg) -> None:
                """step."""
                chat.write(f"{icon} {msg}")

            try:
                result = await forge_context.get_prefect_manager().deploy(_svc, _strat, on_step=_step)
                chat.write(result)
            except Exception as e:
                chat.write(f"[red]❌ Déploiement: {e}[/]")

        asyncio.create_task(do_deploy())

    # ── history ─────────────────────────────────────────────────────
    elif sub == "history":
        hist = forge_context.get_prefect_manager().pipeline_history(15)
        if not hist:
            chat.write("[dim]Aucun pipeline dans l'historique de cette session.[/]")
            return
        chat.write("[bold]Historique des pipelines :[/]")
        for e in reversed(hist):
            icon = "✅" if e["status"] in ("SUCCESS", "DEPLOYED") else ("⚠" if e["status"] == "PARTIAL" else "❌")
            chat.write(f"  {icon} [bold]{e['name'][:40]}[/]  [dim]{e['status']} — {e['time']}[/]")
            if e["detail"]:
                chat.write(f"      [dim italic]{e['detail'][:80]}[/]")

    # ── cancel (Prefect) ────────────────────────────────────────────
    elif sub == "cancel" and len(parts) >= 2:
        if not (_g("HAS_PREFECT", False) and forge_context.get_prefect_manager().client):
            chat.write("[yellow]⚠ Prefect non disponible[/]")
            return
        fid = parts[1]
        try:
            async with get_client() as client:
                await client.cancel_flow_run(uuid.UUID(fid))
                chat.write(f"[green]✅ Run {fid[:8]}… annulé[/]")
        except Exception as e:
            chat.write(f"[red]❌ {e}[/]")

    # ── logs (Prefect) ──────────────────────────────────────────────
    elif sub == "logs" and len(parts) >= 2:
        if not (_g("HAS_PREFECT", False) and forge_context.get_prefect_manager().client):
            chat.write("[yellow]⚠ Prefect non disponible[/]")
            return
        fid = parts[1]
        try:
            async with get_client() as client:
                logs = await client.read_logs(flow_run_id=uuid.UUID(fid))
                chat.write(f"[bold]Logs run {fid[:8]}… :[/]")
                for log in logs[-25:]:
                    lvl = str(getattr(log, "level", ""))
                    col = "#ff7b72" if lvl in ("ERROR", "CRITICAL") else "#d2a8ff" if lvl == "WARNING" else "#8b949e"
                    chat.write(f"  [dim]{log.timestamp}[/] [{col}]{log.message}[/]")
        except Exception as e:
            chat.write(f"[red]❌ {e}[/]")

    else:
        chat.write(f"[yellow]⚠ Sous-commande '{sub}' inconnue.[/]  Tape [bold]@workflow[/] pour l'aide.")


async def _handle_ci(app, args: str):
    """
    chat = app._chat_log()
    @ci                          — aide
    @ci run <repo> [branche]     — lancer un pipeline CI complet
    @ci run <repo> [b] [dir]     — avec répertoire de travail custom
    @ci status                   — derniers pipelines (historique)
    @ci lint <dossier>           — analyse statique SSH (flake8/eslint/shellcheck)
    @ci test <dossier>           — tests uniquement (pytest/npm test)
    @ci diff <repo>              — git diff résumé du dernier commit
    @ci env                      — infos runtime sur le serveur (python/node/docker)
    """
    chat = app._chat_log()
    parts = args.split()
    sub = parts[0].lower() if parts else ""

    if not sub:
        chat.write(
            "[bold #58a6ff]@ci[/] — sous-commandes :\n"
            "  [bold]run[/] [dim]<repo_url> [branche] [workdir][/]  pipeline complet\n"
            "  [bold]status[/]                              historique\n"
            "  [bold]lint[/] [dim]<dossier>[/]                       analyse statique\n"
            "  [bold]test[/] [dim]<dossier>[/]                       tests uniquement\n"
            "  [bold]diff[/] [dim]<dossier>[/]                       git diff dernier commit\n"
            "  [bold]env[/]                                 infos runtime serveur"
        )
        return

    # ── run ─────────────────────────────────────────────────────────
    elif sub == "run" and len(parts) >= 2:
        repo = parts[1]
        branch = parts[2] if len(parts) >= 3 else "main"
        workdir = parts[3] if len(parts) >= 4 else "/tmp/ci-repo"
        chat.write(f"[dim]🚀 Pipeline CI : [bold]{repo}[/] @ [bold]{branch}[/]  → {workdir}[/]")

        async def do_ci(_r=repo, _b=branch, _w=workdir) -> None:
            """Do ci.

            Args:
                _r: Description.
                _b: Description.
                _w: Description.
            """
            """Step.

            Args:
                icon: Description.
                msg: Description.
            """

            def _step(icon, msg) -> None:
                """step."""
                chat.write(f"{icon} {msg}")

            try:
                result = await forge_context.get_prefect_manager().run_ci_pipeline(
                    _r, branch=_b, workdir=_w, on_step=_step
                )
                chat.write(result)
            except Exception as e:
                chat.write(f"[red]❌ CI : {e}[/]")

        asyncio.create_task(do_ci())

    # ── status ──────────────────────────────────────────────────────
    elif sub == "status":
        hist = forge_context.get_prefect_manager().pipeline_history(10)
        if not hist:
            chat.write("[dim]Aucun pipeline exécuté dans cette session.[/]")
            return
        chat.write("[bold]Historique CI :[/]")
        for e in reversed(hist):
            icon = "✅" if e["status"] == "SUCCESS" else "⚠" if e["status"] == "PARTIAL" else "❌"
            chat.write(f"  {icon} [bold]{e['name'][:40]}[/]  [dim]{e['status']} — {e['time']}[/]")

    # ── lint ────────────────────────────────────────────────────────
    elif sub == "lint" and len(parts) >= 2:
        folder = parts[1]
        chat.write(f"[dim]🔎 Analyse statique de [bold]{folder}[/]…[/]")

        async def do_lint(_f=folder) -> None:
            """Do lint.

            Args:
                _f: Description.
            """
            results = []
            # Python
            try:
                out = await forge_context.get_prefect_manager().run_ssh_command(
                    f"cd {_f} && python -m flake8 --max-line-length=120 --statistics . 2>&1 | head -40"
                )
                results.append(f"[bold]flake8 :[/]\n{out[:600] or '  ✅ Aucun problème'}")
            except RuntimeError as e:
                results.append(f"[dim]flake8 : {str(e)[:100]}[/]")
            # Shell
            try:
                sh_files = await forge_context.get_prefect_manager().run_ssh_command(
                    f"find {_f} -name '*.sh' | head -10"
                )
                if sh_files.strip():
                    for sf in sh_files.strip().split("\n")[:5]:
                        out = await forge_context.get_prefect_manager().run_ssh_command(
                            f"shellcheck {sf} 2>&1 | head -15"
                        )
                        results.append(f"[bold]shellcheck {sf} :[/]\n{out[:300] or '  ✅ OK'}")
            except RuntimeError:
                pass
            # JS/TS
            try:
                pkg = await forge_context.get_prefect_manager().run_ssh_command(
                    f"[ -f {_f}/package.json ] && echo yes || echo no"
                )
                if "yes" in pkg:
                    out = await forge_context.get_prefect_manager().run_ssh_command(
                        f"cd {_f} && npx eslint . --ext .js,.ts 2>&1 | head -30"
                    )
                    results.append(f"[bold]eslint :[/]\n{out[:400] or '  ✅ OK'}")
            except RuntimeError:
                pass
            chat.write("\n".join(results) if results else "[dim]Aucun linter trouvé[/]")

        asyncio.create_task(do_lint())

    # ── test ────────────────────────────────────────────────────────
    elif sub == "test" and len(parts) >= 2:
        folder = parts[1]
        chat.write(f"[dim]🧪 Tests dans [bold]{folder}[/]…[/]")

        async def do_test(_f=folder) -> None:
            """Do test.

            Args:
                _f: Description.
            """
            try:
                # Détecter l'outil
                ls = await forge_context.get_prefect_manager().run_ssh_command(f"ls {_f}/")
                if "pytest" in ls or "pyproject.toml" in ls or "setup.cfg" in ls:
                    out = await forge_context.get_prefect_manager().run_ssh_command(
                        f"cd {_f} && python -m pytest -v --tb=short 2>&1 | tail -40"
                    )
                    chat.write(f"[bold]pytest :[/]\n{out[:800]}")
                elif "package.json" in ls:
                    out = await forge_context.get_prefect_manager().run_ssh_command(
                        f"cd {_f} && npm test 2>&1 | tail -30"
                    )
                    chat.write(f"[bold]npm test :[/]\n{out[:600]}")
                elif "Makefile" in ls or "makefile" in ls:
                    out = await forge_context.get_prefect_manager().run_ssh_command(
                        f"cd {_f} && make test 2>&1 | tail -30"
                    )
                    chat.write(f"[bold]make test :[/]\n{out[:600]}")
                else:
                    chat.write("[yellow]⚠ Aucun outil de test détecté (pytest/npm/make)[/]")
            except RuntimeError as e:
                chat.write(f"[red]❌ Tests : {e}[/]")

        asyncio.create_task(do_test())

    # ── diff ────────────────────────────────────────────────────────
    elif sub == "diff" and len(parts) >= 2:
        folder = parts[1]
        chat.write(f"[dim]📋 Git diff [bold]{folder}[/]…[/]")

        async def do_diff(_f=folder) -> None:
            """Do diff.

            Args:
                _f: Description.
            """
            try:
                out = await forge_context.get_prefect_manager().run_ssh_command(f"cd {_f} && git log --oneline -5 2>&1")
                chat.write(f"[bold]5 derniers commits :[/]\n{out[:400]}")
                diff = await forge_context.get_prefect_manager().run_ssh_command(
                    f"cd {_f} && git diff HEAD~1 --stat 2>&1 | head -20"
                )
                chat.write(f"[bold]Diff HEAD~1 :[/]\n{diff[:600]}")
            except RuntimeError as e:
                chat.write(f"[red]❌ {e}[/]")

        asyncio.create_task(do_diff())

    # ── env ─────────────────────────────────────────────────────────
    elif sub == "env":
        chat.write("[dim]🔍 Infos runtime serveur…[/]")

        async def do_env() -> None:
            """Do env."""
            cmds = [
                ("Python", "python3 --version 2>&1 || python --version 2>&1"),
                ("Node", "node --version 2>&1"),
                ("npm", "npm --version 2>&1"),
                ("Docker", "docker --version 2>&1"),
                ("Git", "git --version 2>&1"),
                ("make", "make --version 2>&1 | head -1"),
                ("OS", "uname -a"),
                ("Disque", "df -h / | tail -1"),
                ("RAM", "free -h | grep Mem"),
            ]
            lines = []
            for label, cmd in cmds:
                try:
                    out = await forge_context.get_prefect_manager().run_ssh_command(cmd)
                    lines.append(f"  [bold]{label:8}[/] {out.strip()[:80]}")
                except RuntimeError:
                    lines.append(f"  [dim]{label:8} — indisponible[/]")
            chat.write("[bold]Environnement runtime :[/]\n" + "\n".join(lines))

        asyncio.create_task(do_env())

    else:
        chat.write(f"[yellow]⚠ Sous-commande '{sub}' inconnue.[/]  Tape [bold]@ci[/] pour l'aide.")


async def _handle_loop(app, args: str):
    """
    @loop [start|stop|status|merge|versions]
    Lance la boucle d'amélioration autonome (B1→B2→B3) sur un tronc séparé.
    """
    chat = app._chat_log()
    if not _g("HAS_LOOPS", False) or not _g("HAS_SANDBOX", False):
        missing = []
        if not _g("HAS_LOOPS", False):
            missing.append("forge_agents.py")
        if not _g("HAS_SANDBOX", False):
            missing.append("forge_code.py")
        chat.write(f"[red]❌ @loop indisponible — manquant : {', '.join(missing)}[/]")
        return

    sub = args.split()[0].lower() if args.split() else "start"

    if sub == "start":
        if hasattr(app, "_loop_task") and app._loop_task and not app._loop_task.done():
            chat.write("[yellow]⚠ Un loop est déjà en cours.[/]")
            return

        loop_id = _gvm_global().start_loop_trunk()
        chat.write(
            f"[bold #58a6ff]🔄 Loop {loop_id} démarré sur tronc séparé[/]\n"
            f"  Tronc : loop_trunk/loop_{loop_id}/\n"
            f"  Version départ : v{_gvm_global().current_version}"
        )

        # Auto-indexation avant de démarrer
        await app._index_self_in_rag()

        from nokido_agent.app.forge_code import ImprovementOrchestrator

        orchestrator = ImprovementOrchestrator(
            forge_context.get_settings().ollama_url,
            forge_context.get_settings().ollama_tags_url,
        )

        def log_fn(msg: str):
            """Log fn.

            Args:
                msg: Description.
            """
            try:
                app._chat_log().write(msg)
            except Exception:
                pass

        async def run_loop() -> None:
            """Run loop."""
            try:
                state = await orchestrator.run(
                    vm=_gvm_global(),
                    rag=_g_rag_ci(),
                    log_fn=log_fn,
                    on_done=lambda s: log_fn(
                        f"[green]✅ Loop terminé — "
                        f"{s.loop1_iterations + s.loop2_iterations + s.loop3_iterations}"
                        f" itérations[/]"
                    ),
                )
                # Indexer les résultats dans le RAG
                if _g_rag_ci():
                    summary = (
                        f"[LOOP {loop_id}] "
                        f"v{state.last_successful_version or '?'} "
                        f"— {len(state.iterations)} itérations "
                        f"— {state.total_failures} échecs"
                    )
                    await _g_rag_ci().add_session_message("improvement_loop", "loop_done", summary)
                # Versions du tronc loop
                versions = _gvm_global().list_loop_versions()
                if versions:
                    log_fn("[bold]Versions créées dans le tronc loop :[/]")
                    for v in versions:
                        log_fn(f"  v{v['version']} — {v['mtime'][:19]}")

                # ── Vérification post-loop automatique ────────────────
                await app._post_loop_safe_check(
                    loop_id=loop_id,
                    state=state,
                    log_fn=log_fn,
                )

            except Exception as e:
                import traceback

                tb = traceback.format_exc()
                log_fn(f"[red]❌ Loop erreur : {e}[/]")
                log_fn(f"[dim red]{tb[:600]}[/]")
                # Logger dans debug.log pour ne pas perdre l'erreur
                try:
                    _loop_log = Path(__file__).resolve().parent / "logs" / f"loop_error_{loop_id}.log"
                    _loop_log.parent.mkdir(exist_ok=True)
                    _loop_log.write_text(
                        f"Loop {loop_id} erreur\n{datetime.datetime.now().isoformat()}\n\n{tb}", encoding="utf-8"
                    )
                    log_fn(f"[dim]→ Traceback complet : logs/loop_error_{loop_id}.log[/]")
                except Exception:
                    pass
                _gvm_global().end_loop_trunk(merge=False)

        app._loop_task = asyncio.create_task(run_loop())

    elif sub == "stop":
        if hasattr(app, "_loop_task") and app._loop_task and not app._loop_task.done():
            app._loop_task.cancel()
            chat.write("[yellow]⚠ Loop interrompu.[/]")
        _gvm_global().end_loop_trunk(merge=False)
        chat.write("[dim]Tronc loop abandonné (aucune fusion).[/]")

    elif sub == "merge":
        # Checkpoint AVANT merge (Double Porte)
        save_orchestrator = _g("save_orchestrator", None)
        if save_orchestrator:
            _bk = save_orchestrator.create_checkpoint(label="pre_loop_merge")
            chat.write(f"  [dim]💾 Checkpoint : {_bk.name}[/dim]")
        _gvm_global().end_loop_trunk(merge=True)
        new_ver = _gvm_global().current_version
        if save_orchestrator:
            save_orchestrator.rotate_backups()
        chat.write(f"[green]✅ Tronc loop fusionné → workspace (v{new_ver})[/]")
        app._update_sidebar_title()

    elif sub == "versions":
        versions = _gvm_global().list_loop_versions()
        if versions:
            chat.write("[bold]Versions dans le tronc loop courant :[/]")
            for v in versions:
                chat.write(f"  v{v['version']} {v['mtime'][:19]} ({v['size']} octets)")
        else:
            chat.write("[dim]Aucun tronc loop actif.[/]")
        ws = _gvm_global().list_workspace_versions()
        chat.write("[bold]Workspace principal :[/]")
        for v in ws:
            cur = " ← [green]COURANT[/]" if v["current"] else ""
            chat.write(f"  v{v['version']} {v['mtime'][:19]}{cur}")

    elif sub == "status":
        if hasattr(app, "_loop_task") and app._loop_task and not app._loop_task.done():
            chat.write("[cyan]🔄 Loop en cours…[/]")
        else:
            chat.write("[dim]Aucun loop actif.[/]")
        chat.write(f"  Version courante : v{_gvm_global().current_version}")
        chat.write(f"  Fichier : {_gvm_global().work_path.name}")
        chat.write(f"  Tronc loop : {'actif' if _gvm_global()._loop_trunk else 'inactif'}")
    else:
        chat.write(
            "[bold]@loop[/] start|stop|merge|versions|status\n"
            "  start    — lance l'amélioration autonome (tronc séparé)\n"
            "  stop     — interrompt sans fusionner\n"
            "  merge    — fusionne la meilleure version dans workspace\n"
            "  versions — liste les versions du tronc courant\n"
            "  status   — état du loop"
        )


async def _handle_audit(app) -> None:
    """Handle audit.

    Args:
        app: Description.
    """
    chat = app._chat_log()
    try:
        from nokido_agent.app.forge_context import get_version_manager as _gvm_ci

        vm = _gvm_ci()
        if vm is None:
            chat.write("[yellow]⚠ version_manager non disponible[/]")
            return
        from nokido_agent.app.forge_ollama import ollama_stream as ollama_fn

        chat.write("[dim]⏳ Audit du code en cours…[/]")

        # ── 1. Auto-indexation RAG ────────────────────────────────────────
        chat.write("[dim]  📚 Indexation du code source dans le RAG…[/]")
        await app._index_self_in_rag()

        code = _gvm_global().get_current_code()
        reports = []

        # ── 2. Analyse statique ───────────────────────────────────────────
        for tool, args in [
            ("pylint", ["pylint", "--output-format=text", str(_gvm_global().work_path)]),
            ("black", ["black", "--check", str(_gvm_global().work_path)]),
            ("mypy", ["mypy", str(_gvm_global().work_path)]),
        ]:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                out = stdout.decode("utf-8", errors="replace")
                reports.append((tool, "Aucun problème détecté." if proc.returncode == 0 else out[:2000]))
            except FileNotFoundError:
                reports.append((tool, f"⚠️ {tool} non installé"))
            except asyncio.TimeoutError:
                reports.append((tool, f"⚠️ {tool} timeout"))

        # ── 3. Contexte RAG sur le code lui-même ─────────────────────────
        rag_ctx = ""
        if _g_rag_ci():
            try:
                docs = await _g_rag_ci().search("bugs erreurs architecture Python async await", k=4)
                rag_ctx = "\n".join(f"[{d.get('source', '')}] {d.get('content', '')[:300]}" for d in docs)
            except Exception:
                pass

        # ── 4. Prompt enrichi avec contexte RAG ───────────────────────────
        prompt = (
            "Tu es un expert Python/DevOps. Analyse ce code source et propose des améliorations.\n"
            "Pour chaque suggestion, utilise ce format EXACT :\n"
            "Suggestion N : Titre court\n"
            "TARGET: nom_de_la_fonction_ou_classe\n"
            "```python\n"
            "def nom_de_la_fonction_ou_classe(...):  # code complet\n"
            "    ...\n"
            "```\n\n"
            "Règle : TARGET doit être le nom EXACT d'une fonction ou classe existante.\n"
            "Ne fournis que la fonction/classe modifiée, pas le fichier entier.\n\n"
        )
        if rag_ctx:
            prompt += f"Contexte base de connaissances :\n{rag_ctx}\n\n"
        prompt += "Rapports d'analyse statique :\n"
        for tool, rep in reports:
            prompt += f"--- {tool} ---\n{rep}\n\n"
        prompt += f"Code source (v{_gvm_global().current_version}) :\n```python\n{code[:8000]}\n```\n"

        app._set_status("[cyan]🤖 Analyse en cours…[/]")
        try:
            reply = await ollama_fn(
                app.model_chat,
                [{"role": "user", "content": prompt}],
                lambda _: None,
                lambda: None,
            )
        except Exception as e:
            chat.write(f"[red]❌ Erreur IA : {e}[/]")
            app._set_status("")
            return

        # Anti-pourrissement : rapport MemoryJanitor
        if (
            __import__("forge_agentic").get_agentic_engine()
            if hasattr(__import__("forge_agentic"), "get_agentic_engine")
            else None
        ):
            try:
                chat.write(
                    (
                        __import__("forge_agentic").get_agentic_engine()
                        if hasattr(__import__("forge_agentic"), "get_agentic_engine")
                        else None
                    ).audit_report()
                )
                _gauge = app.query_one("#entropy-gauge", EntropyGauge)
                _gauge.refresh_entropy(
                    (
                        __import__("forge_agentic").get_agentic_engine()
                        if hasattr(__import__("forge_agentic"), "get_agentic_engine")
                        else None
                    ).entropy_level(),
                    (
                        __import__("forge_agentic").get_agentic_engine()
                        if hasattr(__import__("forge_agentic"), "get_agentic_engine")
                        else None
                    ).entropy_color(),
                )
            except Exception:
                pass
        chat.write(f"[bold #58a6ff]Rapport d'audit v{_gvm_global().current_version} :[/]")
        chat.write(reply)

        # ── 5. Indexer le rapport dans le RAG ─────────────────────────────
        if _g_rag_ci():
            try:
                await _g_rag_ci().add_session_message(
                    "audit_results", "audit", f"[AUDIT v{_gvm_global().current_version}]\n{reply[:3000]}"
                )
            except Exception:
                pass

        # ── 6. Parser les suggestions ─────────────────────────────────────
        app.last_audit_suggestions = []
        pattern = r"Suggestion\s+(\d+)\s*:\s*(.*?)(?:\nTARGET:\s*(\S+))?\n```python\n(.*?)\n```"
        for num, desc, target, code_block in re.findall(pattern, reply, re.DOTALL | re.IGNORECASE):
            app.last_audit_suggestions.append(
                {
                    "num": int(num),
                    "description": desc.strip(),
                    "target": target.strip() if target else "",
                    "code": code_block.strip(),
                }
            )

        if app.last_audit_suggestions:
            chat.write("[bold]Suggestions disponibles :[/]")
            for sugg in app.last_audit_suggestions:
                chat.write(f"  {sugg['num']}. {sugg['description'][:80]}")
            chat.write(
                "[dim]→ Tape le numéro de la suggestion (ex: 1, 2) ou [bold]t[/] pour tout appliquer · @loop pour auto-amélioration[/]"
            )
        else:
            chat.write("[dim]Aucune suggestion exploitable trouvée.[/]")

        app._set_status("")

    except Exception as _e:
        chat.write(
            f"[bold red]❌ @audit ({type(_e).__name__}) :[/]\n"
            f"[red]{escape(str(_e))}[/]\n"
            f"[dim]{escape(traceback.format_exc()[-600:])}[/]"
        )
        try:
            app._set_status("")
        except Exception:
            pass
