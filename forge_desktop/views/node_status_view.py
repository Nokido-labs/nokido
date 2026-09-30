"""
forge_desktop/views/node_status_view.py
========================================
WORKFLOW_NODE_INTEGRATION — UI override
Remove_Chat_Bubbles_Enable_Node_Status

Pipeline view : trigger → ADR_CHECK → RUNNING → DONE/FAILED/BLOCKED
Status par node. Pas de chat. MMap polling.
"""
from __future__ import annotations
import asyncio
import copy
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
APP  = ROOT / "app"

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QGroupBox,
    QScrollArea, QFrame, QSizePolicy, QTextEdit,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QColor, QFont

# ── Palette statuts ───────────────────────────────────────────────────────────
STATUS_CFG = {
    "IDLE":      {"color": "#444",     "label": "IDLE",       "bg": "#111"},
    "PENDING":   {"color": "#ff9800",  "label": "PENDING",    "bg": "#1a1200"},
    "ADR_CHECK": {"color": "#2196f3",  "label": "ADR CHECK",  "bg": "#001524"},
    "RUNNING":   {"color": "#00bcd4",  "label": "RUNNING",    "bg": "#001a1a"},
    "DONE":      {"color": "#4caf50",  "label": "DONE",       "bg": "#001a00"},
    "FAILED":    {"color": "#f44336",  "label": "FAILED",     "bg": "#1a0000"},
    "BLOCKED":   {"color": "#9c27b0",  "label": "BLOCKED",    "bg": "#110018"},
}

# ── Node Card ─────────────────────────────────────────────────────────────────
class NodeCard(QFrame):
    """Carte visuelle d'un noeud pipeline."""

    def __init__(self, node_id: str, label: str = "", parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self._status = "IDLE"
        self.setFixedHeight(72)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._build()
        self.set_status("IDLE")

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 6, 12, 6)
        lo.setSpacing(3)

        hdr = QHBoxLayout()
        self._id_lbl = QLabel(self.node_id)
        self._id_lbl.setStyleSheet("color:#888; font-size:9px; font-family:'Cascadia Code';")
        hdr.addWidget(self._id_lbl)
        hdr.addStretch()
        self._status_lbl = QLabel("IDLE")
        self._status_lbl.setStyleSheet(
            "font-size:10px; font-weight:600; padding:1px 6px;"
            " border-radius:3px; font-family:'Cascadia Code';"
        )
        hdr.addWidget(self._status_lbl)
        lo.addLayout(hdr)

        self._detail_lbl = QLabel("—")
        self._detail_lbl.setStyleSheet(
            "color:#666; font-size:11px; font-family:'Cascadia Code';"
        )
        lo.addWidget(self._detail_lbl)

        self._meta_lbl = QLabel("")
        self._meta_lbl.setStyleSheet("color:#444; font-size:9px;")
        lo.addWidget(self._meta_lbl)

    def set_status(self, status: str, detail: str = "", meta: str = ""):
        self._status = status
        cfg = STATUS_CFG.get(status, STATUS_CFG["IDLE"])
        self.setStyleSheet(
            f"QFrame {{ background:{cfg['bg']}; border:1px solid {cfg['color']}44;"
            " border-radius:6px; margin:2px 0; }}"
        )
        self._status_lbl.setText(cfg["label"])
        self._status_lbl.setStyleSheet(
            f"font-size:10px; font-weight:600; padding:1px 6px;"
            f" border-radius:3px; background:{cfg['color']}22;"
            f" color:{cfg['color']}; font-family:'Cascadia Code';"
        )
        if detail:
            self._detail_lbl.setText(detail[:80])
        if meta:
            self._meta_lbl.setText(meta)


# ── Turn Row (résultat d'un participant) ──────────────────────────────────────
class TurnRow(QFrame):
    def __init__(self, agent_id: str, ok: bool, chars: int,
                 elapsed_ms: int, parent=None):
        super().__init__(parent)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(8, 2, 8, 2)
        lo.setSpacing(8)

        status_icon = "✓" if ok else "✗"
        status_col  = "#4caf50" if ok else "#f44336"

        icon_lbl = QLabel(status_icon)
        icon_lbl.setStyleSheet(f"color:{status_col}; font-weight:700; font-size:12px;")
        icon_lbl.setFixedWidth(16)
        lo.addWidget(icon_lbl)

        agent_lbl = QLabel(agent_id)
        agent_lbl.setStyleSheet("color:#c2c0b6; font-size:11px; font-family:'Cascadia Code';")
        agent_lbl.setFixedWidth(120)
        lo.addWidget(agent_lbl)

        chars_lbl = QLabel(f"{chars} chars")
        chars_lbl.setStyleSheet("color:#555; font-size:10px;")
        lo.addWidget(chars_lbl)

        lo.addStretch()

        ms_lbl = QLabel(f"{elapsed_ms}ms")
        ms_lbl.setStyleSheet("color:#333; font-size:10px;")
        lo.addWidget(ms_lbl)

        self.setStyleSheet("background:#0d0d0d; border-radius:3px;")


# ── Worker pipeline ───────────────────────────────────────────────────────────
class _PipelineWorker(QThread):
    node_status = Signal(str, str, str, str)  # node_id, status, detail, meta
    turn_done   = Signal(str, bool, int, int)  # agent, ok, chars, ms
    pipeline_done = Signal(dict)

    def __init__(self, task: str, agents: list, context: str, parent=None):
        super().__init__(parent)
        self._task    = task
        self._agents  = agents
        self._context = context

    def run(self):
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        try:
            from forge_pipeline_node import PipelineNode, NodeStatus
            node = PipelineNode("ui_node")

            # Monkey-patch MMap pour émettre les signaux
            orig_write = node._mmap.write_node_status
            def _patched_write(nid, status, data=None):
                orig_write(nid, status, data)
                detail = ""
                if data:
                    detail = " | ".join(f"{k}={str(v)[:20]}" for k,v in list(data.items())[:3])
                self.node_status.emit(nid, status.value, detail, "")
            node._mmap.write_node_status = _patched_write

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(
                node.execute(self._task, self._agents, self._context, "UI")
            )
            loop.close()

            # Émettre les tours
            for turn in result.turns:
                self.turn_done.emit(
                    turn.get("participant_id","?"),
                    turn.get("ok", False),
                    len(str(turn.get("response",""))),
                    turn.get("duration_ms", 0),
                )

            self.pipeline_done.emit(result.to_dict())

        except Exception as e:
            import traceback
            self.pipeline_done.emit({
                "status": "FAILED",
                "error": str(e)[:300],
                "turns": 0,
            })


# ── Vue principale ────────────────────────────────────────────────────────────
class NodeStatusView(QWidget):
    """
    Vue pipeline — Node Status.
    Pas de chat bubbles. Status nodes + turn rows.
    Trigger manuel ou API.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._node_cards: dict[str, NodeCard] = {}
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(6)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("⬡  Pipeline Node — Sequential_Batch")
        title.setStyleSheet("font-size:14px; font-weight:600; color:#c2c0b6;")
        hdr.addWidget(title)
        hdr.addStretch()
        self._run_badge = QLabel("IDLE")
        self._run_badge.setStyleSheet(
            "background:#111; color:#444; font-size:10px; font-weight:600;"
            " padding:2px 8px; border-radius:4px; border:1px solid #333;"
            " font-family:'Cascadia Code';"
        )
        hdr.addWidget(self._run_badge)
        lo.addLayout(hdr)

        # Config trigger
        cfg_grp = QGroupBox("Trigger")
        cfg_grp.setStyleSheet(
            "QGroupBox { border:1px solid #222; border-radius:6px;"
            " margin-top:6px; color:#555; padding-top:4px; }"
        )
        cfg_lo = QVBoxLayout(cfg_grp)
        cfg_lo.setSpacing(4)

        # Task input
        self._task_input = QTextEdit()
        self._task_input.setFixedHeight(56)
        self._task_input.setPlaceholderText("Task payload…")
        self._task_input.setStyleSheet(
            "background:#0d0d0d; color:#c2c0b6; border:1px solid #222;"
            " border-radius:4px; padding:4px; font-size:11px;"
            " font-family:'Cascadia Code';"
        )
        cfg_lo.addWidget(self._task_input)

        # Agents row
        agents_row = QHBoxLayout()
        agents_lbl = QLabel("Agents:")
        agents_lbl.setStyleSheet("color:#666; font-size:11px;")
        agents_row.addWidget(agents_lbl)
        self._agents_input = QLineEdit("nokido,llamacpp")
        self._agents_input.setStyleSheet(
            "background:#0d0d0d; color:#c2c0b6; border:1px solid #222;"
            " border-radius:4px; padding:3px 6px; font-size:11px;"
            " font-family:'Cascadia Code';"
        )
        agents_row.addWidget(self._agents_input, 1)

        self._trigger_sel = QComboBox()
        self._trigger_sel.addItems(["API_Call","FS_Event","MCP_Call","Manual"])
        self._trigger_sel.setStyleSheet(
            "background:#0d0d0d; color:#c2c0b6; border:1px solid #222;"
            " border-radius:4px; padding:2px 6px; font-size:11px;"
        )
        self._trigger_sel.setFixedWidth(100)
        agents_row.addWidget(self._trigger_sel)
        cfg_lo.addLayout(agents_row)

        # Boutons
        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("▶  Execute Pipeline")
        self._run_btn.setFixedHeight(32)
        self._run_btn.setStyleSheet(
            "background:#0a1a0a; border:1px solid #4caf50; color:#4caf50;"
            " border-radius:4px; font-size:12px; font-weight:600;"
            " font-family:'Cascadia Code';"
        )
        self._run_btn.clicked.connect(self._execute)

        self._abort_btn = QPushButton("⏹  Abort")
        self._abort_btn.setFixedHeight(32)
        self._abort_btn.setEnabled(False)
        self._abort_btn.setStyleSheet(
            "background:#1a0000; border:1px solid #f4433655; color:#f4433688;"
            " border-radius:4px; font-size:11px;"
        )
        self._abort_btn.clicked.connect(self._abort)

        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._abort_btn)
        cfg_lo.addLayout(btn_row)
        lo.addWidget(cfg_grp)

        # Pipeline nodes
        nodes_grp = QGroupBox("Node Status")
        nodes_grp.setStyleSheet(
            "QGroupBox { border:1px solid #222; border-radius:6px;"
            " margin-top:6px; color:#555; padding-top:4px; }"
        )
        nodes_lo = QVBoxLayout(nodes_grp)
        nodes_lo.setSpacing(2)

        for nid, label in [
            ("trigger",   "Trigger"),
            ("adr_check", "Ring2 ADR Check"),
            ("running",   "Pipeline Execution"),
            ("result",    "Result"),
        ]:
            card = NodeCard(nid, label)
            self._node_cards[nid] = card
            nodes_lo.addWidget(card)
        lo.addWidget(nodes_grp)

        # Turns output
        turns_grp = QGroupBox("Batch Results")
        turns_grp.setStyleSheet(
            "QGroupBox { border:1px solid #222; border-radius:6px;"
            " margin-top:6px; color:#555; padding-top:4px; }"
        )
        self._turns_lo = QVBoxLayout(turns_grp)
        self._turns_lo.setSpacing(2)
        self._turns_lo.setContentsMargins(4, 6, 4, 4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(160)
        scroll.setStyleSheet(
            "QScrollArea { background:#0a0a0a; border:none; }"
        )
        self._turns_container = QWidget()
        self._turns_inner = QVBoxLayout(self._turns_container)
        self._turns_inner.setSpacing(2)
        self._turns_inner.setContentsMargins(2, 2, 2, 2)
        self._turns_inner.addStretch()
        scroll.setWidget(self._turns_container)
        self._turns_lo.addWidget(scroll)
        self._scroll = scroll
        lo.addWidget(turns_grp)

    # ── Execute ───────────────────────────────────────────────────────────────

    def _execute(self):
        task = self._task_input.toPlainText().strip()
        if not task:
            return
        if self._worker and self._worker.isRunning():
            return

        agents = [a.strip() for a in self._agents_input.text().split(",") if a.strip()]
        source = self._trigger_sel.currentText()

        # Reset nodes
        for card in self._node_cards.values():
            card.set_status("IDLE")

        # Vider turns
        while self._turns_inner.count() > 1:
            item = self._turns_inner.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._node_cards["trigger"].set_status("PENDING",
            f"{source} → {','.join(agents)}", task[:40])

        self._run_btn.setEnabled(False)
        self._abort_btn.setEnabled(True)
        self._set_badge("RUNNING")

        self._worker = _PipelineWorker(task, agents, "", parent=self)
        self._worker.node_status.connect(self._on_node_status)
        self._worker.turn_done.connect(self._on_turn)
        self._worker.pipeline_done.connect(self._on_done)
        self._worker.start()

    def _abort(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
        for card in self._node_cards.values():
            card.set_status("IDLE")
        self._set_badge("IDLE")
        self._run_btn.setEnabled(True)
        self._abort_btn.setEnabled(False)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_node_status(self, node_id: str, status: str,
                        detail: str, meta: str):
        STATUS_TO_CARD = {
            "PENDING":   "trigger",
            "ADR_CHECK": "adr_check",
            "RUNNING":   "running",
            "DONE":      "result",
            "FAILED":    "result",
            "BLOCKED":   "adr_check",
        }
        card_key = STATUS_TO_CARD.get(status)
        if card_key and card_key in self._node_cards:
            self._node_cards[card_key].set_status(status, detail, meta)
        self._set_badge(status)

    def _on_turn(self, agent_id: str, ok: bool, chars: int, ms: int):
        row = TurnRow(agent_id, ok, chars, ms)
        self._turns_inner.insertWidget(self._turns_inner.count()-1, row)
        QTimer.singleShot(50, lambda:
            self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()
            )
        )

    def _on_done(self, result: dict):
        status = result.get("status", "DONE")
        turns  = result.get("turns", 0)
        err    = result.get("error", "")
        self._node_cards["result"].set_status(
            status,
            f"{turns} turns | {result.get('elapsed_ms',0)}ms",
            err[:60] if err else result.get("session_id","")[:30],
        )
        self._set_badge(status)
        self._run_btn.setEnabled(True)
        self._abort_btn.setEnabled(False)

    def _set_badge(self, status: str):
        cfg = STATUS_CFG.get(status, STATUS_CFG["IDLE"])
        self._run_badge.setText(cfg["label"])
        self._run_badge.setStyleSheet(
            f"background:{cfg['bg']}; color:{cfg['color']}; font-size:10px;"
            f" font-weight:600; padding:2px 8px; border-radius:4px;"
            f" border:1px solid {cfg['color']}44; font-family:'Cascadia Code';"
        )
