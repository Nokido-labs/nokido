"""
forge_desktop/widgets/debate_timeline.py
=========================================
DebateTimeline — v17.04-RT
Affiche les tours du débat en cascade séquentielle.
VRAM Focus Monitor — alerte si >80% utilisé.
Intervention R0 Trigger — bouton urgence Ring0.
"""
from __future__ import annotations
import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QProgressBar,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor

AGENT_COLORS = {
    "laforge":    "#2196f3",
    "llamacpp":   "#ff9800",
    "llamacpp_2": "#f44336",
    "gemini":     "#4caf50",
    "CLAUDE":     "#00bcd4",
    "groq":       "#ff5722",
    "deepseek":   "#795548",
    "mistral":    "#607d8b",
    "SYSTEM":     "#9e9e9e",
}

def _agent_color(agent_id: str) -> str:
    for k, v in AGENT_COLORS.items():
        if k.lower() in agent_id.lower():
            return v
    return "#888"


# ── Bulle de tour ─────────────────────────────────────────────────────────────
class _TurnBubble(QFrame):
    def __init__(self, agent_id: str, text: str, turn_n: int,
                 elapsed_ms: int = 0, parent=None):
        super().__init__(parent)
        col = _agent_color(agent_id)
        self.setStyleSheet(
            f"QFrame {{ background:#0d0d0d; border-left:3px solid {col};"
            " border-radius:4px; margin:2px 0; }}"
        )
        lo = QVBoxLayout(self)
        lo.setContentsMargins(10, 6, 10, 6)
        lo.setSpacing(3)

        hdr = QHBoxLayout()
        agent_lbl = QLabel(f"[T{turn_n}] {agent_id}")
        agent_lbl.setStyleSheet(f"color:{col}; font-size:10px; font-weight:600;")
        hdr.addWidget(agent_lbl)
        hdr.addStretch()
        if elapsed_ms:
            time_lbl = QLabel(f"{elapsed_ms}ms")
            time_lbl.setStyleSheet("color:#444; font-size:9px;")
            hdr.addWidget(time_lbl)
        ts_lbl = QLabel(time.strftime("%H:%M:%S"))
        ts_lbl.setStyleSheet("color:#333; font-size:9px;")
        hdr.addWidget(ts_lbl)
        lo.addLayout(hdr)

        content = QLabel(text[:400] + ("…" if len(text)>400 else ""))
        content.setWordWrap(True)
        content.setStyleSheet("color:#c2c0b6; font-size:11px; line-height:1.4;")
        lo.addWidget(content)


# ── VRAM Monitor ──────────────────────────────────────────────────────────────
class _VRAMMonitor(QWidget):
    vram_critical = Signal(float)  # % VRAM

    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(6)

        lo.addWidget(QLabel("VRAM"))
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(8)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(
            "QProgressBar{background:#111;border:none;border-radius:4px;}"
            "QProgressBar::chunk{background:#2196f3;border-radius:4px;}"
        )
        lo.addWidget(self._bar, 1)

        self._val_lbl = QLabel("—")
        self._val_lbl.setStyleSheet("color:#888; font-size:10px; min-width:40px;")
        lo.addWidget(self._val_lbl)

        # Refresh toutes les 2s
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)

    def _refresh(self):
        pct = self._read_vram_pct()
        self._bar.setValue(int(pct))
        self._val_lbl.setText(f"{pct:.0f}%")
        # Couleur selon seuil
        if pct > 80:
            chunk_color = "#f44336"
            self.vram_critical.emit(pct)
        elif pct > 60:
            chunk_color = "#ff9800"
        else:
            chunk_color = "#2196f3"
        self._bar.setStyleSheet(
            "QProgressBar{background:#111;border:none;border-radius:4px;}"
            f"QProgressBar::chunk{{background:{chunk_color};border-radius:4px;}}"
        )

    def _read_vram_pct(self) -> float:
        try:
            import subprocess
            r = subprocess.run(
                ["nvidia-smi","--query-gpu=memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=2
            )
            if r.returncode == 0:
                used, total = r.stdout.strip().split(",")
                return 100 * int(used.strip()) / max(1, int(total.strip()))
        except Exception:
            pass
        # Fallback : estimation depuis psutil GPU ou iGPU AMD
        try:
            import subprocess
            r = subprocess.run(
                ["wmic","path","Win32_VideoController","get",
                 "AdapterRAM,CurrentRefreshRate","/format:csv"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=2
            )
            return 0.0
        except Exception:
            return 0.0


# ── Widget principal ──────────────────────────────────────────────────────────
class DebateTimeline(QWidget):
    """
    Timeline séquentielle des tours de débat.
    VRAM Focus Monitor — seuil 80% → alerte.
    Ring0 Trigger — bouton urgence interruption.
    """
    r0_triggered  = Signal(str)   # message d'urgence
    turn_received = Signal(str, str, int)  # agent, text, turn

    def __init__(self, parent=None):
        super().__init__(parent)
        self._turns: list[_TurnBubble] = []
        self._turn_count = 0
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setSpacing(4)
        lo.setContentsMargins(0, 0, 0, 0)

        # Header avec VRAM monitor et R0 trigger
        hdr = QHBoxLayout()

        title = QLabel("⏱  Debate Timeline")
        title.setStyleSheet("font-size:12px; font-weight:600; color:#c2c0b6;")
        hdr.addWidget(title)

        hdr.addStretch()

        self._vram = _VRAMMonitor()
        self._vram.vram_critical.connect(self._on_vram_critical)
        self._vram.setFixedWidth(160)
        hdr.addWidget(self._vram)

        # Ring0 Trigger
        self._r0_btn = QPushButton("R0 ⚡ Intervenir")
        self._r0_btn.setFixedHeight(24)
        self._r0_btn.setStyleSheet(
            "background:#2a0505; border:1px solid #f44336; color:#f44336;"
            " border-radius:4px; padding:2px 8px; font-size:10px; font-weight:600;"
        )
        self._r0_btn.clicked.connect(self._on_r0_trigger)
        self._r0_btn.setEnabled(False)
        hdr.addWidget(self._r0_btn)

        # Bouton clear
        btn_clear = QPushButton("✕")
        btn_clear.setFixedSize(22, 22)
        btn_clear.setStyleSheet(
            "background:#1a1a1a; border:1px solid #444; color:#666;"
            " border-radius:3px;"
        )
        btn_clear.clicked.connect(self.clear_timeline)
        hdr.addWidget(btn_clear)

        lo.addLayout(hdr)

        # Zone scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{background:#0a0a0a; border:1px solid #1a1a1a; border-radius:4px;}"
        )
        self._container = QWidget()
        self._container_lo = QVBoxLayout(self._container)
        self._container_lo.setSpacing(2)
        self._container_lo.setContentsMargins(4, 4, 4, 4)
        self._container_lo.addStretch()
        scroll.setWidget(self._container)
        lo.addWidget(scroll, 1)
        self._scroll = scroll

        # Status bar
        self._status_lbl = QLabel("En attente…")
        self._status_lbl.setStyleSheet("color:#444; font-size:10px;")
        lo.addWidget(self._status_lbl)

    def add_turn(self, agent_id: str, text: str,
                 elapsed_ms: int = 0):
        """Ajoute un tour en cascade."""
        self._turn_count += 1
        bubble = _TurnBubble(agent_id, text, self._turn_count, elapsed_ms)
        # Insérer avant le stretch
        self._container_lo.insertWidget(
            self._container_lo.count() - 1, bubble
        )
        self._turns.append(bubble)
        # Scroll vers le bas
        QTimer.singleShot(50, lambda:
            self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()
            )
        )
        self._r0_btn.setEnabled(True)
        self._status_lbl.setText(
            f"Tour {self._turn_count} — {agent_id}"
        )
        self._status_lbl.setStyleSheet(
            f"color:{_agent_color(agent_id)}; font-size:10px;"
        )
        self.turn_received.emit(agent_id, text, self._turn_count)

    def set_done(self, summary: str, ok: bool = True):
        """Marque la fin du débat."""
        self._r0_btn.setEnabled(False)
        col = "#4caf50" if ok else "#f44336"
        self._status_lbl.setText(
            f"{'DONE' if ok else 'ERR'} — {self._turn_count} tours — {summary}"
        )
        self._status_lbl.setStyleSheet(f"color:{col}; font-size:10px; font-weight:600;")

    def clear_timeline(self):
        for b in self._turns:
            b.deleteLater()
        self._turns.clear()
        self._turn_count = 0
        self._r0_btn.setEnabled(False)
        self._status_lbl.setText("En attente…")
        self._status_lbl.setStyleSheet("color:#444; font-size:10px;")

    def _on_vram_critical(self, pct: float):
        self._status_lbl.setText(
            f"⚠ VRAM {pct:.0f}% — R0 disponible"
        )
        self._status_lbl.setStyleSheet("color:#ff9800; font-size:10px; font-weight:600;")
        self._r0_btn.setEnabled(True)

    def _on_r0_trigger(self):
        msg = f"R0_INTERRUPT — VRAM critique à {time.strftime('%H:%M:%S')}"
        self._status_lbl.setText(f"⚡ {msg}")
        self._status_lbl.setStyleSheet("color:#f44336; font-size:10px; font-weight:700;")
        self._r0_btn.setEnabled(False)
        self.r0_triggered.emit(msg)
