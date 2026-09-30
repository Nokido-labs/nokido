# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_events
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""forge_events.py — Handlers UI extraits de Nokido.py (v16.5)"""

from nokido_agent.app import forge_context
import asyncio, json, os, sys
from pathlib import Path
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

from app.core.settings import get_app_attr as _g  # noqa: F401


def _settings() -> object:
    """Settings."""
    return forge_context.get_settings()


def _vm() -> object:
    """Vm."""
    return forge_context.get_version_manager()


def _AgentType() -> object:
    """Agenttype."""
    return _g("AgentType")


def _AGENT_META() -> dict:
    """Agent meta."""
    return _g("AGENT_META", {})


# ── on_button_pressed ───────────────────────────────


async def on_button_pressed(app, event) -> None:
    """On button pressed.

    Args:
        app: Description.
        event: Description.
    """
    bid = getattr(event.button, "id", "") or ""

    # ── Core TUI bridge — notifier le Hub des clics boutons ─────────────────
    _TUI_BUTTON_MAP = {
        "btn-mode-autonome": ("auto_mode", {"level": 3}),
        "btn-mode-collaboration": ("collab_mode", {"level": 2}),
        "btn-mode-comite": ("collab_mode", {"level": 1}),
        "btn-agent-action": ("run_action", {}),
        "btn-agent-rag": ("query_rag", {}),
    }
    if bid in _TUI_BUTTON_MAP:
        try:
            from nokido_agent.app.nokido_core import get_core as _gc

            _cmd, _payload = _TUI_BUTTON_MAP[bid]
            _gc().push_tui_command(_cmd, _payload, source="tui")
        except Exception:
            pass
    AgentType = _AgentType()

    if bid in ("btn-mode-autonome", "btn-mode-collaboration", "btn-mode-comite"):
        mode = bid.replace("btn-mode-", "")
        app._collab_mode = mode
        app._update_mode_buttons()
        COLORS = {"autonome": "#79c0ff", "collaboration": "#56d364", "comite": "#d2a8ff"}
        ICONS = {"autonome": "🤖", "collaboration": "🤝", "comite": "⚖️ "}
        color = COLORS[mode]
        icon = ICONS[mode]
        app._safe_write(f"[bold {color}]{icon} Mode {mode.capitalize()}[/]")
        if mode in ("collaboration", "comite"):
            app._awaiting_collab_prompt = mode
            app._safe_write(
                f"[bold {color}]⤵ Prompt maître ?[/] "
                f"[dim]Décris la tâche — agents : {', '.join(app._collab_agents())}[/]"
            )
        else:
            app._awaiting_collab_prompt = ""
            app._safe_write("[dim]Mode autonome — tape ton message normalement.[/]")
        return

    if AgentType:
        if bid == "btn-agent-chat":
            app._set_agent(AgentType.CHAT)
        elif bid == "btn-agent-action":
            app._set_agent(AgentType.ACTION)
        elif bid == "btn-agent-rag":
            app._set_agent(AgentType.RAG)

    if bid == "btn-model":
        await app._select_model()
    elif bid == "btn-rag-open":
        s = _settings()
        path = Path(s.rag_dir) if s else Path(".")
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                os.system(f"open {path}")
            else:
                os.system(f"xdg-open {path}")
            app._safe_write(f"[dim]📁 {path}[/]")
        except Exception as e:
            app._safe_write(f"[yellow]⚠ RAG dir: {e}[/]")


# ── _handle_orchestrated_input ──────────────────────


async def _handle_orchestrated_input(app, user_input: str) -> None:
    """Gère les entrées utilisateur via l'orchestrateur."""

    # Enregistrer dans l'historique autocomplete
    _ac = getattr(app, "_autocomplete_engine", None)
    if _ac is None:
        try:
            AutocompleteInput = _g("AutocompleteInput")
            if AutocompleteInput:
                _ac = app.query_one("#chat-input", AutocompleteInput)._engine
                app._autocomplete_engine = _ac
        except Exception:
            pass
    if _ac is None:
        AutocompleteEngine = _g("AutocompleteEngine")
        if AutocompleteEngine:
            app._autocomplete_engine = AutocompleteEngine()
            _ac = app._autocomplete_engine
    if _ac:
        _ac.add_to_history(user_input)

    # Sélection suggestion @audit par numéro ou "t"
    if app.last_audit_suggestions:
        stripped = user_input.strip().lower()
        vm = _vm()
        if stripped == "t":
            app._safe_write(f"[bold #79c0ff]▸[/] {escape(user_input)}")
            ok = 0
            for sugg in app.last_audit_suggestions:
                if await app._apply_suggestion(sugg, _ask_restart=False):
                    ok += 1
            vf = vm.current_version if vm else "?"
            app._safe_write(f"[bold green]✅ {ok}/{len(app.last_audit_suggestions)} → v{vf}[/]")
            if ok > 0:
                app._propose_restart(f"{ok} suggestions → v{vf}")
            return
        if stripped.isdigit():
            num = int(stripped)
            sugg = next((s for s in app.last_audit_suggestions if s["num"] == num), None)
            if sugg:
                app._safe_write(f"[bold #79c0ff]▸[/] {escape(user_input)}")
                if await app._apply_suggestion(sugg, _ask_restart=False):
                    vm = _vm()
                    app._propose_restart(f"suggestion {num} → v{vm.current_version if vm else '?'}")
                return

    # Affichage et dispatch
    app._safe_write(f"[bold #79c0ff]▸[/] {escape(user_input)}")
    if user_input.startswith("@"):
        await app._handle_at(user_input)
    else:
        # ── Log message naturel → shared_prompt_log mode DEV (is_private=1) ─────
        try:
            import os as _os

            if _os.environ.get("LAFORGE_ENV", "") == "dev":
                from nokido_agent.app.forge_conv_sanitizer import log_secure

                _sid = (
                    getattr(getattr(app, "context", None), "session_id", None)
                    or getattr(app, "session_name", "")
                    or "default"
                )
                if _sid:
                    log_secure(_sid, "human:tui", user_input, role="user", mode="dev:llm", is_private=1)
        except Exception:
            pass
        asyncio.create_task(app._dispatch_ai(user_input))


# ── _set_agent ──────────────────────────────────────


def _set_agent(app, agent, _from_user: bool = True) -> None:
    """Set agent.

    Args:
        app: Description.
        agent: Description.
        _from_user: Description.
    """
    if not _from_user:
        return
    AgentType = _AgentType()
    AGENT_META = _AGENT_META()
    debug_log = _g("debug_log", lambda **kw: None)

    app.current_agent = agent
    app.agent_selector.set_agent(agent)

    _btn_map = {}
    if AgentType:
        _btn_map = {
            AgentType.CHAT: "btn-agent-chat",
            AgentType.ACTION: "btn-agent-action",
            AgentType.RAG: "btn-agent-rag",
        }
    for _at, _bid in _btn_map.items():
        try:
            from textual.widgets import Button

            _b = app.query_one(f"#{_bid}", Button)
            _b.add_class("-active") if _at == agent else _b.remove_class("-active")
        except Exception:
            pass

    meta = AGENT_META.get(agent, {"color": "#58a6ff", "icon": "💬", "label": "Chat"})
    app._set_status(f"[{meta['color']}]{meta['icon']} {meta['label']}[/] actif")
    try:
        from textual.widgets import Static

        app.query_one("#chat-title", Static).update(
            f" [bold {meta['color']}]{meta['icon']} {meta['label']}[/]  [dim]@help · @run · @rag · @audit · @estim[/]"
        )
    except Exception:
        pass
    try:
        from textual.widgets import Button

        app.query_one("#btn-model", Button).label = f"🤖 {app._current_model()[:18]}"
    except Exception:
        pass
    app._update_sidebar_title()


# ── _check_ollama_models ────────────────────────────


async def poll_tui_notifications(app) -> None:
    """
    Appelé périodiquement par la TUI (ex: every 2s via set_interval).
    Lit les notifications non lues du Hub/LLM et les affiche dans le chat.

    Amélioration 2026-04 : parsing agent-aware.
    Si le message contient un tag `[MARKER AGENT]` ou `[MARKER AGENT resource]`
    en début (ex: `[CLAIM GEMINI tools/video/scenes.py] lecture du fichier...`),
    affiche avec une couleur par agent + une icône par marker.
    Sinon fallback vers l'affichage `🤖 Hub:` générique (comportement historique).

    Markers reconnus : CLAIM, RELEASE, PROPOSE, APPROVE, REJECT, NEED_ADMIN,
                        GRANT, DENY, SYNC, PROGRESS, QUESTION, NOTE.
    Agents reconnus : CLAUDE, GEMINI, ROO, USER, CLINE, CHEF.
    """
    try:
        import sqlite3
        import re as _re
        from pathlib import Path

        _ROOT = Path(__file__).resolve().parent.parent
        _DB = _ROOT / "RAG" / "embeddings.db"

        conn = sqlite3.connect(str(_DB))
        rows = conn.execute(
            "SELECT id, type, message FROM tui_notifications WHERE status='unread' ORDER BY id ASC LIMIT 5"
        ).fetchall()
        if rows:
            ids = [str(r[0]) for r in rows]
            conn.execute(
                "UPDATE tui_notifications SET status='read', read_at=datetime('now') "
                "WHERE id IN (" + ",".join(ids) + ")"
            )
            conn.commit()
        conn.close()

        # Fallback colors par type de notif (historique)
        TYPE_COLOR = {
            "success": "#56d364",
            "error": "#ff7b72",
            "warning": "#e3b341",
            "action": "#d2a8ff",
            "info": "#79c0ff",
        }
        # Couleurs par agent (nouveau)
        AGENT_COLOR = {
            "CLAUDE": "#ff9770",  # corail
            "GEMINI": "#a7c7e7",  # bleu ciel
            "ROO": "#c8b6ff",  # violet
            "USER": "#ffd670",  # jaune
            "CLINE": "#77dd77",  # vert menthe
            "CHEF": "#fbb1bd",  # rose
        }
        # Icones par marker protocolaire (nouveau)
        MARKER_ICON = {
            "CLAIM": "🔒",
            "RELEASE": "🔓",
            "PROPOSE": "💡",
            "APPROVE": "✅",
            "REJECT": "❌",
            "NEED_ADMIN": "🛂",
            "GRANT": "🎫",
            "DENY": "🚫",
            "SYNC": "🔄",
            "PROGRESS": "⏳",
            "QUESTION": "❓",
            "NOTE": "📝",
        }
        # Pattern: [MARKER AGENT] ou [MARKER AGENT resource] en debut de message
        MARKER_RE = _re.compile(
            r"^\s*\[(?P<marker>[A-Z_]+)\s+(?P<agent>[A-Z]+)"
            r"(?:\s+(?P<resource>\S+))?\s*\]\s*(?P<body>.*)$",
            _re.DOTALL,
        )

        from rich.markup import escape as _esc

        for _, ntype, message in rows:
            m = MARKER_RE.match(message or "")
            if m and m.group("marker") in MARKER_ICON and m.group("agent") in AGENT_COLOR:
                # Nouveau format agent-aware
                marker = m.group("marker")
                agent = m.group("agent")
                resource = m.group("resource") or ""
                body = m.group("body").strip()
                icon = MARKER_ICON[marker]
                color = AGENT_COLOR[agent]
                header = f"[bold {color}]{icon} {agent}[/]"
                if marker:
                    header += f" [dim]{marker}[/]"
                if resource:
                    header += f" [italic]{_esc(resource)}[/]"
                if body:
                    app._safe_write(f"{header} {_esc(body)}")
                else:
                    app._safe_write(header)
            else:
                # Fallback historique : par type de notif
                color = TYPE_COLOR.get(ntype, "#79c0ff")
                app._safe_write(f"[{color}]🤖 Hub:[/] {message}")

    except Exception:
        pass


async def _check_ollama_models(app) -> None:
    """Vérifie Ollama + fallback modèle si introuvable."""
    s = _settings()
    if not s:
        return
    try:
        import aiohttp as _aio
    except ImportError:
        app._safe_write("[yellow]⚠ aiohttp manquant — pip install aiohttp[/]")
        return
    try:
        async with _aio.ClientSession() as sess:
            async with sess.get(s.ollama_tags_url, timeout=_aio.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    app._safe_write(f"[red]❌ Ollama HTTP {resp.status}[/]")
                    return
                data = await resp.json()
                models = [m["name"] for m in data.get("models", [])]
                chat_m = [m for m in models if "embed" not in m.lower()]
        if not chat_m:
            app._safe_write("[red]❌ Aucun modèle Ollama — ollama pull mistral[/]")
            return
        forced = s.ollama_model_default or ""
        fallback = forced if forced in models else chat_m[0]
        changed = []
        for attr, lbl in [("model_chat", "💬"), ("model_action", "⚡"), ("model_rag", "🗄")]:
            cur = getattr(app, attr, None)
            if not cur or cur not in models:
                setattr(app, attr, fallback)
                changed.append(f"{lbl}→[green]{fallback}[/]")
        if changed:
            app._safe_write(f"[yellow]⚠ Modèles introuvables — fallback:[/] {' '.join(changed)}")
            app._safe_write(f"[dim]Dispo: {', '.join(chat_m[:5])}[/]")
            app._update_sidebar_title()
        else:
            app._safe_write(f"[green]✅ Ollama[/] 💬{app.model_chat}  ⚡{app.model_action}  🗄{app.model_rag}")
    except _aio.ClientConnectorError:
        app._safe_write("[yellow]⚠ Ollama non joignable — ollama serve[/]")
    except Exception as e:
        app._safe_write(f"[yellow]⚠ Ollama: {escape(str(e)[:80])}[/]")


# ── _select_model ───────────────────────────────────


async def _select_model(app) -> None:
    """Select model.

    Args:
        app: Description.
    """
    s = _settings()
    if not s:
        return
    try:
        import aiohttp as _aio

        async with _aio.ClientSession() as sess:
            async with sess.get(s.ollama_tags_url, timeout=_aio.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                models = [m["name"] for m in data.get("models", []) if "embed" not in m["name"]]
    except Exception:
        models = [m for m in [s.ollama_model_default] if m]

    if not models:
        app._safe_write("[red]❌ Aucun modèle disponible[/]")
        return

    AgentType = _AgentType()
    AGENT_META = _AGENT_META()

    def cb(selected: str) -> None:
        """Cb.

        Args:
            selected: Description.
        """
        if AgentType:
            if app.current_agent == AgentType.CHAT:
                app.model_chat = selected
            elif app.current_agent == AgentType.ACTION:
                app.model_action = selected
            else:
                app.model_rag = selected
        app._set_agent(app.current_agent)
        app._update_sidebar_title()
        save_la = _g("save_last_assignment")
        if save_la:
            save_la(app.model_chat, app.model_action, app.model_rag)
        meta = AGENT_META.get(app.current_agent, {})
        app._safe_write(f"[green]✅ Modèle [bold]{selected}[/] → {meta.get('icon', '?')}[/]")

    ModelScreen = _g("ModelScreen")
    if ModelScreen:
        app.push_screen(ModelScreen(models, app._current_model(), cb))


# ── action_copy_full_log ────────────────────────────


def action_copy_full_log(app) -> None:
    """Action copy full log.

    Args:
        app: Description.
    """
    try:
        from textual.widgets import RichLog

        log = app.query_one("#chat-log", RichLog)
        content = "\n".join(str(l) for l in getattr(log, "_lines", []))
        HAS_CLIPBOARD = _g("HAS_CLIPBOARD", False)
        _pyperclip = _g("_pyperclip")
        if _g("HAS_CLIPBOARD", False) and _pyperclip:
            _pyperclip.copy(content)
            app._clipboard_status("[green]📜 Log copié[/]")
        else:
            app._clipboard_status("[yellow]⚠ pip install pyperclip[/]", 4.0)
    except Exception as e:
        logger.debug(f"action_copy_full_log: {e}")


# ── on_list_view_selected ───────────────────────────


async def on_list_view_selected(app, event) -> None:
    """On list view selected.

    Args:
        app: Description.
        event: Description.
    """
    try:
        item_id = getattr(event.item, "id", "") or ""
        if not item_id or not item_id.startswith("session_"):
            return
        name = item_id[8:]
        _DATA_DIR = _g("_DATA_DIR", Path("data"))
        sf = _DATA_DIR / f"session_{name}.json"
        if not sf.exists():
            return
        data = json.loads(sf.read_text(encoding="utf-8"))
        app._safe_write(f"[bold]Session {name}[/] chargée")
        for msg in data.get("messages", [])[-20:]:
            role = msg.get("role", "?")
            content = msg.get("content", "")[:120]
            color = "#58a6ff" if role == "assistant" else "#79c0ff"
            app._safe_write(f"[{color}][{role}][/] {escape(content)}")
    except Exception as e:
        logger.debug(f"on_list_view_selected: {e}")
