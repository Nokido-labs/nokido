# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_commands
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_commands.py — Dispatcher @ unifié
========================================
Lazy imports stricts — chaque handler importe son module au moment de l'appel.
Nettoyage automatique args : strip prefixe @xxx avant passage au handler.
"""

import re
import logging

logger = logging.getLogger("Nokido.Commands")


# ── Commit Guard — Règle IV du Manifeste Technique ────────────────────────────


def safe_write(path, content: str, agent: str = "Nokido") -> tuple[bool, str]:
    """
    Règle IV — Commit Guard Non-Négociable.

    Écrit `content` dans `path` UNIQUEMENT si :
      1. Le fichier n'est pas un fichier Python critique (forge_*.py / Nokido.py)
         OU passe py_compile sans erreur.
      2. L'écriture atomique réussit.

    Retourne (True, "") en succès ou (False, message_erreur) en échec.

    Utilisé par tous les agents (Claude, Cline, TUI) pour toute écriture de code.
    """
    import py_compile
    import tempfile
    import os
    from pathlib import Path as _Path

    p = _Path(path)
    is_forge_py = p.suffix == ".py" and (p.name.startswith("forge_") or p.name == "Nokido.py")

    if is_forge_py:
        # Étape 1 : compiler dans un fichier temporaire
        try:
            with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as tf:
                tf.write(content)
                tf_path = tf.name
            py_compile.compile(tf_path, doraise=True)
            os.unlink(tf_path)
            logger.info(f"[Commit Guard] ✅ {p.name} — py_compile OK [{agent}]")
        except py_compile.PyCompileError as e:
            try:
                os.unlink(tf_path)
            except Exception:
                pass
            msg = f"COMMIT GUARD FAIL: {p.name}: {e.msg[:120]} [{agent}]"
            logger.error(f"[Commit Guard] ❌ {msg}")
            return False, msg
        except Exception as e:
            msg = f"COMMIT GUARD ERROR: {p.name}: {e} [{agent}]"
            logger.error(f"[Commit Guard] ❌ {msg}")
            return False, msg

    # Étape 2 : écriture atomique
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # Écriture via fichier temporaire + rename (atomique sur même filesystem)
        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False, mode="w", encoding="utf-8", dir=p.parent) as tf:
            tf.write(content)
            tf_path = tf.name
        import shutil

        shutil.move(tf_path, str(p))
        guard_label = " [Commit Guard: OK]" if is_forge_py else ""
        logger.info(f"[safe_write] ✅ {p.name} ({len(content)} chars){guard_label} [{agent}]")
        return True, ""
    except Exception as e:
        msg = f"safe_write IO ERROR: {p.name}: {e}"
        logger.error(f"[safe_write] ❌ {msg}")
        return False, msg


def _split(cmd_line: str) -> tuple[str, str]:
    """
    '@rag info'  -> ('@rag', 'info')
    '@role'      -> ('@role', '')
    '@rag @rag'  -> ('@rag', '')   # double-prefix nettoye
    """
    parts = cmd_line.strip().split(maxsplit=1)
    cmd = parts[0].lower() if parts else ""
    args = parts[1].strip() if len(parts) > 1 else ""
    args = re.sub(r"^@\w+\s*", "", args).strip()
    return cmd, args


# ── Handlers (lazy import) ────────────────────────────────────────────────────


async def _cmd_rag(app, args: str) -> None:
    """Cmd rag.

    Args:
        app: Description.
        args: Description.
    """
    import forge_context as _fc, importlib, forge_handler_rag as _fhr

    app.rag_engine = _fc.rag_engine  # passer l'instance au handler
    importlib.reload(_fhr)
    await _fhr._handle_rag(app, args)


async def _cmd_role(app, args: str) -> None:
    """Cmd role.

    Args:
        app: Description.
        args: Description.
    """
    from nokido_agent.app.forge_handler_agents import _handle_role

    await _handle_role(app, args)


async def _cmd_mode(app, args: str) -> None:
    """Cmd mode.

    Args:
        app: Description.
        args: Description.
    """
    from nokido_agent.app.forge_handler_agents import _handle_mode

    await _handle_mode(app, args)


async def _cmd_nr(app, args: str) -> None:
    """Cmd nr.

    Args:
        app: Description.
        args: Description.
    """
    from nokido_agent.app.forge_handlers import _handle_nr

    await _handle_nr(app, args)


async def _cmd_workflow(app, args: str) -> None:
    """Cmd workflow.

    Args:
        app: Description.
        args: Description.
    """
    from nokido_agent.app.forge_handler_ci import _handle_workflow

    await _handle_workflow(app, args)


async def _cmd_ci(app, args: str) -> None:
    """Cmd ci.

    Args:
        app: Description.
        args: Description.
    """
    from nokido_agent.app.forge_handler_ci import _handle_ci

    await _handle_ci(app, args)


async def _cmd_apply(app, args: str) -> None:
    """Cmd apply.

    Args:
        app: Description.
        args: Description.
    """
    from nokido_agent.app.forge_handler_patch import _handle_apply

    await _handle_apply(app, args)


async def _cmd_run(app, args: str) -> None:
    """Cmd run.

    Args:
        app: Description.
        args: Description.
    """
    from nokido_agent.app.forge_handler_patch import _handle_run

    await _handle_run(app, args)


async def _cmd_ssh(app, args: str) -> None:
    """Cmd ssh.

    Args:
        app: Description.
        args: Description.
    """
    from nokido_agent.app.forge_at_dispatch import handle_at_ssh

    parts = ["@ssh"] + args.split()
    await handle_at_ssh(app, f"@ssh {args}", parts, "@ssh")


async def _cmd_ollama(app, args: str) -> None:
    """Cmd ollama.

    Args:
        app: Description.
        args: Description.
    """
    from nokido_agent.app.forge_at_dispatch import handle_at_ollama

    parts = ["@ollama"] + args.split()
    await handle_at_ollama(app, f"@ollama {args}", parts, "@ollama")


async def _cmd_scan(app, args: str) -> None:
    """Cmd scan.

    Args:
        app: Description.
        args: Description.
    """
    from nokido_agent.app.forge_at_dispatch import handle_at_scan

    parts = ["@scan"] + args.split()
    await handle_at_scan(app, f"@scan {args}", parts, "@scan")


async def _cmd_web(app, args: str) -> None:
    """Cmd web.

    Args:
        app: Description.
        args: Description.
    """
    from nokido_agent.app.forge_at_dispatch import handle_at_web

    parts = ["@web"] + args.split()
    await handle_at_web(app, f"@web {args}", parts, "@web")


async def _cmd_services(app, args: str) -> None:
    """Cmd services.

    Args:
        app: Description.
        args: Description.
    """
    from nokido_agent.app.forge_at_dispatch import handle_at_services

    parts = ["@services"] + args.split()
    await handle_at_services(app, f"@services {args}", parts, "@services")


async def _cmd_agentic(app, args: str) -> None:
    """Cmd agentic.

    Args:
        app: Description.
        args: Description.
    """
    from nokido_agent.app.forge_at_dispatch import handle_at_agentic

    parts = ["@agentic"] + args.split()
    await handle_at_agentic(app, f"@agentic {args}", parts, "@agentic")


async def _cmd_help(app, args: str) -> None:
    """Cmd help.

    Args:
        app: Description.
        args: Description.
    """
    chat = app._chat_log()
    descs = {
        "@rag": "info / list / size / reindex / del / purge / build",
        "@mem": "status / clear",
        "@role": "list / assign <role>",
        "@mode": "status / set <mode>",
        "@agentic": "start / stop / status",
        "@chain": "<chaine agents>",
        "@run": "<commande shell>",
        "@ssh": "connect / exec / status",
        "@scan": "scan reseau / ports",
        "@services": "liste endpoints",
        "@proxy": "status / set",
        "@model": "selecteur modele Ollama",
        "@ollama": "list / pull / status",
        "@web": "<requete web search>",
        "@estim": "<estimation tache>",
        "@workflow": "list / run <id>",
        "@ci": "status / run pipeline",
        "@apply": "<patch fichier>",
        "@audit": "rapport securite",
        "@loop": "start / stop boucle",
        "@nr": "non-regression checks",
        "@help": "cette aide",
    }
    chat.write("[bold #58a6ff]⚒ Nokido — commandes @[/]")
    for cmd in sorted(COMMAND_MAP.keys()):
        chat.write(f"  [cyan bold]{cmd:<12}[/] [dim]{descs.get(cmd, '')}[/]")


async def _cmd_audit(app, args: str) -> None:
    """Cmd audit.

    Args:
        app: Description.
        args: Description.
    """

    async def _run() -> None:
        """Run."""
        await app._handle_audit()

    app.run_worker(_run(), exclusive=False, thread=False)


async def _cmd_loop(app, args: str) -> None:
    """Cmd loop.

    Args:
        app: Description.
        args: Description.
    """
    try:
        await app._handle_loop(args)
    except Exception as e:
        app._chat_log().write(f"[red]❌ @loop: {e}[/]")


async def _cmd_proxy(app, args: str) -> None:
    """Cmd proxy.

    Args:
        app: Description.
        args: Description.
    """
    try:
        method = getattr(app, "_handle_proxy", None)
        if method:
            await method(args)
    except Exception as e:
        app._chat_log().write(f"[red]❌ @proxy: {e}[/]")


async def _cmd_estim(app, args: str) -> None:
    """Cmd estim.

    Args:
        app: Description.
        args: Description.
    """

    async def _run() -> None:
        """Run."""
        await app._handle_estim(args)

    app.run_worker(_run(), exclusive=False, thread=False)


async def _cmd_model(app, args: str) -> None:
    """Cmd model.

    Args:
        app: Description.
        args: Description.
    """
    await app._open_model_screen(args)


async def _cmd_chain(app, args: str) -> None:
    """Cmd chain.

    Args:
        app: Description.
        args: Description.
    """
    try:
        method = getattr(app, "_handle_chain", None)
        if method:
            await method(args)
    except Exception as e:
        app._chat_log().write(f"[red]❌ @chain: {e}[/]")


async def _cmd_mem(app, args: str) -> None:
    """Cmd mem.

    Args:
        app: Description.
        args: Description.
    """
    try:
        await app._handle_mem(args)
    except Exception as e:
        app._chat_log().write(f"[red]❌ @mem: {e}[/]")


# ── COMMAND_MAP complète ──────────────────────────────────────────────────────


async def _cmd_collab(app, args: str) -> None:
    """
    @collab [ping|chef|debat|auto] [--with claude,gemini] [--model auto|<nom>] [--turns N] <prompt>
    Nokido orchestre la collaboration entre agents.
    """
    import re as _re

    chat = app._chat_log()

    MODES = ("ping", "chef", "debat", "auto", "cline")

    # Parser les options
    participants = ["ollama"]  # defaut
    chef_model = "auto"
    turns = 3
    mode = "ping"

    # --with claude,gemini
    m_with = _re.search(r"--with\s+([\w,]+)", args)
    if m_with:
        participants = [p.strip().lower() for p in m_with.group(1).split(",") if p.strip()]
        args = args.replace(m_with.group(0), "").strip()

    # --model <nom>
    m_model = _re.search(r"--model\s+(\S+)", args)
    if m_model:
        chef_model = m_model.group(1)
        args = args.replace(m_model.group(0), "").strip()

    # --turns N
    m_turns = _re.search(r"--turns\s+(\d+)", args)
    if m_turns:
        turns = int(m_turns.group(1))
        args = args.replace(m_turns.group(0), "").strip()

    # Mode
    parts = args.strip().split(None, 1)
    if parts and parts[0].lower() in MODES:
        mode = parts[0].lower()
        prompt = parts[1] if len(parts) > 1 else ""
    else:
        prompt = args.strip()

    if not prompt:
        chat.write(
            "[bold #f7c948]@collab[/] — Collaboration multi-agents orchestree par LaForge\n"
            "  [bold]ping[/]   Ping-pong alterné avec synthese finale\n"
            "  [bold]chef[/]   Nokido planifie, agents executent\n"
            "  [bold]debat[/]  These / Antithese / Synthese\n"
            "  [bold]auto[/]   Nokido decide si elle delegue\n\n"
            "Options:\n"
            "  [bold]--with[/] claude,gemini    participants (defaut: ollama)\n"
            "  [bold]--model[/] auto|<nom>      modele chef (defaut: auto-detect)\n"
            "  [bold]--turns[/] N               nombre de tours (defaut: 3)\n\n"
            "Exemples:\n"
            "  [italic]@collab ping --with claude,gemini Optimise ce handler[/]\n"
            "  [italic]@collab debat --with gemini --turns 2 SQLite vs PostgreSQL[/]"
        )
        return

    async def _run_collab() -> None:
        """Run collab."""
        try:
            from nokido_agent.app import forge_context as _ctx
            import uuid as _uuid

            sid = getattr(app, "_session_id", "") or f"collab_{_uuid.uuid4().hex[:8]}"

            # Orchestrateur central
            orc = _ctx.get_orchestrator()
            if orc is None:
                chat.write("[red]❌ OrchestratorManager non initialise[/]")
                return

            if mode == "ping":
                await orc.ping_pong(
                    task=prompt,
                    models_list=participants,
                    chat=chat,
                    session_id=sid,
                )
            elif mode == "chef":
                await orc.chef_dispatch(
                    task=prompt,
                    chat=chat,
                    session_id=sid,
                    participants=participants,
                )
            elif mode == "debat":
                await orc.debate_compare(
                    query=prompt,
                    models_list=participants,
                    chat=chat,
                    session_id=sid,
                )
            elif mode == "auto":
                from nokido_agent.app.forge_collab_modes import run_mode_auto

                await run_mode_auto(chat=chat, task=prompt)
            elif mode == "cline":
                import os as _os, socket as _socket, subprocess as _sub
                from nokido_agent.app import forge_context as _fctx

                # Lire config port depuis .env
                _ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
                _port = 8766
                try:
                    for _l in (_ROOT / "Nokido.env").read_text(encoding="utf-8").splitlines():
                        if _l.startswith("MCP_HTTP_PORT="):
                            _port = int(_l.split("=", 1)[1].strip())
                except Exception:
                    pass

                # Verifier si le serveur tourne deja
                _running = False
                try:
                    _s = _socket.create_connection(("127.0.0.1", _port), timeout=1)
                    _s.close()
                    _running = True
                except Exception:
                    pass

                if _running:
                    chat.write(f"[green]✅ Serveur MCP HTTP deja actif sur :{_port}[/]")
                else:
                    # Lancer le serveur en background
                    chat.write(f"[cyan]⚡ Lancement serveur MCP HTTP sur :{_port}...[/]")
                    _bat = _ROOT / "start_mcp_http.bat"
                    _py = __import__("sys").executable
                    _srv = str(_ROOT / "tools" / "nokido_mcp_server.py")
                    # Charger le token depuis .env
                    _env = {**_os.environ}
                    try:
                        for _l in (_ROOT / "Nokido.env").read_text(encoding="utf-8").splitlines():
                            if "=" in _l and not _l.startswith("#"):
                                _k, _v = _l.split("=", 1)
                                _env[_k.strip()] = _v.strip()
                    except Exception:
                        pass
                    try:
                        _sub.Popen(
                            [_py, _srv, "--mode", "http", "--name", "CLINE"],
                            env=_env,
                            creationflags=_sub.DETACHED_PROCESS | _sub.CREATE_NEW_PROCESS_GROUP
                            if _os.name == "nt"
                            else 0,
                        )
                        # Attendre que le port soit pret (max 5s)
                        import asyncio as _aio

                        for _ in range(10):
                            await _aio.sleep(0.5)
                            try:
                                _s = _socket.create_connection(("127.0.0.1", _port), timeout=0.5)
                                _s.close()
                                _running = True
                                break
                            except Exception:
                                pass
                        if _running:
                            chat.write(f"[green]✅ Serveur MCP HTTP pret sur :{_port}[/]")
                        else:
                            chat.write("[yellow]⚠ Serveur lance mais pas encore pret — attends quelques secondes[/]")
                    except Exception as _e:
                        chat.write(f"[red]❌ Impossible de lancer le serveur: {_e}[/]")

                # Basculer bridge_state en mode CLINE
                _fctx.set_active_mode("CLINE", reason="@collab cline")
                chat.write(
                    "[bold #58a6ff]🔗 Mode CLINE actif[/]\n"
                    f"  Serveur MCP HTTP : [link]http://127.0.0.1:{_port}/mcp[/link]\n"
                    "  [dim]CLINE_PLAN + CLINE_ACT peuvent se connecter[/]\n"
                    "  [dim]bridge_state.json synchronise Claude ↔ Cline[/]"
                )

            else:
                chat.write(f"[yellow]Mode {mode} non reconnu[/]")

        except Exception as e:
            import traceback as _tb

            chat.write(f"[red]❌ @collab: {e}[/]")
            chat.write(f"[dim]{_tb.format_exc()[-400:]}[/]")

    app.run_worker(_run_collab(), exclusive=False, thread=False)


COMMAND_MAP: dict = {
    "@rag": _cmd_rag,
    "@role": _cmd_role,
    "@mode": _cmd_mode,
    "@nr": _cmd_nr,
    "@workflow": _cmd_workflow,
    "@ci": _cmd_ci,
    "@apply": _cmd_apply,
    "@run": _cmd_run,
    "@ssh": _cmd_ssh,
    "@ollama": _cmd_ollama,
    "@scan": _cmd_scan,
    "@web": _cmd_web,
    "@services": _cmd_services,
    "@agentic": _cmd_agentic,
    "@help": _cmd_help,
    "@audit": _cmd_audit,
    "@loop": _cmd_loop,
    "@proxy": _cmd_proxy,
    "@estim": _cmd_estim,
    "@model": _cmd_model,
    "@chain": _cmd_chain,
    "@mem": _cmd_mem,
    "@collab": _cmd_collab,
}


# ── Dispatcher principal ──────────────────────────────────────────────────────


async def dispatch_at(app, cmd_line: str) -> bool:
    """
    Dispatche une commande @ vers le bon handler.
    Retourne True si traitee, False si commande inconnue.
    """
    cmd, args = _split(cmd_line)

    # DEBUG — a retirer apres validation
    import logging as _lg

    _lg.getLogger("Nokido.Commands").info(f"[forge_commands] dispatch_at cmd={cmd!r} args={args!r}")

    handler = COMMAND_MAP.get(cmd)
    if handler is None:
        return False
    try:
        await handler(app, args)
    except Exception as e:
        logger.error(f"dispatch_at {cmd}: {e}", exc_info=True)
        try:
            app._chat_log().write(f"[red]❌ {cmd}: {e}[/]")
        except Exception:
            pass
    return True
