"""Fournit a la TUI Nokido des handlers @commande, le routage des requetes et l'arret.

Definit _handle_mode, _handle_role, _handle_mem, _check_ollama_models,
process_user_input, run_collaboration, run_comite, get_remote_context, on_unmount,
do_scan, do_scan_basic ; re-exporte _handle_proxy, _handle_loop, _handle_audit,
handle_evolve... depuis forge_handler_*. Chaque handler recoit l'app en argument.
Effets : appels Ollama (ollama_parallel, ollama_call, GET ollama_tags_url) ;
on_unmount tue les processus enfants (taskkill ou SIGTERM). Appele par Nokido.py,
forge_core_models.py, forge_commands.py. Attention : _handle_rag y est un stub vide,
et des noms utilises (chat, agents, debug_log) ne sont pas definis ici.
"""
from __future__ import annotations

# Imports oublies, mesures le 2026-09-08 : chacun etait une NameError qui
# attendait que son chemin soit emprunte (datetime.now() L174, sys.platform
# L1088, time.monotonic() L858). `from datetime import datetime` et non
# `import datetime` : le code appelle la CLASSE.
import sys
import time
from datetime import datetime

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_165156_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns/Raises
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_handlers.py — Handlers @cmd extraits de Nokido.py (v16.5)
=================================================================
Code source récupéré depuis workspace/Nokido_v13.6.py.
Chaque fonction reçoit `app` à la place de `self`.
_g(name) résout les globals Nokido sans import circulaire.
"""
import asyncio
import gc

try:
    import aiohttp
except ImportError:
    aiohttp = None
import os
import re
import traceback as _traceback
from pathlib import Path
from typing import Optional, Tuple
from rich.markup import escape
from nokido_agent.app.forge_logging import debug_log

try:
    import asyncssh
except ImportError:
    asyncssh = None


from app.core.settings import get_app_attr as _g  # noqa: F401

from nokido_agent.app import forge_context as _forge_ctx  # singleton rag_engine
from nokido_agent.app import forge_context  # acces direct forge_context.xxx
from app.forge_llm import ollama_parallel
from app.forge_network import NetworkDiscovery
from app.forge_ollama import ollama_call
from app.forge_startup import auto_select_models
from app.forge_startup import save_last_assignment


def _g_rag():
    """g rag."""
    return _forge_ctx.rag_engine


from nokido_agent.app.forge_context import get_version_manager as _gvm_global  # remplace _g_rag()


logger = __import__("logging").getLogger("Nokido.Handlers")


# ─────────────────────────────────────────────────────────────────────────────
# HANDLERS
# ─────────────────────────────────────────────────────────────────────────────


# ─── Network Handlers ────────────────────────────────────────────────────────
from nokido_agent.app.forge_handler_network import _handle_proxy  # noqa: F401

# ─── RAG & Knowledge Handlers ────────────────────────────────────────────────
from nokido_agent.app.forge_handler_rag import _handle_rag, _validate_suggestion_async  # noqa: F401

# ─── CI/CD & Audit Handlers ──────────────────────────────────────────────────
from nokido_agent.app.forge_handler_ci import (  # noqa: F401
    _handle_workflow,
    _handle_loop,
    _handle_audit,
    # _handle_estim,
)

# ─── Evolve & Evolution Handlers ─────────────────────────────────────────────
from nokido_agent.app.forge_handler_evolve import handle_evolve  # noqa: F401


async def _handle_loop(app: object, args: str) -> None:
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

        orchestrator = ImprovementOrchestrator(
            forge_context.get_settings().ollama_url,
            forge_context.get_settings().ollama_tags_url,
        )

        def log_fn(msg: str) -> None:
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
                    rag=_g_rag(),
                    log_fn=log_fn,
                    on_done=lambda s: log_fn(
                        f"[green]✅ Loop terminé — "
                        f"{s.loop1_iterations + s.loop2_iterations + s.loop3_iterations}"
                        f" itérations[/]"
                    ),
                )
                # Indexer les résultats dans le RAG
                if _g_rag():
                    summary = (
                        f"[LOOP {loop_id}] "
                        f"v{state.last_successful_version or '?'} "
                        f"— {len(state.iterations)} itérations "
                        f"— {state.total_failures} échecs"
                    )
                    await _g_rag().add_session_message("improvement_loop", "loop_done", summary)
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
                        f"Loop {loop_id} erreur\n{datetime.now().isoformat()}\n\n{tb}", encoding="utf-8"
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


async def _handle_mode(app: object, args: str) -> None:
    """
    @mode [autonome|collaboration|comite] [set] <tâche>
    Câblage vers run_collab() selon le mode TUI :
      autonome      -> auto   (Nokido pilote seule)
      collaboration -> cline  (Claude+CLINE_PLAN+CLINE_ACT, prompt partagé)
      comite        -> debat  (tous proposent, Nokido vote)
    """
    chat = app._chat_log()
    parts = args.split(maxsplit=1)
    MODES = ("autonome", "collaboration", "comite")
    ICONS = {"autonome": "🤖", "collaboration": "🤝", "comite": "⚖️"}
    DESCS = {
        "autonome": "Nokido pilote — Ollama exécute",
        "collaboration": "Claude + Cline PLAN/ACT + Ollama — prompt partagé",
        "comite": "Tous proposent — Nokido vote et tranche",
    }
    MODE_MAP = {
        "autonome": ("auto", {}),
        "collaboration": ("cline", {"timeout": 180}),
        "comite": ("debat", {"rounds": 2}),
    }
    COLORS = {"autonome": "#58a6ff", "collaboration": "#3fb950", "comite": "#d2a8ff"}

    # ── Afficher mode actuel ─────────────────────────────────────
    if not parts or parts[0].lower() in ("", "status"):
        m = getattr(app, "_collab_mode", "autonome")
        chat.write(
            "[bold]Mode actuel :[/] " + ICONS.get(m, "?") + " [bold]" + m + "[/]\n"
            "  " + DESCS.get(m, "") + "\n\n"
            "[bold #8b949e]Modes disponibles :[/]\n"
            "  🤖 [bold]autonome[/]      — @mode autonome <tâche>\n"
            "  🤝 [bold]collaboration[/] — @mode collaboration <tâche>\n"
            "  ⚖️  [bold]comite[/]        — @mode comite <tâche>\n"
            "[dim]  @mode set <mode> — changer le mode par défaut[/]"
        )
        return

    # ── set — changer le mode par défaut ─────────────────────────
    if parts[0].lower() == "set" and len(parts) > 1:
        m = parts[1].strip().lower()
        if m in MODES:
            app._collab_mode = m
            try:
                app._update_mode_buttons()
            except Exception:
                pass
            chat.write("[green]✅ Mode → " + ICONS.get(m, "") + " [bold]" + m + "[/][/]")
        else:
            chat.write("[red]❌ Mode inconnu : " + m + "  (autonome | collaboration | comite)[/]")
        return

    # ── Extraire mode + tâche ─────────────────────────────────────
    first = parts[0].lower()
    if first in MODES:
        mode = first
        task = parts[1].strip() if len(parts) > 1 else ""
    else:
        mode = getattr(app, "_collab_mode", "autonome")
        task = args.strip()

    if not task:
        chat.write("[red]❌ Tâche manquante. Ex : @mode " + mode + " configurer AdGuard[/]")
        return

    collab_sub, collab_opts = MODE_MAP[mode]
    color = COLORS[mode]
    icon = ICONS[mode]
    chat.write("[bold " + color + "]" + icon + " Mode " + mode.capitalize() + "[/] → " + escape(task))
    app._set_status("[" + color + "]" + icon + " " + mode.capitalize() + "…[/]")

    async def _run_mode() -> None:
        """Run mode."""
        try:
            from nokido_agent.app.forge_collab_modes import run_collab

            await run_collab(chat, collab_sub, task, collab_opts)
        except Exception as _e:
            import traceback as _tb

            chat.write(
                "[bold red]❌ Mode " + mode + " erreur :[/]\n"
                "[red]" + escape(str(_e)) + "[/]\n"
                "[dim]" + escape(_tb.format_exc()[-600:]) + "[/]"
            )
        finally:
            app._set_status("")

    import asyncio as _aio

    _aio.create_task(_run_mode())


async def _handle_role(app: object, args: str) -> None:
    """
    @role [list|assign|detect <texte>|score]
    Gère l'assignation des rôles aux modèles via le scorer intégré.
    """
    chat = app._chat_log()
    try:  # comme le monolithe : forge_agents absent => HAS_LOOPS faux
        from nokido_agent.app.forge_agents import (
            AgentRole as OpsAgentRole,
            IntentRouter,
            ROLE_META,
            RoleOrchestrator,
        )
    except ImportError:
        OpsAgentRole = IntentRouter = RoleOrchestrator = None
        ROLE_META = {}

    # ── Mode scorer natif (scoring.py) ────────────────────────────────
    if app.scorer and _g("HAS_SCORING", False):
        parts = args.split(maxsplit=1)
        sub = parts[0].lower() if parts else "list"

        if sub == "list" or sub == "score":
            arch_hint = f"  Cible : {app.arch.summary()}" if app.arch else ""
            chat.write(app.scorer.report(app.arch))
            if arch_hint:
                chat.write(f"[dim]{arch_hint}[/]")
            return

        elif sub == "assign":
            chat.write("[dim]⏳ Re-scoring et assignation des rôles…[/]")
            try:
                await app.scorer.refresh(bench=True)
                selected = await auto_select_models(app.scorer, app.arch)
                app.model_chat = selected["chat"]
                app.model_action = selected["action"]
                app.model_rag = selected["rag"]
                app._update_sidebar_title()
                save_last_assignment(app.model_chat, app.model_action, app.model_rag)
                chat.write(
                    f"[green]✅ Modèles ré-assignés et sauvegardés :[/]\n"
                    f"  💬 Chat   → {app.model_chat}\n"
                    f"  ⚡ Action → {app.model_action}\n"
                    f"  🗄 RAG    → {app.model_rag}"
                )
            except Exception as e:
                chat.write(f"[red]❌ Erreur scoring : {e}[/]")
            return

        elif sub == "arch":
            chat.write("[dim]⏳ Re-détection de l'architecture…[/]")
            try:
                app.arch = await app.scorer.get_arch(force=True)
                if app.arch:
                    chat.write(f"[green]✅ Architecture :[/] {app.arch.summary()}")
                    chat.write(f"[dim]{app.arch.context_hint()}[/]")
                else:
                    chat.write("[yellow]⚠ Impossible de détecter l'architecture[/]")
            except Exception as e:
                chat.write(f"[red]❌ {e}[/]")
            return

        elif sub == "detect" and len(parts) > 1:
            _AR = OpsAgentRole  # forge_agents (ex-roles.py)
            text = parts[1]
            if _g("HAS_LOOPS", False):
                router = IntentRouter()  # importé depuis forge_agents
                role, conf, secondary = router.route_with_confidence(text)
                model = app.scorer.best_for(role, app.arch)
                meta = ROLE_META.get(role, {})
                chat.write(
                    f"[bold]Rôle détecté :[/] {meta.get('icon', '?')} "
                    f"[bold]{meta.get('label', role.value)}[/] "
                    f"(confiance={conf:.0%}) → {model}"
                )
                for r in secondary:
                    m2 = app.scorer.best_for(r, app.arch)
                    rm = ROLE_META.get(r, {})
                    chat.write(f"  {rm.get('icon', '?')} {rm.get('label', r.value)} → {m2}")
            else:
                chat.write("[red]❌ roles.py non disponible pour la détection[/]")
            return

    # ── Fallback : RoleOrchestrator classique (loops.py) ─────────────
    if not _g("HAS_LOOPS", False):
        chat.write("[red]❌ roles.py non disponible[/]")
        return

    if not hasattr(app, "_role_orchestrator"):
        app._role_orchestrator = RoleOrchestrator(
            forge_context.get_settings().ollama_url, forge_context.get_settings().ollama_tags_url
        )

    orc = app._role_orchestrator
    parts = args.split(maxsplit=1)
    sub = parts[0].lower() if parts else "list"

    if sub == "list":
        models = await orc.discover_models()
        chat.write(f"[bold]Modèles disponibles ({len(models)}) :[/]")
        for m in models:
            chat.write(f"  • {m}")
        summary = orc.summary()
        if summary != "Aucun rôle attribué.":
            chat.write(f"\n[bold]Assignations actuelles :[/]\n{summary}")

    elif sub == "assign":
        chat.write("[dim]⏳ Assignation des rôles ops…[/]")
        assignments = await orc.assign_ops_roles(
            run_benchmark=False,
            log_fn=lambda m: chat.write(m),
        )
        chat.write(f"[green]✅ {len(assignments)} rôles assignés[/]")

    elif sub == "detect" and len(parts) > 1:
        text = parts[1]
        role, model, secondary = await orc.assign_from_intent(text, log_fn=lambda m: chat.write(m))
        meta = ROLE_META.get(role, {})
        chat.write(
            f"[bold]Rôle détecté :[/] {meta.get('icon', '?')} [bold]{meta.get('label', role.value)}[/] → {model}"
        )
        if secondary:
            chat.write("[bold]Rôles secondaires :[/]")
            for r, m in secondary:
                rm = ROLE_META.get(r, {})
                chat.write(f"  {rm.get('icon', '?')} {rm.get('label', r.value)} → {m}")
    else:
        chat.write(
            "[bold]@role[/] list|assign|detect <texte>|arch|score\n"
            "  list   — modèles + scores\n"
            "  assign — ré-assigne par scoring automatique\n"
            "  arch   — re-détecte l'architecture cible\n"
            "  detect <texte> — détecte le rôle depuis un texte"
        )


async def do_scan(_subnet: object = None) -> None:
    """Do scan.

    Args:
        _subnet: Description.
    """
    _rag = _g_rag()
    try:
        nd = NetworkDiscovery(_subnet)
        # snif.py expose run() synchrone → on_thread pour ne pas bloquer
        import asyncio as _aio

        if hasattr(nd, "run_async"):
            devs = await nd.run_async(inject_rag=_rag)
        elif hasattr(nd, "scan_async"):
            devs = await nd.scan_async()
        elif hasattr(nd, "run_subnet"):
            devs = await _aio.to_thread(nd.run_subnet)
        elif hasattr(nd, "run"):
            # méthode synchrone → thread pour ne pas bloquer l'event loop
            devs = await _aio.to_thread(nd.run)
        elif hasattr(nd, "scan"):
            devs = await _aio.to_thread(nd.scan)
        else:
            meths = [m for m in dir(nd) if not m.startswith("_")]
            raise AttributeError(f"NetworkDiscovery : aucune méthode de scan trouvée. Disponibles : {meths}")
        chat.write(f"[green]✅ {len(devs)} appareil(s) sur {_subnet} :[/]")
        for d in devs:
            ip = d.get("ip", "?")
            host = d.get("hostname") or ""
            os_ = d.get("os") or ""
            pts = ", ".join(str(p) for p in (d.get("ports") or [])[:6])
            protos = ", ".join(d.get("protocols") or [])
            line = f"  [bold]{ip:<16}[/]"
            if host:
                line += f" [dim]{host[:20]}[/]"
            if os_:
                line += f" · [#79c0ff]{os_[:30]}[/]"
            if pts:
                line += f" · ports:[cyan]{pts}[/]"
            if protos:
                line += f" · [#8b949e]{protos}[/]"
            chat.write(line)
        # Afficher la topologie si NetworkX disponible
        topo = nd.topology_summary()
        if topo:
            chat.write(f"[bold]Topologie ({len(topo)} nœuds) :[/]")
            for node in topo[:8]:
                neighbors = ", ".join(node["neighbors"][:4])
                chat.write(f"  [dim]{node['node']:<16}[/] ↔ {neighbors or 'isolé'}")
            if len(topo) > 8:
                chat.write(f"  [dim]… +{len(topo) - 8} nœuds[/]")
            chat.write("[dim]Résultats injectés dans le RAG ✅[/]")
        debug_log("SECU", "@scan", "Terminé", {"subnet": _subnet, "count": len(devs)})
    except Exception as _e:
        chat.write(f"[red]❌ Scan: {escape(str(_e))}[/]")


async def do_scan_basic(_subnet: object = None) -> object:
    """Do scan basic.

    Args:
        _subnet: Description.
    """
    import ipaddress, socket as _sock, concurrent.futures as _cf

    try:
        net = ipaddress.ip_network(_subnet, strict=False)
    except ValueError:
        chat.write(f"[red]❌ Subnet invalide : {_subnet}[/]")
        return
    PORTS = [21, 22, 23, 25, 80, 443, 445, 3306, 3389, 8080, 8443, 8888, 161]
    TIMEOUT = 0.08  # 80ms — suffisant sur LAN

    def _probe(ip_s: object) -> object:
        """Probe.

        Args:
            ip_s: Description.
        """
        open_p, hostname = [], ""
        for p in PORTS:
            try:
                s = _sock.socket()
                s.settimeout(TIMEOUT)
                if s.connect_ex((ip_s, p)) == 0:
                    open_p.append(p)
                s.close()
            except Exception:
                pass
        if open_p:  # DNS seulement si hôte actif
            try:
                hostname = _sock.gethostbyaddr(ip_s)[0]
            except Exception:
                pass
        return ip_s, hostname, open_p

    hosts = [str(h) for h in list(net.hosts())[:254]]
    chat.write(f"[dim]  Sonde {len(hosts)} hôtes ({len(PORTS)} ports, timeout={int(TIMEOUT * 1000)}ms)…[/]")
    found = []
    loop = asyncio.get_event_loop()
    with _cf.ThreadPoolExecutor(max_workers=128) as ex:
        for ip_s, host, ports in await loop.run_in_executor(None, lambda: list(ex.map(_probe, hosts))):
            if ports:
                found.append((ip_s, host, ports))
    if found:
        chat.write(f"[green]✅ {len(found)} hôte(s) actif(s) :[/]")
        for ip_s, host, ports in sorted(found, key=lambda x: list(map(int, x[0].split(".")))):
            svc = {22: "SSH", 23: "Telnet", 80: "HTTP", 443: "HTTPS", 445: "SMB", 3389: "RDP", 3306: "MySQL", 21: "FTP"}
            line = f"  [bold]{ip_s:<16}[/]"
            if host:
                line += f" [dim]{host[:25]}[/]"
            line += (
                " · " + "[cyan]" + ", ".join(f"{p}({svc.get(p, '')})" if p in svc else str(p) for p in ports) + "[/]"
            )
            chat.write(line)
    else:
        chat.write(f"[dim]Aucun hôte actif détecté sur {_subnet}[/]")
    debug_log("SECU", "@scan", "Terminé (basique)", {"subnet": _subnet, "count": len(found)})


# _validate_suggestion_async — voir forge_handler_rag.py


async def run_collaboration(app: object, task: str) -> Tuple[str, str]:
    """
    Mode collaboration : tous les agents pertinents proposent en parallèle.
    Le dialogue synthétise les résultats.
    """
    app._push_context("user", task)

    rag_docs = await app.agents["rag"].search_context(task, k=3)
    rag_text = app.agents["rag"].format_docs(rag_docs) if rag_docs else ""

    # ── Contributions via ollama_parallel — tous les agents en même temps ──
    model = app.agents["dialogue"].model
    sys_base = (
        "Tu es La Forge, un assistant DevOps expert. "
        "Réponds en français, de façon technique et précise en 5-10 lignes max."
        + (f"\n\nDocumentation disponible :\n{rag_text[:600]}" if rag_text else "")
    )
    agent_roles = [
        ("DevOps & Infrastructure", "DevOps"),
        ("Sécurité & Durcissement", "Sécurité"),
        ("Réseau & Firewall", "Réseau"),
    ]
    calls = [
        {
            "model": model,
            "system": f"{sys_base}\n\nTu joues le rôle : Expert {role_label}.",
            "messages": [{"role": "user", "content": task}],
            "max_tokens": 400,
        }
        for role_label, _ in agent_roles
    ]
    # Appels parallèles — le sémaphore limite la concurrence Ollama
    raw_results = await ollama_parallel(calls)
    valid = [
        f"[{short}] {resp}"
        for (_, short), resp in zip(agent_roles, raw_results)
        if resp and not resp.startswith("[Erreur:")
    ]
    joined = "\n\n".join(valid)

    # Synthèse — un seul appel ollama_call supplémentaire
    final = await ollama_call(
        model=model,
        messages=[
            {
                "role": "user",
                "content": f"Synthétise ces contributions d'experts sur la tâche : {task}\n\n{joined}\n\n"
                f"Sois concis, garde les commandes concrètes, max 15 lignes.",
            }
        ],
        system=sys_base,
        max_tokens=600,
    )
    await app._enrich_rag(task, final)
    app._push_context("assistant", final)
    return final, "collaboration"


async def run_comite(app: object, task: str) -> Tuple[str, str]:
    """
    Mode comité : plusieurs agents proposent, le juge (dialogue) vote.
    Retourne la meilleure proposition avec justification.
    """
    app._push_context("user", task)

    rag_docs = await app.agents["rag"].search_context(task, k=3)
    rag_text = app.agents["rag"].format_docs(rag_docs) if rag_docs else ""

    # ── Propositions parallèles via ollama_parallel ─────────────────────
    model = app.agents["dialogue"].model
    experts = ["Expert DevOps", "Expert Sécurité", "Expert Réseau"]
    sys_ctx = "Tu es un expert DevOps. Réponds en français, sois précis et concis (max 8 lignes)." + (
        f"\n\nDocumentation disponible :\n{rag_text[:500]}" if rag_text else ""
    )
    calls = [
        {
            "model": model,
            "system": f"{sys_ctx}\n\nTu joues le rôle : {expert}.",
            "messages": [{"role": "user", "content": f"Propose ta meilleure solution pour : {task}"}],
            "max_tokens": 350,
        }
        for expert in experts
    ]
    raw_props = await ollama_parallel(calls)
    valid_props = [
        f"[{exp}]\n{resp}" for exp, resp in zip(experts, raw_props) if resp and not resp.startswith("[Erreur:")
    ]
    all_props = "\n\n---\n\n".join(valid_props)

    # Juge — un seul appel ollama_call
    verdict = await ollama_call(
        model=model,
        messages=[
            {
                "role": "user",
                "content": f"Voici {len(valid_props)} propositions d'experts pour : {task}\n\n"
                f"{all_props}\n\n"
                "Analyse chaque proposition, désigne la meilleure et explique pourquoi.\n"
                "Format OBLIGATOIRE :\n"
                "VERDICT : [nom expert]\n"
                "JUSTIFICATION : [2 phrases max]\n"
                "SYNTHÈSE FINALE : [réponse complète à appliquer]",
            }
        ],
        system="Tu es le Juge DevOps. Sois factuel, technique, concis.",
        max_tokens=500,
    )
    await app._enrich_rag(task, verdict)
    app._push_context("assistant", verdict)
    return verdict, "comite"


async def _handle_mem(app: object, cmd: str) -> None:
    """
    @mem / @mem status  -> modeles en memoire + GiB
    @mem free           -> libere embeddings
    @mem free-all       -> libere tout
    """
    from nokido_agent.app.forge_app_context import get_mem_mgr as _get_mem_mgr

    chat = app._chat_log()
    mgr = _get_mem_mgr()
    if mgr is None:
        chat.write("[yellow]OllamaMemoryManager non init[/]")
        return
    sub = (cmd.split() + ["status"])[1] if len(cmd.split()) > 1 else "status"
    if sub == "status":
        lines, total = await mgr.status_lines()
        if total == 0:
            chat.write("[dim]Aucun modele en memoire[/]")
            return
        chat.write("[bold]Memoire Ollama :[/]")
        for ln in lines:
            chat.write(f"[dim]{ln}[/]")
        chat.write("[dim]@mem free  -  @mem free-all[/]")
    elif sub == "free":
        res = await mgr.free(strategy="embed")
        if res["evicted"]:
            names = ", ".join(e.split(":")[0] for e in res["evicted"])
            chat.write(f"[green]Libere {res['freed_gib']:.1f} GiB ({names})[/]")
        else:
            chat.write("[dim]Rien a decharger[/]")
    elif sub == "free-all":
        res = await mgr.free(strategy="all")
        if res["evicted"]:
            names = ", ".join(e.split(":")[0] for e in res["evicted"])
            chat.write(f"[green]{len(res['evicted'])} modele(s) - {res['freed_gib']:.1f} GiB ({names})[/]")
        else:
            chat.write("[dim]Memoire deja vide[/]")
    else:
        chat.write("[dim]@mem status | free | free-all[/]")


async def get_remote_context() -> dict[str, str]:
    """Retrieve system information from a remote host via SSH.

    Executes a predefined set of commands (hostname, kernel, uptime,
    memory, disk usage) concurrently and returns their outputs as a
    dictionary mapping command names to trimmed strings or error    messages truncated to 40 characters.

    Returns:
        dict[str, str]: Mapping of command identifiers to their
        sanitized output.
    """
    cmds: dict[str, str] = {
        "hostname": "hostname",
        "kernel": "uname -r",
        "uptime": "uptime",
        "memory": "free -h",
        "disk": "df -h /",
    }
    from nokido_agent.app.forge_prefect import _get_run_ssh

    run_ssh = _get_run_ssh()
    # Run each SSH command concurrently, capturing exceptions.
    results: list[tuple[str, str] | BaseException] = await asyncio.gather(
        *[run_ssh(c) for c in cmds.values()], return_exceptions=True
    )
    out: dict[str, str] = {}
    for (k, _), r in zip(cmds.items(), results):
        if isinstance(r, tuple):
            # r is (stdout, stderr); use stdout if no error, else show truncated stderr.
            out[k] = r[0].strip() if not r[1] else f"err:{r[1][:40]}"
        else:
            # r is an exception; convert to string and truncate.
            out[k] = str(r)[:40]
    return out


async def _check_ollama_models(app: object) -> None:
    """Check ollama models.

    Args:
        app: Description.
    """
    from nokido_agent.app.forge_app_context import get_settings as _gset

    _settings = getattr(app, "settings", None) or _gset()
    """Vérifie Ollama + fallback modèle auto si introuvable."""
    chat = app._chat_log()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(_settings.ollama_tags_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    chat.write(f"[red]❌ Ollama HTTP {resp.status}[/]")
                    return
                data = await resp.json()
                models = [m["name"] for m in data.get("models", [])]
                chat_models = [m for m in models if "embed" not in m.lower()]
        if not chat_models:
            chat.write("[red]❌ Aucun modèle Ollama — ollama pull mistral[/]")
            return
        # Résolution du modèle par défaut :
        # si OLLAMA_MODEL_DEFAULT est vide → prendre le 1er modèle dispo
        _forced = _settings.ollama_model_default
        changed, fallback = [], (_forced if _forced and _forced in models else chat_models[0])
        for attr, lbl in [("model_chat", "💬"), ("model_action", "⚡"), ("model_rag", "🗄")]:
            cur = getattr(app, attr, None)
            if not cur or cur not in models:
                setattr(app, attr, fallback)
                changed.append(f"{lbl}→[green]{fallback}[/]")
        if changed:
            chat.write(f"[yellow]⚠ Modèles introuvables — fallback:[/] {' '.join(changed)}")
            chat.write(f"[dim]Dispo: {', '.join(chat_models[:5])} (@model pour changer)[/]")
            logger.warning(f"[boot] Ollama fallback : {' '.join(changed)}")
            app._update_sidebar_title()
        else:
            chat.write(
                f"[green]✅ Ollama OK[/] · "
                f"💬[bold]{getattr(app, 'model_chat', '-')}[/] "
                f"⚡[bold]{getattr(app, 'model_action', '-')}[/] "
                f"🗄[bold]{getattr(app, 'model_rag', '-')}[/]"
            )
            logger.info(
                f"[boot] Ollama OK : chat={getattr(app, 'model_chat', '-')} "
                f"action={getattr(app, 'model_action', '-')} "
                f"rag={getattr(app, 'model_rag', '-')} ({len(chat_models)} modèles)"
            )
    except aiohttp.ClientConnectorError:
        chat.write("[red]❌ Ollama non joignable — ollama serve[/]")
        logger.error("[boot] Ollama non joignable")
    except Exception as e:
        chat.write(f"[yellow]⚠ Ollama check: {e}[/]")
        logger.warning(f"[boot] Ollama check : {e}")


async def process_user_input(
    self,
    user_input: str,
    raw_input: Optional[str] = None,
) -> Tuple[str, str, Optional[str]]:
    """
    Pipeline de routage complet avec logs à chaque étape.
    Retourne (response, agent_type_used, cmd_to_inject).

    raw_input : la demande brute de l'utilisateur, sans les injections de
    contexte [CONTEXTE CIBLE] ni [RÉSULTATS WEB]. Si None, on tente de
    l'extraire automatiquement depuis user_input.
    """
    # ── Court-circuit @ commands — bypasse totalement le pipeline IA ───
    _raw = raw_input or user_input
    if _raw.strip().startswith("@"):
        try:
            from nokido_agent.app.forge_at_dispatch import AT_DISPATCH
            from nokido_agent.app.forge_dispatch import REGISTRY as _REG

            _cmd = _raw.strip().split()[0].lower()
            _parts = _raw.strip().split()
            _handler = AT_DISPATCH.get(_cmd) or _REG.get(_cmd)
            if _handler:
                await _handler(self, _raw.strip(), _parts, _cmd)
            # Toujours retourner pour les @ — meme si handler absent
            return ("", "AT_DISPATCH", None)
        except Exception as _at_e:
            logger.debug(f"process_user_input AT_DISPATCH: {_at_e}")
            return ("", "AT_DISPATCH_ERROR", None)
    # ── Pipeline normal ───────────────────────────────────────────────────
    intent_classifier = _g("intent_classifier")
    from nokido_agent.app.forge_core_models import AgentType, SupervisorAnalysis

    _agentic_eng = (
        __import__("forge_agentic").get_agentic_engine()
        if hasattr(__import__("forge_agentic"), "get_agentic_engine")
        else None
    )
    _push_context("user", user_input)
    t0 = time.monotonic()

    # ── ÉTAPE 0 : Extraire le raw_input (avant injection contexte) ────────
    # Le dispatch injecte le contexte AVANT d'appeler process_user_input.
    # On ne veut classifier que la demande réelle de l'utilisateur.
    if raw_input is None:
        # Tente d'extraire depuis "[DEMANDE]\n<texte>" si present
        _demande_match = re.search(r"\[DEMANDE\]\n(.+)", user_input, re.S)
        if _demande_match:
            raw_input = _demande_match.group(1).strip()
        else:
            raw_input = user_input

    # ── ÉTAPE 1 : NLU hybride (predictif + regex fallback) ─────────────
    nlu_intent, cmd_to_inject, nlu_conf = intent_classifier.classify_hybrid(raw_input)
    debug_log(
        "ROUTE",
        "OrchestratorManager.process_user_input",
        "NLU classification",
        {
            "input": raw_input[:100],
            "nlu_intent": nlu_intent.value,
            "nlu_conf": round(nlu_conf, 2),
            "cmd_extracted": cmd_to_inject,
        },
    )

    # ── ÉTAPE 2 : Supervisor — court-circuit si NLU CHAT confiant ───────
    # Si PREDICTIF ou regex dit CHAT avec conf >= 0.68, on ne consulte pas
    # le supervisor heuristique (qui ré-introduit des faux-positifs ACTION
    # via ses shell_indicators sur ? [ ] etc.)
    # FIX : seuil abaissé à 0.58 (fallback regex retourne 0.60)
    # NLU regex CHAT + conf >= 0.58 → court-circuiter supervisor
    # (évite que supervisor ré-introduise des faux-positifs ACTION via ?)
    if nlu_intent == AgentType.CHAT and nlu_conf >= 0.58:
        supervisor_result = SupervisorAnalysis()
        supervisor_result.needs_dialogue = True
        supervisor_result.confidence = nlu_conf
        supervisor_result.reasoning = f"[NLU-CHAT direct] conf={nlu_conf:.2f}"
    else:
        supervisor_result = await agents["supervisor"].analyze_intent(raw_input)
        # ── ÉTAPE 3 : Fusion NLU + Supervisor ────────────────────────────
        if nlu_intent == AgentType.ACTION:
            supervisor_result.needs_action = True
            supervisor_result.needs_rag = False
            supervisor_result.needs_dialogue = False
            supervisor_result.reasoning = f"[NLU override] {supervisor_result.reasoning}"
        elif nlu_intent == AgentType.RAG and not supervisor_result.needs_action:
            supervisor_result.needs_rag = True
            supervisor_result.needs_dialogue = False

    debug_log(
        "ROUTE",
        "OrchestratorManager.process_user_input",
        "Supervisor analysis",
        {
            "needs_action": supervisor_result.needs_action,
            "needs_rag": supervisor_result.needs_rag,
            "needs_dialogue": supervisor_result.needs_dialogue,
            "confidence": round(supervisor_result.confidence, 2),
            "reasoning": supervisor_result.reasoning[:120],
        },
    )

    final_intent = "action" if supervisor_result.needs_action else "rag" if supervisor_result.needs_rag else "dialogue"
    debug_log(
        "ROUTE",
        "OrchestratorManager.process_user_input",
        "Intent après fusion NLU+Supervisor",
        {"final_intent": final_intent, "nlu_was": nlu_intent.value, "cmd_to_inject": cmd_to_inject},
    )

    # ── ÉTAPE 4 : RAG piloté par AgenticEngine ──────────────────────────
    # Si AgenticEngine disponible et requête non-ACTION :
    #   → prepare_rag_context() vérifie compétences, enrichit si besoin, puis search
    # Sinon : search_context direct (fallback léger)
    _skip_rag = nlu_intent == AgentType.CHAT and nlu_conf >= 0.80 and not supervisor_result.needs_rag
    _agentic_meta = {}
    if _skip_rag:
        rag_context = []
        debug_log(
            "ROUTE",
            "OrchestratorManager.process_user_input",
            "RAG skipped (CHAT confiant)",
            {"nlu_conf": round(nlu_conf, 2)},
        )
    elif _agentic_eng and not supervisor_result.needs_action:
        # AgenticEngine pilote : check compétences → enrichit → search
        _rh = "rag" if nlu_intent == AgentType.RAG else "chat"
        rag_context, _agentic_meta = await _agentic_eng.prepare_rag_context(raw_input, k=6, role_hint=_rh)
        debug_log(
            "ROUTE",
            "OrchestratorManager.process_user_input",
            "RAG via AgenticEngine",
            {
                "docs_found": len(rag_context),
                "enriched": _agentic_meta.get("enriched", False),
                "skills": _agentic_meta.get("skills", []),
                "missing": _agentic_meta.get("missing", []),
                "top_score": round(rag_context[0]["score"], 3) if rag_context else 0,
            },
        )
    else:
        # Fallback direct (ACTION ou pas d'AgenticEngine)
        _rh = "action" if nlu_intent == AgentType.ACTION else "chat"
        rag_context = await agents["rag"].search_context(user_input, k=6, role_hint=_rh)
        debug_log(
            "ROUTE",
            "OrchestratorManager.process_user_input",
            "RAG search direct",
            {
                "docs_found": len(rag_context) if rag_context else 0,
                "top_score": round(rag_context[0]["score"], 3) if rag_context else 0,
            },
        )

    # ── ÉTAPE 5 : Plan de routage (avec l'analysis déjà calculée) ────────
    routing_plan = await agents["supervisor"].create_routing_plan(user_input, rag_context, analysis=supervisor_result)
    debug_log(
        "ROUTE",
        "OrchestratorManager.process_user_input",
        "Routing plan",
        {"steps": [s["agent_type"] for s in routing_plan.steps], "reasoning": routing_plan.reasoning[:120]},
    )

    # ── ÉTAPE 6 : Exécution ───────────────────────────────────────────────
    final_response, agent_used = await _execute_routing_plan(routing_plan, user_input, rag_context, cmd_to_inject)
    elapsed = round(time.monotonic() - t0, 2)
    debug_log(
        "ROUTE",
        "OrchestratorManager.process_user_input",
        "Pipeline terminé",
        {
            "agent_used": agent_used,
            "cmd_injected": cmd_to_inject,
            "elapsed_s": elapsed,
            "response_len": len(final_response),
        },
    )

    # ── ÉTAPE 7 : Enrichissement RAG ─────────────────────────────────────
    await _enrich_rag(user_input, final_response)
    _push_context("assistant", final_response)

    return final_response, agent_used, cmd_to_inject


# ── Ré-exports depuis modules domaine (compatibilité) ──────────────────
from nokido_agent.app.forge_handler_ci import _handle_loop  # noqa: F401


async def on_unmount(app: object) -> None:
    # Résoudre les globals Nokido
    """On unmount.

    Args:
        app: Description.
    """
    from app.core.settings import get_app_attr as _gu

    _mem_mgr = _gu("mem_optimizer") or _gu("_mem_mgr")
    _prefect_mgr = forge_context.get_prefect_manager()
    _rag_eng = _g_rag()
    HAS_ONNX = _gu("HAS_ONNX", False)
    HAS_MEMORY = _gu("HAS_MEMORY", False)
    mem_optimizer = _gu("mem_optimizer")
    shutdown_onnx_backend = _gu("shutdown_onnx_backend") or (lambda: None)
    _queue_listener = _gu("_queue_listener")
    _jsonl_handler = _gu("_jsonl_handler")
    _debug_main_handle = _gu("_debug_main_handle")
    _debug_route_handle = _gu("_debug_route_handle")
    # ── Déconnexion PTY + SSH ────────────────────────────────────
    try:
        await app.terminal.disconnect()
    except Exception:
        pass

    # ── Arrêt Prefect ────────────────────────────────────────────
    try:
        await _prefect_mgr.stop()
    except Exception:
        pass

    # ── Fermeture RAG ────────────────────────────────────────────
    try:
        _re = globals().get("rag_engine")
        if _re:
            await _re.close()
    except Exception:
        pass

    # ── Déchargement modèles Ollama ──────────────────────────────
    if _mem_mgr:
        try:
            await _mem_mgr.free("all")
        except Exception:
            pass

    # ── Arrêt ONNX/sidecar ───────────────────────────────────────
    if HAS_ONNX:
        try:
            shutdown_onnx_backend()
        except Exception:
            pass

    # ── Nettoyage mémoire final ──────────────────────────────────
    if HAS_MEMORY and mem_optimizer:
        try:
            mem_optimizer.optimize(_rag_engine=_rag_eng, aggressive=True)
        except Exception:
            pass
    gc.collect()

    # ── Arrêt logging ────────────────────────────────────────────
    try:
        _queue_listener.stop()
        _jsonl_handler.close()
    except Exception:
        pass
    for _fh in (_debug_main_handle, _debug_route_handle):
        try:
            if _fh and not _fh.closed:
                _fh.flush()
                _fh.close()
        except Exception:
            pass

    # ── Tuer les processus enfants (brain_worker, terminaux) ─────
    try:
        pid = os.getpid()
        if sys.platform == "win32":
            # Tuer les enfants SEULEMENT, pas le parent
            # wmic donne la liste des enfants d'un PID
            import subprocess

            result = subprocess.run(
                f"wmic process where (ParentProcessId={pid}) get ProcessId /format:list",
                capture_output=True,
                text=True,
                shell=True,
                timeout=5,
            errors="replace")
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("ProcessId="):
                    child_pid = line.split("=")[1].strip()
                    if child_pid and child_pid.isdigit():
                        try:
                            os.system(f"taskkill /F /T /PID {child_pid} >nul 2>&1")
                            logger.debug(f"[shutdown] killed child PID {child_pid}")
                        except Exception:
                            pass
        else:
            # Unix : envoyer SIGTERM aux enfants via le process group
            import signal

            try:
                # Lister les enfants via /proc
                _children = []
                for _p in Path("/proc").iterdir():
                    try:
                        _stat = (_p / "stat").read_text().split()
                        if int(_stat[3]) == pid:  # ppid == notre pid
                            _children.append(int(_stat[0]))
                    except Exception:
                        continue
                for _cpid in _children:
                    try:
                        os.kill(_cpid, signal.SIGTERM)
                        logger.debug(f"[shutdown] SIGTERM → PID {_cpid}")
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass


# [EXTRAIT → forge_handlers.py] compose — stub NR
def compose(self) -> "ComposeResult":
    """Compose  dlgue au mixin UI."""
    from nokido_agent.app.forge_compose import compose as _compose_main

    return _compose_main(self)


# ── Tombeaux de compatibilité (références Nokido.py) ──────────────────────


def _propagate_patch(*args, **kwargs) -> None:  # noqa: F811
    """Stub de compatibilité — tombeau Nokido.py."""


def _validate_patch(*args, **kwargs) -> bool:  # noqa: F811
    """Stub de compatibilité — tombeau Nokido.py."""
    return True


# ── Wrappers CANARI — re-exports depuis modules spécialisés ────────────────


def _handle_nr(app: object, args: str) -> None:
    """Wrapper CANARI — délègue à forge_handler_nr._handle_nr."""
    from nokido_agent.app.forge_handler_nr import _handle_nr as _impl

    return _impl(app, args)


def classify_with_cmd(
    cmd: str,
    _chat_q_pat: object = None,
    _chat_starters: object = None,
    _conv_pat: object = None,
    _sys_tools: object = None,
) -> tuple:
    """Wrapper CANARI — délègue à forge_handler_patch.classify_with_cmd."""
    from nokido_agent.app.forge_handler_patch import classify_with_cmd as _impl

    return _impl(cmd, _chat_q_pat, _chat_starters, _conv_pat, _sys_tools)
