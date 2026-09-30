"""
forge_desktop/widgets/ring_meter_v2.py
=======================================
TUI_TO_GUI_DYNAMIC_BRIDGE — Grouped_Ring_Meter_V2
60fps token display + system health groupé.
QThread isolation level 3.
"""
from __future__ import annotations
import time
import math
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QPointF, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont, QPainterPath

MONO = "font-family:'Cascadia Code','Consolas';"

# ── Worker isolé niveau 3 — aucun accès UI ────────────────────────────────────
class _HealthWorker(QThread):
    """
    QThread isolation level 3 :
    - Aucun appel Qt UI depuis ce thread
    - Émet uniquement des dicts primitifs
    - Timeout 50ms par probe
    """
    health_data = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self.setObjectName("HealthWorker_L3")

    def run(self):
        while self._running:
            data = {}
            # Hub
            try:
                import urllib.request
                t0 = time.time()
                urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=0.05)
                data["hub"] = {"ok": True, "ms": int((time.time()-t0)*1000)}
            except Exception:
                data["hub"] = {"ok": False, "ms": 0}

            # Ollama
            try:
                import urllib.request
                t0 = time.time()
                urllib.request.urlopen("http://localhost:11434/api/tags", timeout=0.05)
                data["ollama"] = {"ok": True, "ms": int((time.time()-t0)*1000)}
            except Exception:
                data["ollama"] = {"ok": False, "ms": 0}

            # MMap
            try:
                import sys
                from pathlib import Path
                ROOT = Path(r"%NOKIDO_WORKSPACE%\LaForge")
                if str(ROOT/"app") not in sys.path:
                    sys.path.insert(0, str(ROOT/"app"))
                from live_bridge import bridge
                snap = bridge.snapshot().get("json", {})
                data["mmap"] = {
                    "ok":    True,
                    "state": snap.get("swarm.state","IDLE"),
                    "agent": snap.get("swarm.active_agent",""),
                }
            except Exception:
                data["mmap"] = {"ok": False, "state": "—"}

            # VRAM
            try:
                import subprocess
                r = subprocess.run(
                    ["nvidia-smi","--query-gpu=memory.used,memory.total,utilization.gpu",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, encoding="utf-8", errors="replace", timeout=0.05
                )
                if r.returncode == 0 and r.stdout.strip():
                    parts = r.stdout.strip().split(",")
                    used, total = int(parts[0].strip()), int(parts[1].strip())
                    util = int(parts[2].strip()) if len(parts)>2 else 0
                    data["vram"] = {
                        "pct": 100*used//max(1,total),
                        "used_mb": used, "total_mb": total, "util": util
                    }
                else:
                    data["vram"] = {"pct": 0, "used_mb": 0, "total_mb": 0, "util": 0}
            except Exception:
                data["vram"] = {"pct": 0, "used_mb": 0, "total_mb": 0, "util": 0}

            data["ts"] = time.time()
            self.health_data.emit(data)
            self.msleep(2000)  # 0.5fps probe — léger sur le réseau

    def stop(self):
        self._running = False
        self.quit()


# ── Arc gauge (dessiné par QPainter) ─────────────────────────────────────────
class _ArcGauge(QWidget):
    """
    Jauge en arc — 270°. Rendu 60fps via QTimer.
    """
    def __init__(self, label: str, color: str = "#2196f3",
                 size: int = 64, parent=None):
        super().__init__(parent)
        self._label  = label
        self._color  = QColor(color)
        self._value  = 0.0   # 0.0 → 1.0
        self._target = 0.0   # valeur cible pour interpolation
        self._ok     = True
        self._sub    = ""
        self.setFixedSize(size, size + 16)
        self._size   = size

        # 60fps via QTimer
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._step)
        self._anim_timer.start(16)  # ~60fps

    def set_value(self, v: float, ok: bool = True, sub: str = ""):
        self._target = max(0.0, min(1.0, v))
        self._ok     = ok
        self._sub    = sub

    def _step(self):
        # Interpolation fluide vers target
        diff = self._target - self._value
        if abs(diff) > 0.001:
            self._value += diff * 0.15
            self.update()
        elif self._value != self._target:
            self._value = self._target
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        s   = self._size
        cx  = s // 2
        cy  = s // 2
        r   = s // 2 - 6
        pen_w = 5

        # Arc de fond
        bg_pen = QPen(QColor("#1a1a1a"), pen_w, Qt.SolidLine, Qt.RoundCap)
        p.setPen(bg_pen)
        rect = QRectF(cx-r, cy-r, r*2, r*2)
        p.drawArc(rect, 225*16, -270*16)

        # Arc de valeur
        if not self._ok:
            arc_color = QColor("#333")
        elif self._value > 0.8:
            arc_color = QColor("#f44336")
        elif self._value > 0.6:
            arc_color = QColor("#ff9800")
        else:
            arc_color = self._color

        arc_pen = QPen(arc_color, pen_w, Qt.SolidLine, Qt.RoundCap)
        p.setPen(arc_pen)
        span = int(-270 * self._value * 16)
        if abs(span) > 0:
            p.drawArc(rect, 225*16, span)

        # Valeur centrale
        p.setPen(QPen(QColor("#c2c0b6") if self._ok else QColor("#444")))
        f = QFont("Cascadia Code", 9, QFont.Bold)
        p.setFont(f)
        pct_text = f"{int(self._value*100)}%"
        p.drawText(QRectF(0, cy-10, s, 20), Qt.AlignCenter, pct_text)

        # Label bas
        p.setPen(QPen(QColor("#666")))
        f2 = QFont("Cascadia Code", 7)
        p.setFont(f2)
        p.drawText(QRectF(0, s-2, s, 12), Qt.AlignCenter, self._label)

        # Sub (ms ou état)
        if self._sub:
            p.setPen(QPen(QColor("#333")))
            f3 = QFont("Cascadia Code", 6)
            p.setFont(f3)
            p.drawText(QRectF(0, cy+6, s, 10), Qt.AlignCenter, self._sub[:8])

        p.end()


# ── LED dot ───────────────────────────────────────────────────────────────────
class _Dot(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._ok    = False
        self._label = label
        self._ms    = 0
        self.setFixedSize(56, 40)
        self._timer = QTimer(self); self._timer.timeout.connect(self.update)
        self._timer.start(16)

    def set_state(self, ok: bool, ms: int = 0):
        self._ok = ok; self._ms = ms

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor("#4caf50") if self._ok else QColor("#333")
        # Pulsation si ok
        if self._ok:
            pulse = 0.85 + 0.15 * math.sin(time.time() * 3)
            col.setAlphaF(pulse)
        p.setBrush(QBrush(col))
        p.setPen(Qt.NoPen)
        p.drawEllipse(20, 4, 16, 16)
        p.setPen(QPen(QColor("#666")))
        f = QFont("Cascadia Code", 7)
        p.setFont(f)
        p.drawText(0, 22, 56, 10, Qt.AlignCenter, self._label)
        if self._ms:
            p.setPen(QPen(QColor("#333")))
            p.drawText(0, 32, 56, 8, Qt.AlignCenter, f"{self._ms}ms")
        p.end()


# ── Widget principal ──────────────────────────────────────────────────────────
class RingMeterV2(QWidget):
    """
    Grouped Ring Meter V2 — 60fps.
    Gauges : VRAM, GPU util.
    Dots : Hub, Ollama, MMap.
    Token stream counter.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(96)
        self.setStyleSheet("background:#0d0d0d; border-top:1px solid #111;")
        self._token_count = 0
        self._token_rate  = 0.0
        self._last_token_ts = time.time()
        self._build()

        # Worker isolé — démarrage différé 1s pour laisser Qt s'initialiser
        self._worker = _HealthWorker(self)
        self._worker.health_data.connect(self._on_data)
        QTimer.singleShot(1000, self._worker.start)

        # Token rate decay
        self._decay = QTimer(self)
        self._decay.timeout.connect(self._decay_rate)
        self._decay.start(500)

    def _build(self):
        lo = QHBoxLayout(self)
        lo.setContentsMargins(12, 4, 12, 4)
        lo.setSpacing(16)

        # Gauges arc
        self._vram_gauge = _ArcGauge("VRAM",   "#2196f3", 64)
        self._gpu_gauge  = _ArcGauge("GPU",    "#ff9800", 64)
        lo.addWidget(self._vram_gauge)
        lo.addWidget(self._gpu_gauge)

        # Separator
        sep = QWidget(); sep.setFixedWidth(1)
        sep.setStyleSheet("background:#1a1a1a;")
        lo.addWidget(sep)

        # Dots services
        dots_w = QWidget()
        dots_lo = QVBoxLayout(dots_w)
        dots_lo.setContentsMargins(0,0,0,0)
        dots_lo.setSpacing(2)
        row1 = QHBoxLayout(); row1.setSpacing(4)
        row2 = QHBoxLayout(); row2.setSpacing(4)
        self._hub_dot    = _Dot("Hub")
        self._ollama_dot = _Dot("Ollama")
        self._mmap_dot   = _Dot("MMap")
        row1.addWidget(self._hub_dot)
        row1.addWidget(self._ollama_dot)
        row2.addWidget(self._mmap_dot)
        # Swarm state
        self._swarm_lbl = QLabel("IDLE")
        self._swarm_lbl.setStyleSheet(f"color:#333; font-size:9px; {MONO}")
        row2.addWidget(self._swarm_lbl)
        dots_lo.addLayout(row1)
        dots_lo.addLayout(row2)
        lo.addWidget(dots_w)

        # Separator
        sep2 = QWidget(); sep2.setFixedWidth(1)
        sep2.setStyleSheet("background:#1a1a1a;")
        lo.addWidget(sep2)

        # Token stream
        tok_w = QWidget()
        tok_lo = QVBoxLayout(tok_w)
        tok_lo.setContentsMargins(0,0,0,0)
        tok_lo.setSpacing(4)
        tok_title = QLabel("Token Stream")
        tok_title.setStyleSheet(f"color:#333; font-size:9px; {MONO}")
        tok_lo.addWidget(tok_title)
        self._tok_count_lbl = QLabel("0")
        self._tok_count_lbl.setStyleSheet(
            f"color:#2196f3; font-size:18px; font-weight:700; {MONO}"
        )
        tok_lo.addWidget(self._tok_count_lbl)
        self._tok_rate_lbl = QLabel("0 tok/s")
        self._tok_rate_lbl.setStyleSheet(f"color:#444; font-size:9px; {MONO}")
        tok_lo.addWidget(self._tok_rate_lbl)
        lo.addWidget(tok_w)

        lo.addStretch()

        # Latence cible
        self._latency_lbl = QLabel("<100ms")
        self._latency_lbl.setStyleSheet(f"color:#1a4a1a; font-size:9px; {MONO}")
        lo.addWidget(self._latency_lbl)

    def _on_data(self, data: dict):
        v = data.get("vram", {})
        self._vram_gauge.set_value(
            v.get("pct",0)/100,
            True,
            f"{v.get('used_mb',0)}MB"
        )
        self._gpu_gauge.set_value(
            v.get("util",0)/100,
            True,
            f"{v.get('util',0)}%"
        )
        h = data.get("hub",{})
        self._hub_dot.set_state(h.get("ok",False), h.get("ms",0))
        o = data.get("ollama",{})
        self._ollama_dot.set_state(o.get("ok",False), o.get("ms",0))
        m = data.get("mmap",{})
        self._mmap_dot.set_state(m.get("ok",False))
        state = m.get("state","IDLE")
        col = "#00bcd4" if state=="RUNNING" else "#333"
        self._swarm_lbl.setText(state)
        self._swarm_lbl.setStyleSheet(f"color:{col}; font-size:9px; {MONO}")

        # Latence hub
        ms = h.get("ms",0)
        col_lat = "#4caf50" if ms<100 else ("#ff9800" if ms<300 else "#f44336")
        self._latency_lbl.setText(f"{ms}ms" if ms else "<100ms")
        self._latency_lbl.setStyleSheet(f"color:{col_lat}; font-size:9px; {MONO}")

    def add_tokens(self, n: int):
        """Appeler quand des tokens sont générés."""
        self._token_count += n
        now = time.time()
        dt = now - self._last_token_ts
        if dt > 0:
            self._token_rate = n / dt
        self._last_token_ts = now
        self._tok_count_lbl.setText(f"{self._token_count:,}")
        self._tok_rate_lbl.setText(f"{self._token_rate:.0f} tok/s")

    def _decay_rate(self):
        if self._token_rate > 0:
            self._token_rate *= 0.85
            self._tok_rate_lbl.setText(f"{self._token_rate:.0f} tok/s")

    def closeEvent(self, event):
        """Arrêt propre du worker avant fermeture."""
        self._worker.stop()
        if not self._worker.wait(1500):   # 1.5s max
            self._worker.terminate()      # forcé si trop lent
        if hasattr(super(), 'closeEvent'):
            super().closeEvent(event)

    def hideEvent(self, event):
        """Stopper les timers quand le widget est caché."""
        self._decay.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        """Redémarrer les timers à l'affichage."""
        if not self._decay.isActive():
            self._decay.start(500)
        super().showEvent(event)
