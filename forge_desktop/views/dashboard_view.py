"""
forge_desktop/views/dashboard_view.py — Tableau de bord holistique
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QLabel, QProgressBar, QGroupBox, QScrollArea,
    QPlainTextEdit, QFrame, QPushButton,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont

from forge_desktop.widgets.node_graph import NodeGraphWidget

DARK = ("background:#0a0a0a; color:#4caf50;"
        " font-family:'Cascadia Code','Consolas'; font-size:11px;"
        " border:1px solid #333; border-radius:4px;")

KIND_COLORS = {
    "local_llm":  "#3b6d11",
    "remote_llm": "#185fa5",
    "agent":      "#993c1d",
}


class LLMCard(QFrame):
    """Carte d'un LLM dans le Rail des Cerveaux."""

    def __init__(self, pid: str, participant: dict, parent=None):
        super().__init__(parent)
        self.pid = pid
        self.setFrameShape(QFrame.StyledPanel)
        col = KIND_COLORS.get(participant.get("kind",""), "#333")
        self.setStyleSheet(
            f"QFrame {{ background:#111; border:1px solid {col};"
            " border-radius:6px; padding:6px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setSpacing(3)
        layout.setContentsMargins(6,6,6,6)

        row = QHBoxLayout()
        self._icon  = QLabel(participant.get("icon","🤖"))
        self._lbl   = QLabel(participant.get("label", pid)[:18])
        self._lbl.setStyleSheet("font-size:11px; font-weight:500;")
        self._state = QLabel("IDLE")
        self._state.setStyleSheet("font-size:10px; color:#4caf50;")
        row.addWidget(self._icon)
        row.addWidget(self._lbl)
        row.addStretch()
        row.addWidget(self._state)
        layout.addLayout(row)

        self._vram_lbl = QLabel("VRAM : --")
        self._vram_lbl.setStyleSheet("font-size:9px; color:#666;")
        layout.addWidget(self._vram_lbl)

        self._vram_bar = QProgressBar()
        self._vram_bar.setRange(0, 100)
        self._vram_bar.setFixedHeight(5)
        self._vram_bar.setStyleSheet(
            "QProgressBar { border:none; background:#1a1a1a; border-radius:2px; }"
            "QProgressBar::chunk { background:#4caf50; border-radius:2px; }"
        )
        layout.addWidget(self._vram_bar)

        self._tok_lbl = QLabel("tokens/s : --")
        self._tok_lbl.setStyleSheet("font-size:9px; color:#666;")
        layout.addWidget(self._tok_lbl)

    def update(self, state: str, vram_mb: int = 0, tokens_s: float = 0.0):
        STATE_COLORS = {
            "IDLE": "#4caf50", "THINKING": "#ff9800",
            "STREAMING": "#2196f3", "SYNCING_RAG": "#9c27b0",
        }
        self._state.setText(state)
        self._state.setStyleSheet(
            "font-size:10px; color:" + STATE_COLORS.get(state,"#888") + ";"
        )
        if vram_mb:
            self._vram_lbl.setText(f"VRAM : {vram_mb} MB")
            self._vram_bar.setValue(min(100, vram_mb // 40))
        if tokens_s:
            self._tok_lbl.setText(f"tokens/s : {tokens_s:.1f}")


class BrainRailWidget(QWidget):
    """Colonne gauche — état de santé de chaque LLM."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(210)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6,6,6,6)
        layout.setSpacing(4)

        title = QLabel("🧠 Rail des Cerveaux")
        title.setStyleSheet("font-weight:600; font-size:13px; color:#c2c0b6;")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setSpacing(5)
        self._inner_layout.addStretch()
        scroll.setWidget(self._inner)
        layout.addWidget(scroll)
        self._cards: dict[str, LLMCard] = {}

    def update_participants(self, participants: list, vram_info: dict):
        ids = {p.get("id","") for p in participants}
        for pid in list(self._cards.keys()):
            if pid not in ids:
                card = self._cards.pop(pid)
                self._inner_layout.removeWidget(card)
                card.deleteLater()
        for p in participants:
            pid = p.get("id","")
            if not pid:
                continue
            if pid not in self._cards:
                card = LLMCard(pid, p)
                self._cards[pid] = card
                self._inner_layout.insertWidget(
                    self._inner_layout.count()-1, card)
            else:
                vram_mb  = int(p.get("vram_mb", 0) or 0)
                tokens_s = float(p.get("tokens_s", 0.0) or 0.0)
                self._cards[pid].update(
                    p.get("state","IDLE"), vram_mb, tokens_s
                )

    def set_node_state(self, node_id: str, state: str):
        if node_id in self._cards:
            self._cards[node_id].update(state)


class TruthTerminalWidget(QWidget):
    """Console brute des events swarm et appels MCP."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6,6,6,6)

        title = QLabel("⚡ Terminal de Vérité")
        title.setStyleSheet("font-weight:600; font-size:13px; color:#c2c0b6;")
        layout.addWidget(title)

        self._console = QPlainTextEdit()
        self._console.setReadOnly(True)
        self._console.setMaximumBlockCount(300)
        self._console.setStyleSheet(DARK)
        layout.addWidget(self._console)

        btn = QPushButton("Vider")
        btn.clicked.connect(self._console.clear)
        btn.setStyleSheet(
            "background:#1a1a1a; border:1px solid #333; border-radius:4px;"
            " padding:2px 8px; font-size:11px; color:#888;"
        )
        layout.addWidget(btn)

    def append_event(self, ev: dict):
        ts    = str(ev.get("ts",""))[:19]
        etype = ev.get("type","?")
        agent = ev.get("agent","")
        tgt   = ev.get("target","")
        line  = f"[{ts}] {etype}"
        if agent: line += f" ← {agent}"
        if tgt:   line += f" → {tgt}"
        self._console.appendPlainText(line)

    def append_raw(self, text: str):
        self._console.appendPlainText(text)


class DashboardView(QWidget):
    """
    Vue principale : BrainRail | NodeGraph | TruthTerminal
    """
    node_hot_swap = Signal(str, str)
    node_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4,4,4,4)
        layout.setSpacing(4)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(3)

        self.brain_rail = BrainRailWidget()
        splitter.addWidget(self.brain_rail)

        self.graph = NodeGraphWidget()
        self.graph.hot_swap_requested.connect(self.node_hot_swap)
        self.graph.node_clicked.connect(self.node_selected)
        splitter.addWidget(self.graph)

        self.terminal = TruthTerminalWidget()
        splitter.addWidget(self.terminal)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        layout.addWidget(splitter)

    def update_hub_data(self, data: dict):
        team = data.get("team", {})
        if team.get("active_count", 0) > 0:
            self.graph.load_team({"participants": team.get("active", [])})
