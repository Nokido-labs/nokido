# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_163726_astdoccerb
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0 docs
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""forge_compose.py — DevOpsApp.compose() extrait de Nokido.py (v16.5)"""

from nokido_agent.app import forge_context
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Label, ListView, ListItem, ProgressBar, RichLog, Static

from app.core.settings import get_app_attr as _g  # centralisé


def compose(self) -> ComposeResult:
    """Compose."""
    # Résoudre les globals Nokido — compose() tourne dans le scope de forge_compose
    _vm = forge_context.get_version_manager()
    try:
        from nokido_agent.app.forge_version import get_from_manager as _gfv

        _ver = _gfv(_vm)
    except Exception:
        _ver = _g("__version__", "0.13.0")
    AutocompleteInput = _g("AutocompleteInput")
    VSplitter = _g("VSplitter")
    EntropyGauge = _g("EntropyGauge")
    app = self  # self = instance DevOpsApp

    yield Header(show_clock=True)
    with Horizontal(id="main-layout"):
        with Vertical(id="sidebar"):
            yield Static("[bold #58a6ff]⛒ La Forge[/]", id="orc-title")
            yield Static(f"[dim]v{_ver} · {app.session_name[:12]}[/]", id="orc-version")
            yield Static("[bold #8b949e]Agents[/]", classes="sb-section-label")
            yield Button("💬 Chat", id="btn-agent-chat", classes="agent-btn")
            yield Button("⚡ Action", id="btn-agent-action", classes="agent-btn")
            yield Button("🗄 RAG", id="btn-agent-rag", classes="agent-btn")
            yield Button("🤖 Modèle", id="btn-model", classes="sb-btn")
            yield Static("[bold #8b949e]Orchestrateur[/]", classes="sb-section-label")
            yield Button("🤖 Autonome", id="btn-mode-autonome", classes="mode-btn -active")
            yield Button("🤝 Collab", id="btn-mode-collaboration", classes="mode-btn")
            yield Button("⚖  Comité", id="btn-mode-comite", classes="mode-btn")
            yield Static("─" * 20, classes="sb-sep")
            yield app.role_panel
            yield Static("─" * 20, classes="sb-sep")
            yield app.rag_info
            yield Static("─" * 20, classes="sb-sep")
            if EntropyGauge:
                yield EntropyGauge(id="entropy-gauge")
            yield Static("", id="staging-indicator")
            yield app.skill_panel
            yield app.metrics
            yield Static("[dim]Sessions:[/]", id="sess-label")
            yield ListView(
                *[ListItem(Label(f"📁 {s}"), id=f"session_{s}") for s in app._saved_sessions()], id="session-list"
            )
            yield Button("📂 RAG dir", id="btn-rag-open", classes="sb-btn")
            yield Static("", id="prog-label")
            yield ProgressBar(total=100, show_eta=False, id="rag-prog")

        with Horizontal(id="center-layout"):
            with Vertical(id="chat-panel"):
                with Horizontal(id="chat-title-bar"):
                    yield Static(
                        " [bold #58a6ff]⛒ La Forge[/]  [dim]@help · @run · @rag · @audit · @estim[/]", id="chat-title"
                    )
                    yield Label("📋", id="btn-copy-reply", classes="copy-btn")
                    yield Label("📜", id="btn-copy-log", classes="copy-btn")
                yield RichLog(id="chat-log", wrap=True, markup=True, auto_scroll=True)
                yield Static("", id="ai-status")
                yield Static("", id="no-ssh-banner")
                with Vertical(id="input-bar"):
                    if AutocompleteInput:
                        yield AutocompleteInput(placeholder="Message… (@help | numéro suggestion)", id="chat-input")
                    else:
                        from textual.widgets import Input

                        yield Input(placeholder="Message…", id="chat-input")
            if VSplitter:
                yield VSplitter(id="v-splitter", classes="hidden")
            else:
                yield Static("", id="v-splitter", classes="hidden")
            with Vertical(id="terminal-panel"):
                yield Static(" [bold #3fb950]🖥 SSH[/]  [dim]Ctrl+T · focus[/]", id="term-title")
                yield app.terminal
    yield Footer()
