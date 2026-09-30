"""
forge_desktop/widgets/ring_o_meter.py
=======================================
Ring-O-Meter — Visualisation circulaire des rings Nokido.

Chaque anneau = un ring (0..10).
  - Vert brillant  → ring stable, aucune violation
  - Orange pulsant → alerte (tentative de modification)
  - Rouge bloqué   → violation bloquée (ring 10 vs ring 0)

Lecture des données depuis live_bridge.map (mmap) et resonance_log.
Mise à jour par signal Qt depuis MMapPollerWorker.

Architecture :
  RingOMeterWidget (QWidget)
    └── RingDial (QWidget, paint QPainter)
         └── 11 arcs concentriques (ring 0 au centre, ring 10 à l'extérieur)
    └── RingStatusPanel (QWidget, liste violations)
"""
from __future__ import annotations
import math
import sqlite3
import time
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal, Property
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QRadialGradient,
    QConicalGradient, QFont, QPainterPath,
)

ROOT = Path(__file__).resolve().parent.parent.parent
DB   = ROOT / "RAG" / "embeddings.db"

# ── Données de chaque ring ────────────────────────────────────────────────────

RING_META = {
    0:  {"label": "Ring 0",  "desc": "Lois absolues",       "color_ok": "#4caf50", "color_alert": "#ff5722", "color_block": "#f44336"},
    1:  {"label": "Ring 1",  "desc": "Core Nokido",        "color_ok": "#66bb6a", "color_alert": "#ff7043", "color_block": "#ef5350"},
    2:  {"label": "Ring 2",  "desc": "TRUSTED humain",      "color_ok": "#81c784", "color_alert": "#ffa726", "color_block": "#e53935"},
    3:  {"label": "Ring 3",  "desc": "Agents validés",      "color_ok": "#a5d6a7", "color_alert": "#ffb74d", "color_block": "#e53935"},
    4:  {"label": "Ring 4",  "desc": "Agents externes",     "color_ok": "#c8e6c9", "color_alert": "#ffd54f", "color_block": "#e57373"},
    5:  {"label": "Ring 5",  "desc": "RAG web",             "color_ok": "#e8f5e9", "color_alert": "#ffe082", "color_block": "#ef9a9a"},
    6:  {"label": "Ring 6",  "desc": "Outils CI/CD",        "color_ok": "#fff9c4", "color_alert": "#ffe57f", "color_block": "#ffab91"},
    7:  {"label": "Ring 7",  "desc": "SSH / réseau",        "color_ok": "#fff3e0", "color_alert": "#ffcc02", "color_block": "#ff8a65"},
    8:  {"label": "Ring 8",  "desc": "Monitoring",          "color_ok": "#fce4ec", "color_alert": "#ff8f00", "color_block": "#ff7043"},
    9:  {"label": "Ring 9",  "desc": "Système Windows",     "color_ok": "#f3e5f5", "color_alert": "#e65100", "color_block": "#f44336"},
    10: {"label": "Ring 10", "desc": "Corrections de Cap",  "color_ok": "#ede7f6", "color_alert": "#b71c1c", "color_block": "#d32f2f"},
}

# États possibles pour un ring
STATE_OK     = "ok"
STATE_ALERT  = "alert"
STATE_BLOCK  = "block"
STATE_INACTIVE = "inactive"


# ── Lecture état rings depuis DB ──────────────────────────────────────────────

def _load_ring_states() -> dict:
    """
    Lit l'état de chaque ring depuis resonance_log et system_rules.
    Retourne {ring_id: {"state": str, "last_event": str, "count": int}}
    """
    states = {i: {"state": STATE_OK, "last_event": "", "count": 0, "violations": []}
              for i in range(11)}
    try:
        conn = sqlite3.connect(str(DB), timeout=3)

        # Violations récentes depuis resonance_log
        rows = conn.execute(
            "SELECT agent_id, action, drift_score, adr_triggered, timestamp "
            "FROM resonance_log ORDER BY id DESC LIMIT 50"
        ).fetchall()

        for row in rows:
            agent, action, drift, adr_json, ts = row
            if action == "block":
                # Ring 0 violé — alerte critique
                states[0]["state"]  = STATE_BLOCK
                states[0]["last_event"] = f"{agent} BLOQUÉ ({ts[:16]})"
                states[0]["count"] += 1
                states[0]["violations"].append({"agent": agent, "ts": ts[:16], "action": "block"})
                # Ring 10 aussi allumé
                states[10]["state"] = STATE_ALERT
            elif action in ("correct", "warn"):
                # Alerte sur ring de drift
                drift_f = float(drift or 0)
                ring_affected = min(10, max(0, int(drift_f * 10)))
                if states[ring_affected]["state"] != STATE_BLOCK:
                    states[ring_affected]["state"] = STATE_ALERT
                states[ring_affected]["last_event"] = f"{agent} {action.upper()}"
                states[ring_affected]["count"] += 1

        # System rules par ring — marquer rings actifs
        ring_counts = conn.execute(
            "SELECT ring, COUNT(*) FROM system_rules GROUP BY ring"
        ).fetchall()
        conn.close()

        for ring, count in ring_counts:
            if ring in states and count > 0:
                if states[ring]["state"] == STATE_OK:
                    states[ring]["count"] = count

    except Exception:
        pass

    return states


# ── Dial circulaire ───────────────────────────────────────────────────────────

class RingDial(QWidget):
    """
    Widget de dessin — 11 arcs concentriques.
    Ring 0 au centre (le plus petit), Ring 10 à l'extérieur.
    """
    ring_clicked = Signal(int)   # ring_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._states: dict = {i: {"state": STATE_OK, "count": 0, "violations": []}
                               for i in range(11)}
        self._pulse_t   = 0.0
        self._hover_ring: Optional[int] = None

        # Timer animation pulse
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick_anim)
        self._anim_timer.start(50)   # 20fps

        self.setMinimumSize(280, 280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

    def _tick_anim(self):
        self._pulse_t = (self._pulse_t + 0.12) % (2 * math.pi)
        # Redessiner seulement si un ring est en alerte/block
        needs_update = any(
            s["state"] in (STATE_ALERT, STATE_BLOCK)
            for s in self._states.values()
        )
        if needs_update:
            self.update()

    def update_states(self, states: dict):
        self._states = states
        self.update()

    def _ring_rect(self, ring_id: int, cx: float, cy: float,
                   min_r: float, step: float) -> QRectF:
        r = min_r + ring_id * step
        return QRectF(cx - r, cy - r, r * 2, r * 2)

    def _color_for_state(self, ring_id: int, state: str) -> QColor:
        meta = RING_META[ring_id]
        pulse = (math.sin(self._pulse_t) + 1) / 2

        if state == STATE_BLOCK:
            # Rouge pulsant intense
            r = int(180 + pulse * 60)
            return QColor(r, 30, 30)
        elif state == STATE_ALERT:
            # Orange pulsant
            r = int(200 + pulse * 55)
            g = int(80 + pulse * 60)
            return QColor(r, g, 20)
        elif state == STATE_OK:
            return QColor(meta["color_ok"])
        else:
            return QColor("#2a2a2a")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h  = self.width(), self.height()
        cx, cy = w / 2, h / 2
        min_r  = min(w, h) * 0.06   # rayon du ring 0
        step   = min(w, h) * 0.042  # épaisseur de chaque ring
        arc_w  = step * 0.65        # largeur du trait

        # ── Fond sombre ───────────────────────────────────────────────────────
        p.fillRect(0, 0, w, h, QColor("#0e1117"))

        # ── Arcs ring 0..10 ───────────────────────────────────────────────────
        for ring_id in range(11):
            state = self._states[ring_id]["state"]
            col   = self._color_for_state(ring_id, state)
            rect  = self._ring_rect(ring_id, cx, cy, min_r, step)

            # Halo glow pour alert/block
            if state in (STATE_ALERT, STATE_BLOCK):
                pulse = (math.sin(self._pulse_t) + 1) / 2
                glow_w = arc_w + 4 + pulse * 6
                glow_col = QColor(col)
                glow_col.setAlpha(60 + int(pulse * 80))
                glow_pen = QPen(glow_col, glow_w)
                glow_pen.setCapStyle(Qt.RoundCap)
                p.setPen(glow_pen)
                p.drawArc(rect, 0, 360 * 16)

            # Arc principal
            pen = QPen(col, arc_w)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)

            # Ring 0 toujours complet (360°), les autres peuvent être partiels
            if ring_id == 0 and state == STATE_BLOCK:
                # Cercle plein rouge pour Ring 0 bloqué
                p.drawArc(rect, 0, 360 * 16)
                # Croix de blocage
                p.setPen(QPen(QColor("#ffffff"), 2))
                r = min_r * 0.6
                p.drawLine(QPointF(cx-r*0.5, cy-r*0.5), QPointF(cx+r*0.5, cy+r*0.5))
                p.drawLine(QPointF(cx+r*0.5, cy-r*0.5), QPointF(cx-r*0.5, cy+r*0.5))
            else:
                p.drawArc(rect, 90 * 16, -360 * 16)

            # Hover highlight
            if self._hover_ring == ring_id:
                h_pen = QPen(QColor(255, 255, 255, 60), arc_w + 2)
                p.setPen(h_pen)
                p.drawArc(rect, 0, 360 * 16)

        # ── Label central ─────────────────────────────────────────────────────
        # Compter les violations actives
        blocks = sum(1 for s in self._states.values() if s["state"] == STATE_BLOCK)
        alerts = sum(1 for s in self._states.values() if s["state"] == STATE_ALERT)

        p.setPen(QColor("#c2c0b6"))
        font = QFont("Segoe UI", 9, QFont.Medium)
        p.setFont(font)

        if blocks > 0:
            p.setPen(QColor("#f44336"))
            p.drawText(QRectF(cx-40, cy-20, 80, 20),
                       Qt.AlignCenter, "BLOQUÉ")
            p.setPen(QColor("#888"))
            p.drawText(QRectF(cx-40, cy, 80, 20),
                       Qt.AlignCenter, f"Ring 0 violé")
        elif alerts > 0:
            p.setPen(QColor("#ff9800"))
            p.drawText(QRectF(cx-40, cy-20, 80, 20),
                       Qt.AlignCenter, f"{alerts} alerte{'s' if alerts > 1 else ''}")
            p.setPen(QColor("#888"))
            p.drawText(QRectF(cx-40, cy+2, 80, 18),
                       Qt.AlignCenter, "en cours")
        else:
            p.setPen(QColor("#4caf50"))
            p.drawText(QRectF(cx-40, cy-20, 80, 20),
                       Qt.AlignCenter, "STABLE")
            p.setPen(QColor("#555"))
            p.drawText(QRectF(cx-40, cy+2, 80, 18),
                       Qt.AlignCenter, "tous rings OK")

        # ── Labels ring (à droite du dial, 1 sur 2) ───────────────────────────
        p.setFont(QFont("Segoe UI", 8))
        for ring_id in range(0, 11, 2):
            r   = min_r + ring_id * step
            ang = math.pi / 4   # 45°
            lx  = cx + r * math.cos(ang) + 6
            ly  = cy - r * math.sin(ang)
            col = self._color_for_state(ring_id, self._states[ring_id]["state"])
            p.setPen(col)
            p.drawText(QRectF(lx, ly-8, 50, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       str(ring_id))

    def mouseMoveEvent(self, event):
        w, h   = self.width(), self.height()
        cx, cy = w/2, h/2
        min_r  = min(w, h) * 0.06
        step   = min(w, h) * 0.042
        mx, my = event.position().x(), event.position().y()
        dist   = math.sqrt((mx-cx)**2 + (my-cy)**2)

        # Trouver le ring sous le curseur
        ring = round((dist - min_r) / step)
        self._hover_ring = ring if 0 <= ring <= 10 else None
        self.update()

    def mousePressEvent(self, event):
        if self._hover_ring is not None:
            self.ring_clicked.emit(self._hover_ring)

    def leaveEvent(self, event):
        self._hover_ring = None
        self.update()


# ── Panel status ──────────────────────────────────────────────────────────────

class RingStatusPanel(QWidget):
    """Liste des violations récentes et état par ring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        title = QLabel("Ring status")
        title.setStyleSheet("font-weight:600; font-size:11px; color:#c2c0b6;")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setSpacing(2)
        self._layout.addStretch()
        scroll.setWidget(self._inner)
        layout.addWidget(scroll)

        self._rows: dict[int, QLabel] = {}
        for ring_id in range(11):
            lbl = QLabel(f"Ring {ring_id:2d}  ●  stable")
            lbl.setStyleSheet("font-size:10px; color:#4caf50; font-family:monospace;")
            self._rows[ring_id] = lbl
            self._layout.insertWidget(self._layout.count()-1, lbl)

    def update_states(self, states: dict):
        for ring_id, info in states.items():
            if ring_id not in self._rows:
                continue
            lbl   = self._rows[ring_id]
            state = info["state"]
            count = info.get("count", 0)
            last  = info.get("last_event", "")[:25]
            meta  = RING_META[ring_id]

            if state == STATE_BLOCK:
                icon  = "✖"
                color = "#f44336"
                text  = f"Ring {ring_id:2d}  {icon}  BLOQUÉ  {last}"
            elif state == STATE_ALERT:
                icon  = "⚠"
                color = "#ff9800"
                text  = f"Ring {ring_id:2d}  {icon}  alerte  {last}"
            else:
                icon  = "●"
                color = "#4caf50" if count > 0 else "#444"
                desc  = meta["desc"][:16]
                text  = f"Ring {ring_id:2d}  {icon}  {desc}"

            lbl.setText(text)
            lbl.setStyleSheet(f"font-size:10px; color:{color}; font-family:monospace;")


# ── Widget principal Ring-O-Meter ─────────────────────────────────────────────

class RingOMeterWidget(QWidget):
    """
    Widget complet Ring-O-Meter.
    Dial circulaire + panel status.
    Mise à jour automatique toutes les 3s depuis la DB.
    Mise à jour temps réel via update_from_mmap() appelé par MMapPollerWorker.
    """
    ring_selected = Signal(int, dict)   # ring_id, info

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Dial
        self._dial = RingDial()
        self._dial.ring_clicked.connect(self._on_ring_clicked)
        layout.addWidget(self._dial)

        # Status panel
        self._status = RingStatusPanel()
        layout.addWidget(self._status)

        # Timer refresh depuis DB
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(3000)
        self._refresh()   # refresh immédiat

    def _refresh(self):
        states = _load_ring_states()
        self._dial.update_states(states)
        self._status.update_states(states)

    def update_from_resonance(self, resonance_data: dict):
        """
        Mise à jour temps réel depuis le filtre de résonance
        (données reçues via MMap sans attendre le timer 3s).
        """
        action     = resonance_data.get("last_action", "pass")
        drift      = float(resonance_data.get("drift_score", 0) or 0)
        agent      = resonance_data.get("last_agent", "")

        if action == "block":
            self._dial._states[0]["state"]  = STATE_BLOCK
            self._dial._states[0]["last_event"] = agent + " BLOQUÉ"
            self._dial._states[10]["state"] = STATE_ALERT
            self._dial.update()
            self._status.update_states(self._dial._states)
        elif action in ("correct", "warn"):
            ring_aff = min(10, max(1, int(drift * 10)))
            self._dial._states[ring_aff]["state"] = STATE_ALERT
            self._dial._states[ring_aff]["last_event"] = agent + " " + action
            self._dial.update()
            self._status.update_states(self._dial._states)
        elif action == "pass":
            # Décroissance progressive vers OK (ne pas reset instantané)
            for ring_id in range(1, 11):
                if self._dial._states[ring_id]["state"] == STATE_ALERT:
                    self._dial._states[ring_id]["state"] = STATE_OK
            self._dial.update()

    def _on_ring_clicked(self, ring_id: int):
        info = self._dial._states.get(ring_id, {})
        self.ring_selected.emit(ring_id, info)
