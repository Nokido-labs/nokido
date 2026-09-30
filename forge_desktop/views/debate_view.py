"""
forge_desktop/views/debate_view.py — Thread de Débat augmenté
==============================================================
Ajouts v2 (suggestions Gemini intégrées proprement) :
  - MiniRingMeter  : indicateur visuel Ring 2-4 par agent
  - EntropyBar     : fil d'Ariane anti-pourrissement (Ring 4)
  - Bouton Actionner : appel LaForgeMCPBridge depuis synthèse
  - Sentinelle Ring 2-3 vérifiée dans _launch_debate
  - Inspecteur Ring 4 mis à jour à chaque _on_turn

Règles câblage Qt conservées :
  - self._worker stocké (GC-safe)
  - connect() AVANT start()
  - Tous les slots définis dans la classe
  - Attributs publics QTest préservés
"""
from __future__ import annotations
import math
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QLabel, QPlainTextEdit, QTextEdit, QPushButton,
    QLineEdit, QComboBox, QGroupBox, QProgressBar,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QTimer, QRectF
from PySide6.QtGui import QColor, QTextCharFormat, QPainter, QPen

DARK = ("background:#0a0a0a; color:#c2c0b6;"
        " font-family:'Cascadia Code','Consolas'; font-size:12px;"
        " border:1px solid #333; border-radius:4px;")

STATE_COLORS = {
    "IDLE":      "#666",
    "THINKING":  "#ff9800",
    "STREAMING": "#2196f3",
    "DONE":      "#4caf50",
    "ERROR":     "#f44336",
}

# Couleurs Ring par état
RING_COLORS = {
    "ok":    "#4caf50",
    "warn":  "#ff9800",
    "block": "#f44336",
}


# ── MiniRingMeter ─────────────────────────────────────────────────────────────

class MiniRingMeter(QWidget):
    """
    Indicateur circulaire 20×20 px — Ring 2-4 par agent.
    Vert = OK | Orange pulse = Inspecteur R4 alerte | Rouge = Sentinelle R2 bloque.
    L'arc représente le niveau de confiance : plein = sain, vide = critique.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.setToolTip("Ring-O-Meter agent")
        self._state     = "ok"      # "ok" | "warn" | "block"
        self._ring      = 10        # ring courant (10=sain, 0=critique)
        self._pulse_t   = 0.0

        # Timer pulse animation (warn/block uniquement)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(60)

    def _tick(self):
        if self._state != "ok":
            self._pulse_t = (self._pulse_t + 0.15) % (2 * math.pi)
            self.update()

    def set_state(self, state: str, ring: int = 10):
        """state = 'ok' | 'warn' | 'block' | 'pass'"""
        state = {"pass": "ok", "correct": "warn"}.get(state, state)
        self._state = state if state in RING_COLORS else "ok"
        self._ring  = max(0, min(10, ring))
        self._pulse_t = 0.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        base_color = RING_COLORS[self._state]
        col = QColor(base_color)

        # Pulse alpha pour warn/block
        if self._state != "ok":
            alpha = int(160 + 95 * math.sin(self._pulse_t))
            col.setAlpha(alpha)

        pen = QPen(col, 2.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)

        # Fond gris discret
        p.setPen(QPen(QColor("#333"), 1.5))
        p.drawEllipse(QRectF(3, 3, 16, 16))

        # Arc proportionnel au ring — ring 0 = arc plein (danger), ring 10 = arc vide (sain)
        # On inverse : ring 10 = cercle complet vert = tout va bien
        p.setPen(QPen(col, 2.5))
        span = int(360 * (self._ring / 10) * 16)
        p.drawArc(QRectF(3, 3, 16, 16), 90 * 16, -span)


# ── EntropyBar ────────────────────────────────────────────────────────────────

class EntropyBar(QWidget):
    """
    Fil d'Ariane — barre d'entropie sémantique (Ring 4).
    100% = contexte sain | 0% = pourrissement critique.
    Se vide à chaque conflit détecté par l'Inspecteur.
    Bouton Reset déclenche context_rollback.
    """

    rollback_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(6)

        icon = QLabel("R4")
        icon.setStyleSheet("color:#888; font-size:10px; font-weight:600; min-width:20px;")
        lo.addWidget(icon)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(100)
        self._bar.setFixedHeight(8)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(self._bar_style(100))
        lo.addWidget(self._bar)

        self._label = QLabel("Contexte sain")
        self._label.setStyleSheet("color:#4caf50; font-size:10px; min-width:110px;")
        lo.addWidget(self._label)

        self._btn_reset = QPushButton("Défaire les fils")
        self._btn_reset.setVisible(False)
        self._btn_reset.setStyleSheet(
            "background:#2a1010; border:1px solid #f44336; color:#f44336;"
            " border-radius:4px; padding:2px 8px; font-size:10px;"
        )
        self._btn_reset.clicked.connect(self.rollback_requested)
        lo.addWidget(self._btn_reset)

    def _bar_style(self, value: int) -> str:
        if value > 60:
            chunk = "#4caf50"
        elif value > 30:
            chunk = "#ff9800"
        else:
            chunk = "#f44336"
        return (
            "QProgressBar { background:#111; border:none; border-radius:4px; }"
            f"QProgressBar::chunk {{ background:{chunk}; border-radius:4px; }}"
        )

    def update_entropy(self, entropy_pct: float):
        """entropy_pct : 0.0=pourrissement 100.0=sain."""
        val = max(0, min(100, int(entropy_pct)))
        self._bar.setValue(val)
        self._bar.setStyleSheet(self._bar_style(val))

        if val > 60:
            self._label.setText("Contexte sain")
            self._label.setStyleSheet("color:#4caf50; font-size:10px; min-width:110px;")
            self._btn_reset.setVisible(False)
        elif val > 30:
            self._label.setText("Dérive détectée")
            self._label.setStyleSheet("color:#ff9800; font-size:10px; min-width:110px;")
            self._btn_reset.setVisible(True)
        else:
            self._label.setText("Pourrissement R4 !")
            self._label.setStyleSheet("color:#f44336; font-size:10px; font-weight:600; min-width:110px;")
            self._btn_reset.setVisible(True)


# ── AgentPanel augmenté ───────────────────────────────────────────────────────

class AgentPanel(QGroupBox):
    """Panneau agent avec MiniRingMeter intégré en haut à droite."""

    def __init__(self, agent_id: str, color: str, role: str, parent=None):
        super().__init__(agent_id, parent)
        self.agent_id = agent_id
        self.color    = color
        self.setStyleSheet(
            f"QGroupBox {{ border:2px solid {color}; border-radius:6px;"
            f" margin-top:8px; color:{color}; font-weight:600; }}"
        )
        lo = QVBoxLayout(self)
        lo.setContentsMargins(6, 8, 6, 6)

        # Header : rôle + MiniRingMeter
        header = QHBoxLayout()
        role_lbl = QLabel(role, styleSheet=f"color:{color}; font-size:11px;")
        header.addWidget(role_lbl)
        header.addStretch()
        self.ring_meter = MiniRingMeter()
        self.ring_meter.setToolTip("Sentinelle R2-3 / Inspecteur R4")
        header.addWidget(self.ring_meter)
        lo.addLayout(header)

        self._text = QTextEdit(readOnly=True, styleSheet=DARK)
        self._text.setMinimumHeight(180)
        lo.addWidget(self._text)

        self._status = QLabel("IDLE", styleSheet="color:#666; font-size:10px;")
        lo.addWidget(self._status)

    def append_message(self, text: str, is_conflict: bool = False):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#f44336" if is_conflict else self.color))
        cur = self._text.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(text + "\n\n", fmt)
        self._text.setTextCursor(cur)
        self._text.ensureCursorVisible()

    def set_status(self, status: str):
        col = STATE_COLORS.get(status, self.color)
        self._status.setText(status)
        self._status.setStyleSheet(f"color:{col}; font-size:10px; font-weight:600;")

    def set_ring(self, state: str, ring: int = 10):
        """Mise à jour du MiniRingMeter."""
        self.ring_meter.set_state(state, ring)

    def clear(self):
        self._text.clear()
        self.set_status("IDLE")
        self.ring_meter.set_state("ok", 10)


# ── SynthesisPanel augmenté ───────────────────────────────────────────────────

class SynthesisPanel(QGroupBox):
    """Zone centrale — synthèse + bouton Actionner (OneMCP) + entrée."""

    submit_clicked  = Signal(str)
    action_clicked  = Signal(str)   # synthèse → MCP bridge

    def __init__(self, parent=None):
        super().__init__("Synthétiseur", parent)
        self.setStyleSheet(
            "QGroupBox { border:2px solid #9c27b0; border-radius:6px;"
            " margin-top:8px; color:#9c27b0; font-weight:600; }"
        )
        lo = QVBoxLayout(self)
        lo.setContentsMargins(6, 8, 6, 6)

        self._synthesis = QTextEdit(readOnly=True, styleSheet=DARK)
        self._synthesis.setMinimumHeight(140)
        lo.addWidget(self._synthesis)

        # Bouton Actionner — appelle LaForgeMCPBridge avec la synthèse
        self._btn_act = QPushButton("⚡  Actionner via MCP")
        self._btn_act.setEnabled(False)
        self._btn_act.setToolTip("Envoie la synthèse au serveur MCP Nokido")
        self._btn_act.setStyleSheet(
            "background:#0a1a2a; border:1px solid #2196f3; color:#2196f3;"
            " border-radius:4px; padding:4px 10px; font-size:11px;"
        )
        self._btn_act.clicked.connect(self._on_act)
        lo.addWidget(self._btn_act)

        self.input_field = QLineEdit()
        self.input_field.setObjectName("debate_input")
        self.input_field.setPlaceholderText("Tâche à débattre…")
        self.input_field.setStyleSheet(
            "background:#111; border:1px solid #555; border-radius:4px;"
            " padding:5px 8px; color:#c2c0b6; font-size:12px;"
        )
        lo.addWidget(self.input_field)

        ctrl = QHBoxLayout()
        self.agent_sel = QComboBox()
        self.agent_sel.addItems([
            "nokido + llamacpp",
            "nokido + gemini",
            "llamacpp seul",
        ])
        self.agent_sel.setStyleSheet(
            "background:#111; color:#c2c0b6; border:1px solid #444;"
            " border-radius:4px; padding:3px 6px; font-size:11px;"
        )
        self.btn_start = QPushButton("▶  Débattre")
        self.btn_start.setObjectName("btn_debate_start")
        self.btn_start.setStyleSheet(
            "background:#1a0a2a; border:1px solid #9c27b0; color:#9c27b0;"
            " border-radius:4px; padding:5px 14px; font-size:12px; font-weight:600;"
        )
        self.btn_start.clicked.connect(self._on_click)
        self.input_field.returnPressed.connect(self._on_click)

        ctrl.addWidget(self.agent_sel)
        ctrl.addStretch()
        ctrl.addWidget(self.btn_start)
        lo.addLayout(ctrl)

    def _on_click(self):
        task = self.input_field.text().strip()
        if task:
            self.submit_clicked.emit(task)

    def _on_act(self):
        text = self._synthesis.toPlainText().strip()
        if text:
            self.action_clicked.emit(text)

    def set_synthesis(self, text: str):
        self._synthesis.setPlainText(text)
        # Activer Actionner seulement si contenu non vide
        self._btn_act.setEnabled(bool(text.strip()) and text != "Génération en cours…")

    def get_agents(self) -> list:
        combos = {
            "nokido + llamacpp": ["laforge", "llamacpp"],
            "nokido + gemini":   ["laforge", "gemini"],
            "llamacpp seul":      ["llamacpp", "llamacpp"],
        }
        return combos.get(self.agent_sel.currentText(), ["laforge", "llamacpp"])


# ── DebateView principal ──────────────────────────────────────────────────────

class DebateView(QWidget):
    """
    Vue Thread de Débat augmentée.
    Attributs publics QTest : input_field, btn_start, output_area.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._worker         = None   # GC-safe
        self._entropy        = 100.0  # 100=sain, 0=pourri
        self._session_id     = "debate_" + str(id(self))
        self._mcp_worker     = None   # GC-safe pour MCPWorker
        self._turn_counter   = 0       # alternance panneaux agents identiques

        lo = QVBoxLayout(self)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(6)

        lo.addWidget(QLabel(
            "⚖  Thread de Débat — Collaboration multi-agents",
            styleSheet="font-size:14px; font-weight:600; color:#c2c0b6;"
        ))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)

        self._planner = AgentPanel("Planificateur", "#2196f3", "Propose des solutions")
        self._synth   = SynthesisPanel()
        self._critic  = AgentPanel("Critique",      "#f44336", "Identifie les risques")

        splitter.addWidget(self._planner)
        splitter.addWidget(self._synth)
        splitter.addWidget(self._critic)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        lo.addWidget(splitter)

        # Fil d'Ariane
        self._entropy_bar = EntropyBar()
        lo.addWidget(self._entropy_bar)

        self.output_area = QPlainTextEdit()
        self.output_area.setObjectName("debate_output")
        self.output_area.setReadOnly(True)
        self.output_area.setMaximumHeight(100)
        self.output_area.setStyleSheet(DARK + " font-size:11px;")
        self.output_area.setPlaceholderText("Terminal MCP…")
        lo.addWidget(self.output_area)

        ctrl = QHBoxLayout()
        self._btn_clear  = QPushButton("Vider")
        self._btn_cancel = QPushButton("Annuler")
        self._btn_cancel.setEnabled(False)
        for b in (self._btn_clear, self._btn_cancel):
            b.setStyleSheet(
                "background:#1a1a1a; border:1px solid #444; border-radius:4px;"
                " padding:3px 10px; font-size:11px; color:#888;"
            )
        ctrl.addWidget(self._btn_clear)
        ctrl.addWidget(self._btn_cancel)
        ctrl.addStretch()
        lo.addLayout(ctrl)

        # ── Connexions — UNE SEULE FOIS dans __init__ ───────────────────────
        self._synth.submit_clicked.connect(self._launch_debate)
        self._synth.action_clicked.connect(self._on_action_mcp)
        self._entropy_bar.rollback_requested.connect(self._on_rollback)
        self._btn_clear.clicked.connect(self._clear_all)
        self._btn_cancel.clicked.connect(self._cancel)

        # Raccourcis QTest
        self.input_field = self._synth.input_field
        self.btn_start   = self._synth.btn_start

    # ── Lancement ─────────────────────────────────────────────────────────────

    def _launch_debate(self, task: str):
        if self._worker and self._worker.isRunning():
            self.output_area.appendPlainText("[WARN] Débat déjà en cours")
            return

        # ── Sentinelle Ring 2-3 ──────────────────────────────────────────────
        try:
            from forge_sentinel import validate_action
            result = validate_action(task, tool_name="debate_launch",
                                     agent_id="UI_USER")
            if not result.allowed:
                self.output_area.appendPlainText(f"[SENTINEL R{result.ring_violated}] {result.message}")
                self._planner.append_message(result.message, is_conflict=True)
                self._planner.set_ring("block", result.ring_violated)
                self._critic.set_ring("block", result.ring_violated)
                return
            if result.action == "warn":
                self.output_area.appendPlainText(f"[SENTINEL WARN] {result.message}")
                self._planner.set_ring("warn", result.ring_violated)
                self._critic.set_ring("warn", result.ring_violated)
        except ImportError:
            pass   # Sentinelle non disponible — continuer

        agents = self._synth.get_agents()
        self._session_id = "debate_" + str(int(__import__("time").time()))
        self.output_area.appendPlainText(
            f"[DEBATE] {agents[0]} ↔ {agents[1]} — {task[:60]}"
        )
        self._synth.set_synthesis("Génération en cours…")
        self._planner.set_status("THINKING")
        self._critic.set_status("THINKING")
        self._planner.set_ring("ok", 10)
        self._critic.set_ring("ok", 10)
        self._synth.btn_start.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        # Reset entropie + compteur tours
        self._entropy = 100.0
        self._turn_counter = 0
        self._entropy_bar.update_entropy(100.0)

        try:
            from forge_desktop.core.llm_interactions import DebateWorker
        except ImportError as e:
            self.output_area.appendPlainText("[ERR] " + str(e)[:80])
            self._reset_ui()
            return

        # 1. Instanciation GC-safe
        self._worker = DebateWorker(task, agents, parent=self)

        # 2. Connexions AVANT start()
        self._worker.turn_ready.connect(self._on_turn)
        self._worker.synthesis_ready.connect(self._on_synthesis)
        self._worker.debate_done.connect(self._on_done)
        self._worker.error_signal.connect(self._on_error)

        # 3. start() EN DERNIER
        self._worker.start()
        self.output_area.appendPlainText(f"[MCP] DebateWorker.start() agents={agents}")

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_turn(self, agent_id: str, text: str, is_conflict: bool):
        """Reçoit chaque tour + met à jour Inspecteur R4."""
        # Routing par rôle émis dans le texte (ex: "[Planificateur] ...")
        # Fallback : premier agent = planificateur
        agents = self._synth.get_agents()
        is_planner = (
            "[Planificateur]" in text
            or "[Validateur]" in text
            or agent_id == agents[0]
            or "planner" in agent_id.lower()
        )
        is_critic = (
            "[Critique]" in text
            or "critic" in agent_id.lower()
        )
        # Si les deux agents sont identiques, alterner : pair=planificateur, impair=critique
        if agents[0] == agents[1]:
            turn_n = getattr(self, "_turn_counter", 0)
            self._turn_counter = turn_n + 1
            is_planner = (turn_n % 2 == 0)
            is_critic = not is_planner

        if is_planner and not is_critic:
            self._planner.append_message(text, is_conflict)
            self._planner.set_status("DONE")
            self._critic.set_status("THINKING")
        else:
            self._critic.append_message(text, is_conflict)
            self._critic.set_status("DONE")

        # ── Inspecteur Ring 4 ────────────────────────────────────────────────
        try:
            from forge_inspector import get_inspector
            insp   = get_inspector(self._session_id)
            result = insp.add_response(agent_id, text)

            drift   = result.get("drift", 0.0)
            action  = result.get("action", "pass")
            entropy = max(0.0, 100.0 * (1.0 - drift))

            self._entropy = entropy
            self._entropy_bar.update_entropy(entropy)

            if action == "rollback":
                ring = max(1, int(drift * 10))
                self._planner.set_ring("block", ring)
                self._critic.set_ring("block",  ring)
                self.output_area.appendPlainText(
                    f"[R4-INSPECTEUR] Pourrissement drift={drift:.2f} — Nettoyage suggéré"
                )
                # Bouton Annuler en rouge
                self._btn_cancel.setStyleSheet(
                    "background:#2a1010; border:1px solid #f44336; color:#f44336;"
                    " border-radius:4px; padding:3px 10px; font-size:11px; font-weight:600;"
                )
            elif action == "warn" or is_conflict:
                ring = max(4, int(drift * 10))
                self._planner.set_ring("warn", ring)
                self._critic.set_ring("warn",  ring)
                if is_conflict:
                    self.output_area.appendPlainText(
                        f"[R4] Conflit détecté — {agent_id}"
                    )
        except ImportError:
            # Inspecteur non disponible — dégradation gracieuse
            if is_conflict:
                self._entropy = max(0.0, self._entropy - 20.0)
                self._entropy_bar.update_entropy(self._entropy)

        self.output_area.appendPlainText(
            f"[{agent_id}]{'  ⚠' if is_conflict else ''} {text[:70]}"
        )

    def _on_synthesis(self, text: str):
        self._synth.set_synthesis(text)
        self.output_area.appendPlainText("[SYNTHESE] " + text[:70])

    def _on_done(self, result: dict):
        n      = len(result.get("turns", []))
        action = result.get("resonance_action", "pass")
        self.output_area.appendPlainText(f"[DONE] {n} tours | résonance={action}")
        self._reset_ui("DONE")

    def _on_error(self, err: str):
        self.output_area.appendPlainText("[ERR] " + err)
        self._planner.set_status("ERROR")
        self._critic.set_status("ERROR")
        self._reset_ui("ERROR")

    def _on_synthesis_done(self, text: str):
        self._on_synthesis(text)

    # ── Bouton Actionner → MCP ────────────────────────────────────────────────

    def _on_action_mcp(self, synthesis_text: str):
        """
        Envoie la synthèse au serveur MCP via MCPWorker (non-bloquant).
        Tool : llm_generate avec la synthèse comme prompt.
        """
        self.output_area.appendPlainText("[MCP] Actionner → llm_generate…")
        try:
            from forge_desktop.core.mcp_connector import MCPWorker, local_bridge
            self._mcp_worker = MCPWorker(
                local_bridge(), "llm_generate",
                {"prompt": synthesis_text[:400], "agent_id": "laforge",
                 "max_tokens": 200},
                parent=self,
            )
            self._mcp_worker.result_ready.connect(self._on_mcp_result)
            self._mcp_worker.start()
        except ImportError as e:
            self.output_area.appendPlainText("[ERR MCP] " + str(e)[:60])

    def _on_mcp_result(self, result: dict):
        if result.get("ok"):
            data = result.get("result", {})
            resp = data.get("response", str(data))[:200] if isinstance(data, dict) else str(data)[:200]
            self._synth.set_synthesis(self._synth._synthesis.toPlainText()
                                      + "\n\n[MCP] " + resp)
            self.output_area.appendPlainText(f"[MCP OK] {resp[:60]}")
        else:
            self.output_area.appendPlainText("[MCP ERR] " + result.get("error","?")[:60])

    # ── Rollback Ring 4 ───────────────────────────────────────────────────────

    def _on_rollback(self):
        """Déclenché par EntropyBar — context_rollback via Inspecteur R4."""
        self.output_area.appendPlainText("[R4] Rollback contexte en cours…")
        try:
            from forge_inspector import get_inspector
            insp   = get_inspector(self._session_id)
            result = insp.context_rollback(reason="Demande manuelle depuis DebateView")
            self.output_area.appendPlainText(
                f"[R4] Rollback: {result.get('action','?')} "
                f"purged={result.get('purged_chunks',0)}"
            )
        except ImportError:
            pass
        # Reset UI
        self._entropy = 100.0
        self._entropy_bar.update_entropy(100.0)
        self._planner.set_ring("ok", 10)
        self._critic.set_ring("ok",  10)
        self._btn_cancel.setStyleSheet(
            "background:#1a1a1a; border:1px solid #444; border-radius:4px;"
            " padding:3px 10px; font-size:11px; color:#888;"
        )

    # ── Utilitaires ───────────────────────────────────────────────────────────

    def _reset_ui(self, status: str = "IDLE"):
        self._synth.btn_start.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.setStyleSheet(
            "background:#1a1a1a; border:1px solid #444; border-radius:4px;"
            " padding:3px 10px; font-size:11px; color:#888;"
        )
        self._planner.set_status(status)
        self._critic.set_status(status)

    def _clear_all(self):
        self._planner.clear()
        self._critic.clear()
        self._synth.set_synthesis("")
        self.output_area.clear()
        self._entropy = 100.0
        self._entropy_bar.update_entropy(100.0)
        self._reset_ui()

    def _cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(2000)
            self.output_area.appendPlainText("[CANCEL] worker arrêté")
        self._reset_ui()

    def update_agent_message(self, agent: str, text: str,
                              is_conflict: bool = False):
        """API publique — injection externe (tests, MCP)."""
        self._on_turn(agent, text, is_conflict)

    def closeEvent(self, event):
        """Arrêt propre des workers QThread."""
        if hasattr(self, '_worker') and self._worker is not None:
            if hasattr(self._worker, 'stop'):
                self._worker.stop()
            if hasattr(self._worker, 'wait'):
                self._worker.wait(1000)
            if hasattr(self._worker, 'terminate'):
                self._worker.terminate()
        if hasattr(self, '_mcp_worker') and self._mcp_worker is not None:
            if hasattr(self._mcp_worker, 'stop'):
                self._mcp_worker.stop()
            if hasattr(self._mcp_worker, 'wait'):
                self._mcp_worker.wait(1000)
            if hasattr(self._mcp_worker, 'terminate'):
                self._mcp_worker.terminate()
        super().closeEvent(event)