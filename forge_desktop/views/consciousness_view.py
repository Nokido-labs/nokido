"""
forge_desktop/views/consciousness_view.py
==========================================
Vue "Conscience Émanente" — Forge-Sync OS

Affiche en temps réel :
  1. Pensée en cours de chaque agent (streaming MMap 60fps)
  2. Filtre de résonance — drift score + ADR déclenchés
  3. Journal ADR — Architecture Decision Records
  4. Timestamp synchronizer — historique des propositions

La GUI lit live_bridge.map via MMapPollerWorker (déjà actif).
Aucun appel réseau dans cette vue — tout est MMap ou DB locale.
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

from forge_desktop.widgets.ring_o_meter import RingOMeterWidget, RING_META

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QTextEdit, QPlainTextEdit, QProgressBar,
    QGroupBox, QScrollArea, QFrame, QPushButton,
    QTabWidget, QLineEdit, QComboBox, QDialog,
    QDialogButtonBox, QFormLayout,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont

ROOT = Path(__file__).resolve().parent.parent.parent
DB   = ROOT / "sandbox" / "events.db"

DARK = ("background:#0a0a0a; color:#c2c0b6;"
        " font-family:'Cascadia Code','Consolas'; font-size:11px;"
        " border:1px solid #333; border-radius:4px;")

STATE_COLORS = {
    "IDLE":      "#444",
    "THINKING":  "#ff9800",
    "STREAMING": "#2196f3",
    "WAITING":   "#9c27b0",
    "ERROR":     "#f44336",
}

ACTION_COLORS = {
    "pass":    "#4caf50",
    "warn":    "#ff9800",
    "correct": "#f44336",
    "block":   "#ff1744",
}


# ── Panel "pensée en cours" d'un agent ───────────────────────────────────────

class AgentThinkingCard(QFrame):
    def __init__(self, agent_id: str, parent=None):
        super().__init__(parent)
        self.agent_id = agent_id
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background:#111; border:1px solid #333;"
            " border-radius:6px; padding:4px; }"
        )
        layout = QVBoxLayout(self)
        layout.setSpacing(3)
        layout.setContentsMargins(6,6,6,6)

        # Header
        hdr = QHBoxLayout()
        self._state_lbl = QLabel("⭕")
        self._state_lbl.setStyleSheet("font-size:14px;")
        self._id_lbl    = QLabel(agent_id)
        self._id_lbl.setStyleSheet("font-weight:600; font-size:12px; color:#c2c0b6;")
        self._tok_lbl   = QLabel("0 tok/s")
        self._tok_lbl.setStyleSheet("font-size:10px; color:#666;")
        hdr.addWidget(self._state_lbl)
        hdr.addWidget(self._id_lbl)
        hdr.addStretch()
        hdr.addWidget(self._tok_lbl)
        layout.addLayout(hdr)

        # Task
        self._task_lbl = QLabel("")
        self._task_lbl.setStyleSheet("font-size:10px; color:#666; font-style:italic;")
        layout.addWidget(self._task_lbl)

        # Barre progress
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setFixedHeight(4)
        self._bar.setStyleSheet(
            "QProgressBar { border:none; background:#1a1a1a; border-radius:2px; }"
            "QProgressBar::chunk { background:#2196f3; border-radius:2px; }"
        )
        layout.addWidget(self._bar)

        # Texte de pensée (streaming)
        self._thinking = QPlainTextEdit()
        self._thinking.setReadOnly(True)
        self._thinking.setMaximumHeight(90)
        self._thinking.setStyleSheet(DARK + "font-size:10px;")
        layout.addWidget(self._thinking)

    def update(self, data: dict):
        state    = data.get("state", "IDLE")
        thinking = data.get("thinking", "")
        task     = data.get("task", "")
        progress = int(data.get("progress", 0) or 0)
        tokens_s = float(data.get("tokens_s", 0) or 0)

        col = STATE_COLORS.get(state, "#444")
        icons = {
            "IDLE":      "⭕",
            "THINKING":  "🟡",
            "STREAMING": "🔵",
            "WAITING":   "🟣",
            "ERROR":     "🔴",
        }
        self._state_lbl.setText(icons.get(state, "⭕"))
        self._id_lbl.setStyleSheet(f"font-weight:600; font-size:12px; color:{col};")
        self._task_lbl.setText(task[:60] if task else "")
        self._bar.setValue(progress)
        self._tok_lbl.setText(f"{tokens_s:.1f} tok/s" if tokens_s > 0 else "")

        # Mise à jour texte streaming (seulement si changé)
        current = self._thinking.toPlainText()
        if thinking and thinking != current:
            self._thinking.setPlainText(thinking)
            # Scroll en bas
            sb = self._thinking.verticalScrollBar()
            sb.setValue(sb.maximum())


# ── Panel Résonance ───────────────────────────────────────────────────────────

class ResonancePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4,4,4,4)
        layout.setSpacing(4)

        title = QLabel("🔬 Filtre de Résonance")
        title.setStyleSheet("font-weight:600; font-size:13px; color:#c2c0b6;")
        layout.addWidget(title)

        # Drift score
        row = QHBoxLayout()
        row.addWidget(QLabel("Dérive :"))
        self._drift_bar = QProgressBar()
        self._drift_bar.setRange(0, 100)
        self._drift_bar.setFixedHeight(12)
        self._drift_bar.setStyleSheet(
            "QProgressBar { border:none; background:#1a1a1a; border-radius:3px; }"
            "QProgressBar::chunk { background:#ff9800; border-radius:3px; }"
        )
        self._drift_val = QLabel("0%")
        self._drift_val.setFixedWidth(36)
        row.addWidget(self._drift_bar)
        row.addWidget(self._drift_val)
        layout.addLayout(row)

        # Action badge
        badge_row = QHBoxLayout()
        badge_row.addWidget(QLabel("Action :"))
        self._action_lbl = QLabel("pass")
        self._action_lbl.setStyleSheet("color:#4caf50; font-weight:600;")
        badge_row.addWidget(self._action_lbl)
        badge_row.addStretch()
        self._agent_lbl = QLabel("")
        self._agent_lbl.setStyleSheet("font-size:10px; color:#666;")
        badge_row.addWidget(self._agent_lbl)
        layout.addLayout(badge_row)

        # Log des corrections
        layout.addWidget(QLabel("Corrections injectées :"))
        self._corrections = QPlainTextEdit()
        self._corrections.setReadOnly(True)
        self._corrections.setMaximumBlockCount(100)
        self._corrections.setStyleSheet(DARK + "font-size:10px;")
        layout.addWidget(self._corrections)

    def update_resonance(self, data: dict):
        drift  = float(data.get("drift_score", 0) or 0)
        action = data.get("last_action", "pass") or "pass"
        agent  = data.get("last_agent", "") or ""

        pct = int(drift * 100)
        col = ACTION_COLORS.get(action, "#4caf50")
        chunk_col = {
            "pass":    "#4caf50",
            "warn":    "#ff9800",
            "correct": "#f44336",
            "block":   "#ff1744",
        }.get(action, "#4caf50")

        self._drift_bar.setValue(pct)
        self._drift_bar.setStyleSheet(
            "QProgressBar { border:none; background:#1a1a1a; border-radius:3px; }"
            f"QProgressBar::chunk {{ background:{chunk_col}; border-radius:3px; }}"
        )
        self._drift_val.setText(f"{pct}%")
        self._action_lbl.setText(action.upper())
        self._action_lbl.setStyleSheet(f"color:{col}; font-weight:600;")
        self._agent_lbl.setText(agent)

        if action in ("correct", "block", "warn") and agent:
            import time
            ts = time.strftime("%H:%M:%S")
            self._corrections.appendPlainText(
                f"[{ts}] {action.upper()} {agent} drift={pct}%"
            )


# ── Panel ADR ─────────────────────────────────────────────────────────────────

class ADRPanel(QWidget):
    adr_created = Signal(str)   # adr_id

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4,4,4,4)
        layout.setSpacing(4)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("📋 Architecture Decision Records")
        title.setStyleSheet("font-weight:600; font-size:13px; color:#c2c0b6;")
        hdr.addWidget(title)
        hdr.addStretch()
        new_btn = QPushButton("+ Nouvel ADR")
        new_btn.setStyleSheet(
            "background:#1a2a1a; border:1px solid #4caf50; color:#4caf50;"
            " border-radius:4px; padding:3px 10px; font-size:11px;"
        )
        new_btn.clicked.connect(self._create_adr_dialog)
        hdr.addWidget(new_btn)
        layout.addLayout(hdr)

        # Filtre status
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filtre :"))
        self._status_filter = QComboBox()
        self._status_filter.addItems(["Tous","Accepté","Proposé","Obsolète"])
        self._status_filter.setStyleSheet(
            "background:#111; color:#c2c0b6; border:1px solid #444; font-size:11px;"
        )
        self._status_filter.currentTextChanged.connect(self._load_adrs)
        filter_row.addWidget(self._status_filter)
        filter_row.addStretch()
        self._count_lbl = QLabel("0 ADR")
        self._count_lbl.setStyleSheet("font-size:10px; color:#666;")
        filter_row.addWidget(self._count_lbl)
        layout.addLayout(filter_row)

        # Liste ADR
        self._adr_scroll = QScrollArea()
        self._adr_scroll.setWidgetResizable(True)
        self._adr_inner = QWidget()
        self._adr_layout = QVBoxLayout(self._adr_inner)
        self._adr_layout.setSpacing(4)
        self._adr_layout.addStretch()
        self._adr_scroll.setWidget(self._adr_inner)
        layout.addWidget(self._adr_scroll)

        self._load_adrs()

    def _load_adrs(self):
        # Vider
        while self._adr_layout.count() > 1:
            item = self._adr_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            conn  = sqlite3.connect(str(DB), timeout=5)
            filt  = self._status_filter.currentText()
            query = ("SELECT adr_id,title,status,decision,consequences_neg,ring "
                     "FROM adr_records"
                     + ("" if filt == "Tous" else f" WHERE status='{filt}'")
                     + " ORDER BY ring, id")
            rows = conn.execute(query).fetchall()
            conn.close()

            self._count_lbl.setText(f"{len(rows)} ADR")
            for r in rows:
                card = self._make_adr_card(r)
                self._adr_layout.insertWidget(self._adr_layout.count()-1, card)
        except Exception as e:
            lbl = QLabel("Erreur: " + str(e)[:60])
            self._adr_layout.insertWidget(0, lbl)

    def _make_adr_card(self, row: tuple) -> QFrame:
        adr_id, title, status, decision, cons_neg, ring = row
        STATUS_COLORS = {
            "Accepté":   "#4caf50",
            "Proposé":   "#ff9800",
            "Obsolète":  "#666",
            "Supersédé": "#9c27b0",
        }
        col = STATUS_COLORS.get(status, "#888")

        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setStyleSheet(
            f"QFrame {{ background:#111; border-left:3px solid {col};"
            " border-radius:4px; padding:4px; }}"
        )
        cl = QVBoxLayout(card)
        cl.setSpacing(2)
        cl.setContentsMargins(6,4,6,4)

        # Header
        h = QHBoxLayout()
        id_lbl = QLabel(adr_id)
        id_lbl.setStyleSheet(f"font-weight:700; color:{col}; font-size:11px;")
        title_lbl = QLabel(title[:55])
        title_lbl.setStyleSheet("font-size:11px; color:#c2c0b6;")
        ring_lbl = QLabel(f"ring={ring}")
        ring_lbl.setStyleSheet("font-size:9px; color:#555;")
        h.addWidget(id_lbl)
        h.addWidget(title_lbl)
        h.addStretch()
        h.addWidget(ring_lbl)
        cl.addLayout(h)

        # Décision
        dec = QLabel(decision[:120] + ("…" if len(decision) > 120 else ""))
        dec.setStyleSheet("font-size:10px; color:#888; font-family:'Cascadia Code';")
        dec.setWordWrap(True)
        cl.addWidget(dec)

        # Conséquences négatives (en rouge)
        if cons_neg:
            neg = QLabel("⚠ " + cons_neg[:80])
            neg.setStyleSheet("font-size:9px; color:#f44336;")
            neg.setWordWrap(True)
            cl.addWidget(neg)

        return card

    def _create_adr_dialog(self):
        dlg = ADRCreateDialog(self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            import sys
            if str(ROOT / "app") not in sys.path:
                sys.path.insert(0, str(ROOT / "app"))
            try:
                from forge_resonance_filter import create_adr
                adr_id = create_adr(**data)
                self.adr_created.emit(adr_id)
                self._load_adrs()
            except Exception as e:
                pass

    def refresh(self):
        self._load_adrs()


class ADRCreateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouvel ADR")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._title   = QLineEdit()
        self._context = QTextEdit(); self._context.setMaximumHeight(60)
        self._dec     = QTextEdit(); self._dec.setMaximumHeight(60)
        self._pos     = QLineEdit()
        self._neg     = QLineEdit()
        self._tags    = QLineEdit(); self._tags.setPlaceholderText("tag1,tag2")
        self._ring    = QComboBox(); self._ring.addItems(["0","1","2","3"])
        self._ring.setCurrentIndex(1)

        for lbl, w in [
            ("Titre*", self._title),
            ("Contexte*", self._context),
            ("Décision*", self._dec),
            ("Conséquences+", self._pos),
            ("Conséquences-", self._neg),
            ("Tags", self._tags),
            ("Ring", self._ring),
        ]:
            form.addRow(lbl, w)
        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_data(self) -> dict:
        tags = [t.strip() for t in self._tags.text().split(",") if t.strip()]
        return {
            "title":            self._title.text(),
            "context":          self._context.toPlainText(),
            "decision":         self._dec.toPlainText(),
            "consequences_pos": self._pos.text(),
            "consequences_neg": self._neg.text(),
            "tags":             tags,
            "ring":             int(self._ring.currentText()),
        }


# ── Vue principale Conscience ─────────────────────────────────────────────────

class ConsciousnessView(QWidget):
    """
    Vue complète : agents en cours + résonance + ADR + timestamps.
    Mise à jour depuis MMapPollerWorker via signaux.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6,6,6,6)

        title = QLabel("🧠  Conscience Émanente — Pensée en cours")
        title.setStyleSheet("font-size:14px; font-weight:600; color:#c2c0b6;")
        layout.addWidget(title)

        splitter = QSplitter(Qt.Horizontal)

        # Gauche : agents thinking (60fps via MMap)
        left = QWidget()
        left.setMinimumWidth(350)
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(4)
        left_layout.setContentsMargins(0,0,0,0)
        lbl = QLabel("Agents actifs")
        lbl.setStyleSheet("font-size:11px; color:#666; font-weight:600;")
        left_layout.addWidget(lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._agents_widget = QWidget()
        self._agents_layout = QVBoxLayout(self._agents_widget)
        self._agents_layout.setSpacing(5)
        self._agents_layout.addStretch()
        scroll.setWidget(self._agents_widget)
        left_layout.addWidget(scroll)
        splitter.addWidget(left)

        self._agent_cards: dict[str, AgentThinkingCard] = {}

        # Centre : résonance
        self._resonance = ResonancePanel()
        splitter.addWidget(self._resonance)

        # Droite : ADR
        self._adr_panel = ADRPanel()
        splitter.addWidget(self._adr_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        layout.addWidget(splitter)

        # Ring-O-Meter — sous le splitter principal
        rom_label = QLabel("⚙  Ring-O-Meter — Intégrité des rings")
        rom_label.setStyleSheet("font-size:12px; font-weight:600; color:#c2c0b6; margin-top:8px;")
        layout.addWidget(rom_label)
        self._ring_o_meter = RingOMeterWidget()
        self._ring_o_meter.setFixedHeight(200)
        self._ring_o_meter.ring_selected.connect(self._on_ring_selected)
        layout.addWidget(self._ring_o_meter)

    def update_agents(self, agents_data: dict):
        """Appelé par MMapPollerWorker — données fraîches depuis mmap."""
        known  = set(self._agent_cards.keys())
        active = set(agents_data.keys())

        # Créer les cartes manquantes
        for aid in active - known:
            card = AgentThinkingCard(aid)
            self._agent_cards[aid] = card
            self._agents_layout.insertWidget(
                self._agents_layout.count()-1, card)

        # Mettre à jour
        for aid, data in agents_data.items():
            if aid in self._agent_cards:
                self._agent_cards[aid].update(data)

        # Supprimer les agents disparus (IDLE depuis > 30s)
        for aid in known - active:
            card = self._agent_cards.pop(aid)
            self._agents_layout.removeWidget(card)
            card.deleteLater()

    def update_resonance(self, resonance_data: dict):
        self._resonance.update_resonance(resonance_data)
        # Propager au Ring-O-Meter en temps réel
        self._ring_o_meter.update_from_resonance(resonance_data)

    def _on_ring_selected(self, ring_id: int, info: dict):
        meta  = RING_META.get(ring_id, {})
        state = info.get('state', 'ok')
        last  = info.get('last_event', '')
        self._resonance._corrections.appendPlainText(
            f"Ring {ring_id} ({meta.get('desc','?')}) — {state.upper()}"
            + (f" — {last}" if last else "")
        )

    def refresh_adrs(self):
        self._adr_panel.refresh()
