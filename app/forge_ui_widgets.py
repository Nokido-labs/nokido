from __future__ import annotations

# Import oublie, mesure le 2026-09-08 : Callable L489.
from typing import Callable

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_ui_widgets
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_ui_widgets.py — Widgets Textual extraits de Nokido.py (v16.5)
====================================================================
AgentSelector, MetricsPanel, SkillNode, EntropyGauge, SkillTreePanel,
RAGInfoPanel, VSplitter, RoleLightPanel, ConfirmScreen, ModelScreen,
NotificationScreen
"""

import re
from typing import Dict, List
from rich.panel import Panel
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Static
from textual.screen import ModalScreen
from textual import events
from enum import Enum

# Fallback ENTROPY_THRESHOLDS si pas disponible depuis Nokido
ENTROPY_THRESHOLDS = {"green": 0.2, "orange": 0.5, "red": 0.8}

try:
    import faiss
except ImportError:
    faiss = None

from app.core.settings import get_app_attr as _g  # centralisé


# ── Stubs locaux — remplacés au runtime par les vrais depuis Nokido.py ───────────
class AgentType(Enum):
    CHAT = "chat"
    ACTION = "action"
    RAG = "rag"


AGENT_META = {
    AgentType.CHAT: {"icon": "💬", "color": "#58a6ff", "label": "Chat"},
    AgentType.ACTION: {"icon": "⚡", "color": "#f0883e", "label": "Action"},
    AgentType.RAG: {"icon": "🗄", "color": "#3fb950", "label": "RAG"},
}

# ── AgentSelector ─────────────────────────────────────


class AgentSelector(Static):
    current = reactive(AgentType.CHAT)

    def render(self) -> Panel:
        """Render."""
        _meta = _g("AGENT_META", AGENT_META)  # runtime Nokido ou fallback local
        lines = []
        for agent, meta in _meta.items():
            selected = agent == self.current
            style = f"bold {meta['color']}" if selected else "dim"
            prefix = "▶ " if selected else "  "
            lines.append(f"[{style}]{prefix}{meta['icon']} {meta['label']}[/]")
        return Panel("\n".join(lines), title="[bold]Agents[/]", border_style="#30363d")

    def set_agent(self, agent: AgentType) -> None:
        """Set agent.

        Args:
            agent: Description.
        """
        self.current = agent
        self.refresh()


# ── MetricsPanel ──────────────────────────────────────


class MetricsPanel(Static):
    rag_time = reactive(0.0)
    rag_tok = reactive(0)
    llm_time = reactive(0.0)
    llm_tok = reactive(0)
    req_count = reactive(0)
    last_agent = reactive("—")
    last_model = reactive("—")

    def render(self) -> Panel:
        # Essayer de lire les métriques réelles depuis forge_metrics
        """Render."""
        try:
            from nokido_agent.app.forge_metrics import get_collector

            col = get_collector()
            comp = col.compare_providers()
            lines = []
            for prov, stats in comp.items():
                if stats.get("n", 0) == 0:
                    continue
                lat = stats.get("latency_ms", {}).get("avg", 0)
                tps = stats.get("tokens_per_sec", {}).get("avg", 0)
                err = stats.get("errors", 0)
                color = "#3fb950" if err == 0 else "#f0883e"
                lines.append(f"[{color}]{prov:<10}[/] {lat:>6.0f}ms {tps:>6.1f}tok/s")
            content = "\n".join(lines) if lines else "[dim]En attente d'appels LLM…[/]"
            content += f"\n[dim]reqs: {self.req_count}[/]"
        except Exception:
            # Fallback affichage basique
            rag_line = f"RAG: {self.rag_time:.2f}s ({self.rag_tok} tok)"
            llm_line = f"LLM: {self.llm_time:.2f}s ({self.llm_tok} tok)"
            content = f"{rag_line}\n{llm_line}\n[dim]reqs: {self.req_count}[/]"
        return Panel(content, title="[bold #58a6ff]📊 Métriques LLM[/]", border_style="#30363d")

    def update(self, rd=0.0, rt=0, ld=0.0, lt=0, agent=None, model="") -> None:
        """Update.

        Args:
            rd: Description.
            rt: Description.
            ld: Description.
            lt: Description.
            agent: Description.
            model: Description.
        """
        if agent is None:
            agent = _g("AgentType", AgentType).CHAT
        self.rag_time = rd
        self.rag_tok = rt
        self.llm_time = ld
        self.llm_tok = lt
        self.req_count += 1
        self.last_agent = agent.value
        self.last_model = model
        self.refresh()

    def sync_from_collector(self) -> None:
        """Rafraîcht le panel depuis forge_metrics (appelé toutes les 5s dans on_mount)."""
        self.refresh()


# ── SkillNode ─────────────────────────────────────────


class SkillNode(Static):
    """
    Nœud de compétence dans l'arbre des habiletés.
    Couleur dégradée selon qualité : gris(waiting) → bleu(search)
    → orange(learning) → vert(mastered) → violet(verified)
    Affiche le score si disponible.
    """

    status = reactive("waiting")

    ICONS = {"waiting": "⚪", "searching": "🔍", "learning": "🧪", "mastered": "✅", "verified": "🏆"}
    COLORS = {
        "waiting": "#484f58",  # gris — inconnu
        "searching": "#388bfd",  # bleu — en cours
        "learning": "#d29922",  # orange — partiel
        "mastered": "#3fb950",  # vert — acquis
        "verified": "#a371f7",
    }  # violet — vérifié par usage

    def __init__(self, label: str, score: float = 0.0, **kwargs) -> None:
        """Init.

        Args:
            label: Description.
            score: Description.
        """
        super().__init__(**kwargs)
        self._label = label
        self._score = score  # score cosine 0.0→1.0

    def set_score(self, score: float) -> None:
        """Set score.

        Args:
            score: Description.
        """
        self._score = score
        self.refresh()

    def render(self) -> object:
        """Render."""
        from rich.text import Text

        icon = self.ICONS.get(self.status, "⚪")
        color = self.COLORS.get(self.status, "#484f58")
        if self._score > 0:
            bars = int(self._score * 5)
            bar = "█" * bars + "░" * (5 - bars)
            score_str = f" [dim]{bar} {self._score:.2f}[/]"
        else:
            score_str = ""
        return Text.from_markup(f"[{color}]{icon} {self._label[:14]}[/]{score_str}")


# ── EntropyGauge ──────────────────────────────────────


class EntropyGauge(Static):
    """
    Jauge d'entropie RAG — sidebar, au-dessus du SkillTree.
    0-20% vert · 20-50% orange · >80% rouge critique.
    """

    DEFAULT_CSS = """
    EntropyGauge {
        height: 3; border: solid #21262d;
        background: #0d1117; padding: 0 1;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        """Init."""
        super().__init__(*args, **kwargs)
        self._entropy = 0.0

    def refresh_entropy(self, level: float, color: str) -> None:
        """Refresh entropy.

        Args:
            level: Description.
            color: Description.
        """
        self._entropy = level
        pct = int(level * 100)
        filled = int(level * 20)
        empty = 20 - filled
        bar = "[" + color + "]" + "\u2588" * filled + "[/][dim]" + "\u2591" * empty + "[/]"
        if level <= ENTROPY_THRESHOLDS["green"]:
            label = "[green]Saine[/]"
        elif level <= ENTROPY_THRESHOLDS["orange"]:
            label = "[yellow]Maintenance[/]"
        else:
            label = "[bold red]Critique \U0001f6a8[/]"
        self.update(f"[dim]Sant\u00e9 RAG[/] {label}\n{bar} [bold {color}]{pct}%[/]")

    def compose(self) -> ComposeResult:
        """Compose."""
        yield Static("[dim]Sant\u00e9 RAG[/] [green]Saine[/]\n" + "\u2591" * 20 + " 0%")


# ── SkillTreePanel ────────────────────────────────────


class SkillTreePanel(Static):
    """
    Panneau latéral affichant l'arbre de compétences agentic.
    Mis à jour en temps réel par AgenticEngine.ui_callback.
    """

    DEFAULT_CSS = """
    SkillTreePanel {
        height: auto;
        max-height: 12;
        border: solid #21262d;
        background: #0d1117;
        padding: 0 1;
    }
    SkillNode { height: 1; }
    """

    def __init__(self, *args, **kwargs) -> None:
        """Init."""
        super().__init__(*args, **kwargs)
        self._skill_nodes: Dict[str, "SkillNode"] = {}

    def compose(self) -> ComposeResult:
        """Compose."""
        yield Static("[bold #a371f7]🧠 Compétences @disco[/]", id="skill-title")

    def add_or_update(self, name: str, status: str, score: float = 0.0) -> None:
        """Met à jour ou crée un nœud. Appelé depuis AgenticEngine.ui_callback."""
        if name in self._skill_nodes:
            node = self._skill_nodes[name]
            node.status = status
            node.set_score(score)
        else:
            _safe_id = re.sub(r"[^a-zA-Z0-9_-]", "-", name).strip("-") or "x"
            node = SkillNode(name, score=score, id="sk_" + _safe_id)
            node.status = status
            self._skill_nodes[name] = node
            try:
                self.mount(node)
            except Exception:
                pass

    def clear_skills(self) -> None:
        """Clear skills."""
        for node in list(self._skill_nodes.values()):
            try:
                node.remove()
            except Exception:
                pass
        self._skill_nodes.clear()

    def render_summary(self, skills: List[Dict]) -> None:
        """Met à jour en batch depuis get_skill_summary()."""
        for s in skills:
            self.add_or_update(s["name"], s["status"], s.get("score", 0.0))


# ── RAGInfoPanel ──────────────────────────────────────


class RAGInfoPanel(Static):
    chunks = reactive(0)
    faiss_ok = reactive(False)
    bm25_ok = reactive(False)

    def render(self) -> Panel:
        """Render."""
        status = "[green]●[/]" if self.chunks > 0 else "[red]●[/]"
        faiss = "[green]F[/]" if self.faiss_ok else "[dim]F[/]"
        bm25 = "[green]B[/]" if self.bm25_ok else "[dim]B[/]"
        return Panel(
            f"{status} [bold]{self.chunks}[/] chunks  {faiss}/{bm25}",
            title="[bold #3fb950]🗄 RAG[/]",
            border_style="#30363d",
        )

    def sync(self) -> None:
        """Sync."""
        from nokido_agent.app.forge_app_context import app_ctx as _actx

        _ac = _actx()
        rag_engine = _ac.rag_engine
        if rag_engine:
            self.chunks = len(rag_engine.chunks)
            self.faiss_ok = rag_engine.faiss_index is not None
            self.bm25_ok = rag_engine.bm25_index is not None
        self.refresh()


# ── VSplitter ─────────────────────────────────────────


class VSplitter(Widget):
    """Séparateur vertical draggable entre le chat et le terminal.
    Glisse avec la souris pour ajuster la largeur de chaque panneau.
    """

    DEFAULT_CSS = """
    VSplitter {
        width: 1; background: #21262d;
    }
    VSplitter:hover { background: #388bfd40; }
    """
    _dragging: bool = False
    _drag_start_x: int = 0
    _chat_start_w: int = 0
    _term_start_w: int = 0

    def on_mouse_down(self, event) -> None:
        """On mouse down.

        Args:
            event: Description.
        """
        self._dragging = True
        self._drag_start_x = event.screen_x
        try:
            chat_p = self.app.query_one("#chat-panel")
            term_p = self.app.query_one("#terminal-panel")
            self._chat_start_w = chat_p.size.width
            self._term_start_w = term_p.size.width
        except Exception:
            pass
        self.capture_mouse()

    def on_mouse_move(self, event) -> None:
        """On mouse move.

        Args:
            event: Description.
        """
        if not self._dragging:
            return
        delta = event.screen_x - self._drag_start_x
        new_chat = max(20, self._chat_start_w + delta)
        new_term = max(15, self._term_start_w - delta)
        try:
            self.app.query_one("#chat-panel").styles.width = new_chat
            self.app.query_one("#terminal-panel").styles.width = new_term
        except Exception:
            pass

    def on_mouse_up(self, event) -> None:
        """On mouse up.

        Args:
            event: Description.
        """
        self._dragging = False
        self.release_mouse()

    def render(self) -> object:
        """Pas de texte visible — le séparateur est purement visuel."""
        from rich.text import Text

        return Text("")


# ── RoleLightPanel ────────────────────────────────────


class RoleLightPanel(Static):
    """
    Affiche les 12 rôles ops comme des LEDs.
    Appelé par l'orchestrateur pour allumer/éteindre chaque rôle
    en fonction du flux de traitement en cours.
    """

    ROLES_DISPLAY = [
        ("🔍", "analyste", "Analyste", "#58a6ff"),
        ("🐛", "debugger", "Debugger", "#f0883e"),
        ("📋", "planner", "Planner", "#58a6ff"),
        ("🗺", "discovery", "Discovery", "#3fb950"),
        ("⚙", "devops", "DevOps", "#f0883e"),
        ("🌐", "network", "Network", "#79c0ff"),
        ("🔐", "security", "Security", "#ff7b72"),
        ("📊", "log_analysis", "Log Analysis", "#ffa657"),
        ("🗄", "rag", "RAG", "#56d364"),
        ("⚡", "action_exec", "Action/Exec", "#f0883e"),
        ("🧠", "memory", "Memory", "#d2a8ff"),
        ("📈", "monitoring", "Monitoring", "#3fb950"),
    ]

    def __init__(self) -> None:
        """Init."""
        super().__init__()
        self._active: set = set()
        self._rag_active: bool = False

    def render(self) -> Panel:
        """Render."""
        lines = []
        for icon, key, label, color in self.ROLES_DISPLAY:
            active = key in self._active or (key == "rag" and self._rag_active)
            if active:
                # LED allumée : icône + label en couleur vive + fond highlight
                lines.append(f"[bold {color}]● {icon} {label}[/]")
            else:
                # LED éteinte : icône dimmée visible
                lines.append(f"[#3d444d]{icon} {label}[/]")
        return Panel("\n".join(lines), title="[bold #8b949e]Rôles[/]", border_style="#21262d")

    def activate(self, *roles: str) -> None:
        """Activate."""
        for r in roles:
            self._active.add(r)
        self.refresh()

    def deactivate(self, *roles: str) -> None:
        """Deactivate."""
        for r in roles:
            self._active.discard(r)
        self.refresh()

    def set_rag(self, active: bool) -> None:
        """Set rag.

        Args:
            active: Description.
        """
        self._rag_active = active
        self.refresh()

    def reset(self) -> None:
        """Reset."""
        self._active.clear()
        self._rag_active = False
        self.refresh()


# ── ConfirmScreen ─────────────────────────────────────


class ConfirmScreen(ModalScreen):
    def __init__(self, message: str, callback: Callable) -> None:
        """Init.

        Args:
            message: Description.
            callback: Description.
        """
        super().__init__()
        self.message = message
        self.callback = callback

    def compose(self) -> ComposeResult:
        """Compose."""
        with Vertical(id="confirm-box"):
            yield Static(self.message, id="confirm-message")
            yield Static("Appuyez sur [bold]y[/] pour confirmer, [bold]n[/] pour annuler")

    def on_key(self, event: events.Key) -> None:
        """On key.

        Args:
            event: Description.
        """
        if event.key.lower() == "y":
            self.callback(True)
            self.dismiss()
        elif event.key.lower() == "n":
            self.callback(False)
            self.dismiss()


# ── ModelScreen ───────────────────────────────────────


class ModelScreen(ModalScreen):
    CSS = """
    ModelScreen { align: center middle; background: rgba(0,0,0,0.75); }
    #model-box { width: 64; max-height: 30; background: #161b22; border: solid #58a6ff;
                 padding: 1 2; overflow-y: auto; }
    #model-title { color: #58a6ff; text-style: bold; margin-bottom: 1; }
    #model-hint { color: #8b949e; margin-bottom: 1; }
    .model-btn {
        color: #e6edf3;
        background: #21262d;
        border: solid #30363d;
        height: 1;
        margin: 0;
        width: 100%;
    }
    .model-btn:hover {
        background: #2d333b;
        border: solid #58a6ff;
    }
    .model-btn.-selected {
        color: #79c0ff;
        background: #0d2137;
        text-style: bold;
    }
    #model-close { color: #8b949e; background: #21262d; border: solid #30363d;
                   height: 1; margin-top: 1; width: 100%; }
    #model-close:hover { color: #e6edf3; }
    """

    def __init__(self, models: List[str], current: str, callback: Callable) -> None:
        """Init.

        Args:
            models: Description.
            current: Description.
            callback: Description.
        """
        super().__init__()
        self.models = models
        self.current = current
        self.callback = callback

    def compose(self) -> ComposeResult:
        """Compose."""
        with Vertical(id="model-box"):
            yield Static("🤖 Choisissez un modèle", id="model-title")
            yield Static("Cliquez · Échap pour annuler", id="model-hint")
            for i, m in enumerate(self.models):
                parts = m.split(":")
                tag = f" [{parts[1]}]" if len(parts) > 1 else ""
                marker = "▶ " if m == self.current else "  "
                classes = "model-btn -selected" if m == self.current else "model-btn"
                yield Button(f"{marker}{parts[0]}{tag}", id=f"m{i}", classes=classes)
            yield Button("✕ Fermer", id="model-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """On button pressed.

        Args:
            event: Description.
        """
        if event.button.id == "model-close":
            self.dismiss()
            return
        for i, m in enumerate(self.models):
            if event.button.id == f"m{i}":
                self.callback(m)
                self.dismiss()
                return

    def on_key(self, event: events.Key) -> None:
        """On key.

        Args:
            event: Description.
        """
        if event.key == "escape":
            self.dismiss()


# ── NotificationScreen ────────────────────────────────


class NotificationScreen(ModalScreen):
    CSS = """
    NotificationScreen { align: center middle; background: rgba(0,0,0,0.7); }
    #notification-box { width: 54; background: #161b22; border: solid #58a6ff; padding: 1 2; }
    #notification-message { margin-bottom: 1; color: #c9d1d9; }
    """

    def __init__(self, message: str) -> None:
        """Init.

        Args:
            message: Description.
        """
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        """Compose."""
        with Vertical(id="notification-box"):
            yield Static(self.message, id="notification-message")
            yield Button("OK", id="notification-ok", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """On button pressed.

        Args:
            event: Description.
        """
        if event.button.id == "notification-ok":
            self.dismiss()

    def on_key(self, event: events.Key) -> None:
        """On key.

        Args:
            event: Description.
        """
        if event.key == "escape":
            self.dismiss()
