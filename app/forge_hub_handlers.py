from __future__ import annotations

# Imports oublies, mesures le 2026-09-08 : asyncio.create_task L781,
# datetime.now() L774 (la CLASSE, pas le module), uuid.UUID L419.
import asyncio
import uuid
from datetime import datetime

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_164743_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns/Raises
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_hub_handlers.py — Handlers Nokido connectés au Hub v17
==============================================================
Extrait de Nokido.py pour allègement du monolithe.
Contient les handlers @ci remote, @workflow hub/gh, et les hooks TUI.

Utilisé par Nokido.py :
  from forge_hub_handlers import handle_ci_remote, handle_workflow_hub
  from forge_hub_handlers import tui_auto_patch
"""

from pathlib import Path as _Path

_ROOT_P = _Path(__file__).resolve().parent.parent
_APP_DIR = _ROOT_P / "app"
_DATA_DIR = _ROOT_P / "data"
_LOGS_DIR = _ROOT_P / "logs"

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# =============================================================================
# @ci remote — dispatch vers Woodpecker/Codeberg/GitHub
# =============================================================================


async def handle_ci_remote(app, parts: list) -> None:
    """
    @ci remote [nr|lint|full|status]
    Délègue au Core → dispatch_task() → Woodpecker > Codeberg > GitHub
    """
    try:
        from nokido_agent.app.nokido_core import get_core

        core = get_core()
        chat = app._chat_log()
        action = parts[1].lower() if len(parts) > 1 else "nr"

        if action == "status":
            from nokido_agent.app.forge_hub_client import hub as _hub

            r = _hub.github("actions") if _hub.alive() else "Hub non disponible"
            chat.write("[bold #58a6ff]@ci remote status[/]:\n" + str(r))
            return

        # Mapping action → event
        event_map = {
            "lint": "run_lint",
            "full": "run_full_check",
        }
        task = event_map.get(action, "run-tests")

        r = core.dispatch_task(task, target="remote", payload={"selector": action})

        backend = r.get("backend", "?")
        icon = "✅" if r.get("ok") else "❌"

        chat.write(
            icon
            + " [bold]Dispatch "
            + backend
            + "[/]\n"
            + "  Event    : "
            + str(r.get("event", r.get("workflow", "?")))
            + "\n"
            + "  Selector : "
            + action
            + "\n"
            + "  Suivi    : @ci remote status"
        )

    except Exception as e:
        app._chat_log().write("[red]❌ @ci remote: " + str(e) + "[/]")


# =============================================================================
# @workflow hub — statut Hub + Core
# =============================================================================


async def handle_workflow_hub(app) -> None:
    """@workflow hub  affiche le statut complet Hub + Core."""
    try:
        chat = app._chat_log()
        from nokido_agent.app.forge_hub_client import hub as _hub
        from nokido_agent.app.nokido_core import get_core

        # Status Hub
        hub_report = _hub.status_report()
        chat.write(hub_report)

        # Status Core
        core = get_core()
        status = core.status()
        chat.write(
            "[bold #58a6ff]Core v17[/]\n"
            f"  Mode  : {status['collab_mode']}\n"
            f"  Ring  : {status['active_ring']}\n"
            f"  AUTO  : {core.is_auto_mode()}\n"
            f"  RAG   : {status.get('rag', {}).get('total', '?')} chunks"
        )

    except Exception as e:
        app._chat_log().write(f"[red] @workflow hub: {e}[/]")


# =============================================================================
# Mode AUTO — enchaîner apply_smart_patch sans confirmation
# =============================================================================


async def tui_auto_patch(app, file: str, old: str, new: str) -> dict:
    """
    Applique un patch via apply_smart_patch.
    En mode AUTO : exécute sans demander confirmation.
    En mode normal : demande confirmation à l'utilisateur.
    """
    from nokido_agent.app.nokido_core import get_core, apply_smart_patch

    core = get_core()
    chat = app._chat_log()

    if not core.is_auto_mode():
        # Mode normal — dry_run d'abord, demander confirmation
        r_dry = apply_smart_patch(file, old, new, dry_run=True)
        if not r_dry.get("ok"):
            chat.write("[red]❌ Patch impossible: " + r_dry.get("error", "?") + "[/]")
            return r_dry
        chat.write(
            "[yellow]⚠ Patch proposé sur[/] "
            + file
            + "\n"
            + "[dim]Mode AUTO désactivé — confirme avec 't' ou active AUTO dans la TUI[/]"
        )
        return {"ok": False, "reason": "awaiting_confirmation", "file": file}

    # Mode AUTO — patch direct
    r = apply_smart_patch(file, old, new)
    if r.get("ok"):
        core.tui_notify("Patch appliqué: " + file + " L" + str(r.get("line", "?")), type="success")
        chat.write("[green]✅ Patch AUTO[/] " + file + " L" + str(r.get("line", "?")))
    else:
        core.tui_notify("Patch échoué: " + r.get("error", "?"), type="error")
        chat.write("[red]❌ Patch AUTO échoué: " + r.get("error", "?") + "[/]")
    return r


# =============================================================================
# Hub notifications poller — à appeler via set_interval dans la TUI
# =============================================================================


async def hub_notification_poll(app) -> None:
    """
    Polls tui_notifications + tui_commands depuis le Hub.
    À enregistrer : self.set_interval(2.0, hub_notification_poll)
    """
    from nokido_agent.app.forge_events import poll_tui_notifications

    await poll_tui_notifications(app)

    # Traiter les commandes TUI entrantes
    try:
        from nokido_agent.app.nokido_core import get_core

        core = get_core()
        cmd = core.get_tui_command(consume=True)
        if cmd and not cmd.get("error"):
            command = cmd.get("command", "")
            payload = cmd.get("payload", {})

            # Routing des commandes
            if command == "test":
                selector = payload.get("selector", "nr")
                from nokido_agent.app.forge_hub_client import hub as _hub

                if _hub.alive():
                    _hub.tool("run", {"action": "test_nr", "code": selector})
                    app._chat_log().write("[dim]🤖 Hub:[/] Tests NR lancés (selector=" + selector + ")")
            elif command == "hub_restart":
                app._chat_log().write("[yellow]⚠ Hub restart demandé...[/]")
            elif command == "auto_mode":
                level = int(payload.get("level", 0))
                core.set_auto_mode(level >= 3)
    except Exception:
        pass


# =============================================================================
# @workflow — extrait de Nokido.py via apply_smart_patch
# =============================================================================
async def handle_workflow(app, args: str):
    """
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
    from nokido_agent.app import forge_context
    from nokido_agent.app.forge_prefect import HAS_PREFECT, get_client

    prefect_manager = forge_context.get_prefect_manager()
    chat = app._chat_log()
    parts = args.split()
    sub = parts[0].lower() if parts else ""

    # ── Hub GitHub Actions workflows ─────────────────────────────
    if sub == "gh":
        # @workflow gh [list|run <wf.yml> [branch]]
        try:
            from nokido_agent.app.forge_hub_client import hub as _hub

            if not _hub.alive():
                chat.write("[yellow]⚠ Hub v17 non disponible[/]")
                return
            action = parts[1].lower() if len(parts) > 1 else "list"
            if action in ("list", "actions"):
                r = _hub.github("actions")
                chat.write("[bold #58a6ff]@workflow gh[/] — GitHub Actions:\n" + str(r))
            elif action == "run" and len(parts) > 2:
                wf = parts[2]
                ref = parts[3] if len(parts) > 3 else "alpha"
                r = _hub.trigger_action(wf, ref)
                chat.write("[green]✅ Workflow déclenché:[/] " + str(r))
            else:
                chat.write(
                    "[bold #58a6ff]@workflow gh[/]\n"
                    "  [bold]list[/]                  derniers runs GitHub Actions\n"
                    "  [bold]run[/] [dim]<wf.yml> [branch][/]  déclencher un workflow"
                )
        except Exception as e:
            chat.write("[red]❌ Hub erreur: " + str(e) + "[/]")
        return

    if sub == "hub":
        # Délégué à forge_hub_handlers
        from nokido_agent.app.forge_hub_handlers import handle_workflow_hub as _hwh

        await _hwh(app)
        return

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
        local = prefect_manager.workflow_list()
        if local:
            chat.write("[bold]Workflows locaux :[/]")
            for wf in local:
                steps = prefect_manager._custom_workflows[wf]
                chat.write(f"  [bold #3fb950]{wf}[/] [dim]({len(steps)} étapes)[/]")
        else:
            chat.write("[dim]Aucun workflow local. Crée-en un avec @workflow add …[/]")
        if HAS_PREFECT and prefect_manager.client:
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
        if wf_name not in prefect_manager._custom_workflows:
            known = prefect_manager.workflow_list()
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
                result = await prefect_manager.run_workflow(_n, on_step=_step)
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
        prefect_manager._custom_workflows[wf_name] = steps
        chat.write(f"[green]✅ Workflow [bold]{wf_name}[/] enregistré — {len(steps)} étape(s) :[/]")
        for i, s in enumerate(steps, 1):
            chat.write(f"  [dim]{i}.[/] {s}")

    # ── del ─────────────────────────────────────────────────────────
    elif sub == "del" and len(parts) >= 2:
        wf_name = parts[1]
        if wf_name in prefect_manager._custom_workflows:
            del prefect_manager._custom_workflows[wf_name]
            chat.write(f"[green]✅ Workflow '{wf_name}' supprimé.[/]")
        else:
            chat.write(f"[yellow]⚠ '{wf_name}' introuvable.[/]")

    # ── show ────────────────────────────────────────────────────────
    elif sub == "show" and len(parts) >= 2:
        wf_name = parts[1]
        steps = prefect_manager._custom_workflows.get(wf_name)
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
                result = await prefect_manager.deploy(_svc, _strat, on_step=_step)
                chat.write(result)
            except Exception as e:
                chat.write(f"[red]❌ Déploiement: {e}[/]")

        asyncio.create_task(do_deploy())

    # ── history ─────────────────────────────────────────────────────
    elif sub == "history":
        hist = prefect_manager.pipeline_history(15)
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
        if not (HAS_PREFECT and prefect_manager.client):
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
        if not (HAS_PREFECT and prefect_manager.client):
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


# =============================================================================
# @ci — extrait de Nokido.py via apply_smart_patch
# =============================================================================
async def handle_ci(app, args: str):
    """
    @ci                          — aide
    @ci run <repo> [branche]     — lancer un pipeline CI complet
    @ci run <repo> [b] [dir]     — avec répertoire de travail custom
    @ci status                   — derniers pipelines (historique)
    @ci lint <dossier>           — analyse statique SSH (flake8/eslint/shellcheck)
    @ci test <dossier>           — tests uniquement (pytest/npm test)
    @ci diff <repo>              — git diff résumé du dernier commit
    @ci env                      — infos runtime sur le serveur (python/node/docker)
    """
    from nokido_agent.app import forge_context

    prefect_manager = forge_context.get_prefect_manager()
    chat = app._chat_log()
    parts = args.split()
    sub = parts[0].lower() if parts else ""

    # ── Hub GitHub Actions + Remote Dispatch ────────────────────
    if sub == "gh":
        # @ci gh <workflow.yml> [branch]
        try:
            from nokido_agent.app.forge_hub_client import hub as _hub

            if not _hub.alive():
                chat.write("[yellow]⚠ Hub v17 non disponible — @ci gh requiert le Hub[/]")
                return
            wf = parts[1] if len(parts) > 1 else ""
            ref = parts[2] if len(parts) > 2 else "alpha"
            if not wf:
                r = _hub.github("actions")
                chat.write("[bold #58a6ff]@ci gh[/] — derniers runs:\n" + str(r))
                return
            r = _hub.trigger_action(wf, ref)
            chat.write("[green]✅ Action GitHub déclenchée:[/] " + str(r))
        except Exception as e:
            chat.write("[red]❌ Hub erreur: " + str(e) + "[/]")
        return

    if sub == "remote":
        # Délégué à forge_hub_handlers — dispatch Woodpecker/Codeberg/GitHub
        from nokido_agent.app.forge_hub_handlers import handle_ci_remote as _hcr

        await _hcr(app, parts)
        return

    if not sub:
        chat.write(
            "[bold #58a6ff]@ci[/] — sous-commandes :\n"
            "  [bold]run[/] [dim]<repo_url> [branche] [workdir][/]  pipeline complet\n"
            "  [bold]status[/]                              historique\n"
            "  [bold]lint[/] [dim]<dossier>[/]                       analyse statique\n"
            "  [bold]test[/] [dim]<dossier>[/]                       tests uniquement\n"
            "  [bold]diff[/] [dim]<dossier>[/]                       git diff dernier commit\n"
            "  [bold]env[/]                                 infos runtime serveur\n"
            "  [bold]gh[/] [dim]<workflow.yml> [branch][/]           GitHub Action via Hub v17\n"
            "  [bold]remote[/] [dim][nr|lint|full|status][/]         Tests NR sur GitHub Actions"
        )
        return

    # ── run ─────────────────────────────────────────────────────────
    elif sub == "run" and len(parts) >= 2:
        repo = parts[1]
        branch = parts[2] if len(parts) >= 3 else "main"
        workdir = parts[3] if len(parts) >= 4 else "/tmp/ci-repo"
        chat.write(f"[dim]🚀 Pipeline CI : [bold]{repo}[/] @ [bold]{branch}[/]  → {workdir}[/]")
        # do_ci — voir forge_handler_ci.py
        asyncio.create_task(do_ci())

    # ── status ──────────────────────────────────────────────────────
    elif sub == "status":
        hist = prefect_manager.pipeline_history(10)
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
            from nokido_agent.app.forge_app_context import app_ctx as _actx

            _ac = _actx()
            prefect_manager = _ac.prefect_manager
            results = []
            # Python
            try:
                out = await prefect_manager.run_ssh_command(
                    f"cd {_f} && python -m flake8 --max-line-length=120 --statistics . 2>&1 | head -40"
                )
                results.append(f"[bold]flake8 :[/]\n{out[:600] or '  ✅ Aucun problème'}")
            except RuntimeError as e:
                results.append(f"[dim]flake8 : {str(e)[:100]}[/]")
            # Shell
            try:
                sh_files = await prefect_manager.run_ssh_command(f"find {_f} -name '*.sh' | head -10")
                if sh_files.strip():
                    for sf in sh_files.strip().split("\n")[:5]:
                        out = await prefect_manager.run_ssh_command(f"shellcheck {sf} 2>&1 | head -15")
                        results.append(f"[bold]shellcheck {sf} :[/]\n{out[:300] or '  ✅ OK'}")
            except RuntimeError:
                pass
            # JS/TS
            try:
                pkg = await prefect_manager.run_ssh_command(f"[ -f {_f}/package.json ] && echo yes || echo no")
                if "yes" in pkg:
                    out = await prefect_manager.run_ssh_command(
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
                ls = await prefect_manager.run_ssh_command(f"ls {_f}/")
                if "pytest" in ls or "pyproject.toml" in ls or "setup.cfg" in ls:
                    out = await prefect_manager.run_ssh_command(
                        f"cd {_f} && python -m pytest -v --tb=short 2>&1 | tail -40"
                    )
                    chat.write(f"[bold]pytest :[/]\n{out[:800]}")
                elif "package.json" in ls:
                    out = await prefect_manager.run_ssh_command(f"cd {_f} && npm test 2>&1 | tail -30")
                    chat.write(f"[bold]npm test :[/]\n{out[:600]}")
                elif "Makefile" in ls or "makefile" in ls:
                    out = await prefect_manager.run_ssh_command(f"cd {_f} && make test 2>&1 | tail -30")
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
                out = await prefect_manager.run_ssh_command(f"cd {_f} && git log --oneline -5 2>&1")
                chat.write(f"[bold]5 derniers commits :[/]\n{out[:400]}")
                diff = await prefect_manager.run_ssh_command(f"cd {_f} && git diff HEAD~1 --stat 2>&1 | head -20")
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
                    out = await prefect_manager.run_ssh_command(cmd)
                    lines.append(f"  [bold]{label:8}[/] {out.strip()[:80]}")
                except RuntimeError:
                    lines.append(f"  [dim]{label:8} — indisponible[/]")
            chat.write("[bold]Environnement runtime :[/]\n" + "\n".join(lines))

        asyncio.create_task(do_env())

    else:
        chat.write(f"[yellow]⚠ Sous-commande '{sub}' inconnue.[/]  Tape [bold]@ci[/] pour l'aide.")


# =============================================================================
# @loop — extrait de Nokido.py via apply_smart_patch
# =============================================================================
async def handle_loop(app, args: str):
    """
    @loop [start|stop|status|merge|versions]
    Lance la boucle d'amélioration autonome (B1→B2→B3) sur un tronc séparé.
    """
    from app.core.settings import get_app_attr as _ga
    from nokido_agent.app.forge_app_context import app_ctx as _actx

    _ac = _actx()
    version_manager = _ac.version_manager
    rag_engine = _ac.rag_engine
    settings = _ac.settings
    save_orchestrator = _ga("save_orchestrator", None)

    HAS_LOOPS = _ga("HAS_LOOPS", False)
    HAS_SANDBOX = _ga("HAS_SANDBOX", False)
    chat = app._chat_log()
    if not HAS_LOOPS or not HAS_SANDBOX:
        missing = []
        if not HAS_LOOPS:
            missing.append("forge_agents.py")
        if not HAS_SANDBOX:
            missing.append("forge_code.py")
        chat.write(f"[red]❌ @loop indisponible — manquant : {', '.join(missing)}[/]")
        return

    sub = args.split()[0].lower() if args.split() else "start"

    if sub == "start":
        if hasattr(app, "_loop_task") and app._loop_task and not app._loop_task.done():
            chat.write("[yellow]⚠ Un loop est déjà en cours.[/]")
            return

        # ── Fichiers cibles ───────────────────────────────────────
        _loop_args = args.split()[1:]  # mots après "start"
        _target_files = []
        for _f in _loop_args:
            _fp = _APP_DIR / _f
            if _fp.exists():
                _target_files.append(_fp)
            else:
                chat.write(f"[yellow]⚠ {_f} introuvable[/]")
        if not _target_files:
            _target_files = [version_manager.work_path]

        loop_id = version_manager.start_loop_trunk()
        _file_list = ", ".join(f.name for f in _target_files)
        chat.write(
            f"[bold #58a6ff]🔄 Loop {loop_id} démarré[/]\n"
            f"  Fichiers : {_file_list}\n"
            f"  Tronc : loop_trunk/loop_{loop_id}/\n"
            f"  Version départ : v{version_manager.current_version}"
        )

        # Auto-indexation avant de démarrer
        await app._index_self_in_rag()

        from nokido_agent.app.forge_code import ImprovementOrchestrator

        orchestrator = ImprovementOrchestrator(
            settings.ollama_url,
            settings.ollama_tags_url,
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
                    vm=version_manager,
                    rag=rag_engine,
                    log_fn=log_fn,
                    on_done=lambda s: log_fn(
                        f"[green]✅ Loop terminé — "
                        f"{s.loop1_iterations + s.loop2_iterations + s.loop3_iterations}"
                        f" itérations[/]"
                    ),
                    target_files=_target_files if len(_target_files) > 1 else None,
                )
                # Indexer les résultats dans le RAG
                if rag_engine:
                    summary = (
                        f"[LOOP {loop_id}] "
                        f"v{state.last_successful_version or '?'} "
                        f"— {len(state.iterations)} itérations "
                        f"— {state.total_failures} échecs"
                    )
                    await rag_engine.add_session_message("improvement_loop", "loop_done", summary)
                # Versions du tronc loop
                versions = version_manager.list_loop_versions()
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
                        f"Loop {loop_id} erreur\n{datetime.now().isoformat()}\n\n{tb}", encoding="utf-8"
                    )
                    log_fn(f"[dim]→ Traceback complet : logs/loop_error_{loop_id}.log[/]")
                except Exception:
                    pass
                version_manager.end_loop_trunk(merge=False)

        app._loop_task = asyncio.create_task(run_loop())

    elif sub == "stop":
        if hasattr(app, "_loop_task") and app._loop_task and not app._loop_task.done():
            app._loop_task.cancel()
            chat.write("[yellow]⚠ Loop interrompu.[/]")
        version_manager.end_loop_trunk(merge=False)
        chat.write("[dim]Tronc loop abandonné (aucune fusion).[/]")

    elif sub == "merge":
        # Checkpoint AVANT merge (Double Porte)
        if save_orchestrator:
            _bk = save_orchestrator.create_checkpoint(label="pre_loop_merge")
            chat.write(f"  [dim]💾 Checkpoint : {_bk.name}[/dim]")
        version_manager.end_loop_trunk(merge=True)
        new_ver = version_manager.current_version
        if save_orchestrator:
            save_orchestrator.rotate_backups()
        chat.write(f"[green]✅ Tronc loop fusionné → workspace (v{new_ver})[/]")
        app._update_sidebar_title()

    elif sub == "versions":
        versions = version_manager.list_loop_versions()
        if versions:
            chat.write("[bold]Versions dans le tronc loop courant :[/]")
            for v in versions:
                chat.write(f"  v{v['version']} {v['mtime'][:19]} ({v['size']} octets)")
        else:
            chat.write("[dim]Aucun tronc loop actif.[/]")
        ws = version_manager.list_workspace_versions()
        chat.write("[bold]Workspace principal :[/]")
        for v in ws:
            cur = " ← [green]COURANT[/]" if v["current"] else ""
            chat.write(f"  v{v['version']} {v['mtime'][:19]}{cur}")

    elif sub == "status":
        if hasattr(app, "_loop_task") and app._loop_task and not app._loop_task.done():
            chat.write("[cyan]🔄 Loop en cours…[/]")
        else:
            chat.write("[dim]Aucun loop actif.[/]")
        chat.write(f"  Version courante : v{version_manager.current_version}")
        chat.write(f"  Fichier : {version_manager.work_path.name}")
        chat.write(f"  Tronc loop : {'actif' if version_manager._loop_trunk else 'inactif'}")
    else:
        chat.write(
            "[bold]@loop[/] start|stop|merge|versions|status\n"
            "  start    — lance l'amélioration autonome (tronc séparé)\n"
            "  stop     — interrompt sans fusionner\n"
            "  merge    — fusionne la meilleure version dans workspace\n"
            "  versions — liste les versions du tronc courant\n"
            "  status   — état du loop"
        )
