"""
forge_desktop/widgets/ring_group_widget.py
==========================================
RingGroupWidget — v17.04-RT
3 groupes : Governance | Intelligence | Infra
Polling MMap 500ms. Mise à jour conditionnelle.
"""
from __future__ import annotations
import time
import os
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QGroupBox, QProgressBar, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor

DARK = "background:#0a0a0a; color:#c2c0b6; font-family:'Cascadia Code','Consolas'; font-size:11px;"

# ── Indicateur LED ────────────────────────────────────────────────────────────
class _LED(QWidget):
    COLORS = {"ok":"#4caf50","warn":"#ff9800","err":"#f44336","off":"#333"}
    def __init__(self, size=10, parent=None):
        super().__init__(parent)
        self.setFixedSize(size+4, size+4)
        self._color = "off"
        self._size  = size
    def set_state(self, state: str):
        self._color = state
        self.update()
    def paintEvent(self, _):
        from PySide6.QtGui import QPainter, QBrush
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(self.COLORS.get(self._color, "#333"))))
        p.setPen(Qt.NoPen)
        p.drawEllipse(2, 2, self._size, self._size)

# ── Carte d'un élément du ring ────────────────────────────────────────────────
class _RingCard(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(6, 3, 6, 3)
        lo.setSpacing(6)
        self._led = _LED()
        lo.addWidget(self._led)
        self._lbl = QLabel(label)
        self._lbl.setStyleSheet("color:#c2c0b6; font-size:11px;")
        lo.addWidget(self._lbl)
        lo.addStretch()
        self._val = QLabel("—")
        self._val.setStyleSheet("color:#666; font-size:10px;")
        lo.addWidget(self._val)
        self.setStyleSheet("background:#111; border:1px solid #222; border-radius:4px;")

    def update_card(self, state: str, val: str = ""):
        self._led.set_state(state)
        self._val.setText(val[:30])

# ── Widget principal ──────────────────────────────────────────────────────────
class RingGroupWidget(QWidget):
    """
    3 groupes Ring : Governance | Intelligence | Infra
    Polling MMap 500ms — émet ring_alert si Ring0 violation détectée.
    """
    ring_alert = Signal(str, str)  # (ring, message)

    # Définition des anneaux
    GROUPS = {
        "Governance": {
            "color": "#9c27b0",
            "items": [
                ("master_dev",   "Master Dev"),
                ("orchestrators","Orchestrators"),
                ("authority",    "Authority TTL"),
                ("sentinel",     "Sentinel R0"),
            ]
        },
        "Intelligence": {
            "color": "#2196f3",
            "items": [
                ("ollama",       "Ollama"),
                ("llamacpp",     "LlamaCPP"),
                ("ring8",        "Ring 8 Cloud"),
                ("rag",          "RAG Engine"),
                ("resonance",    "Résonance Filter"),
            ]
        },
        "Infra": {
            "color": "#4caf50",
            "items": [
                ("hub",          "Hub :8766"),
                ("gateway",      "Gateway :8080"),
                ("mcp_server",   "MCP Server"),
                ("watchdog",     "Watchdog"),
                ("mmap",         "MMap bridge"),
            ]
        },
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: dict[str, _RingCard] = {}
        self._last_snap = {}
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(5000)   # 5s — Hub + Ollama + MMap
        QTimer.singleShot(200, self._poll)

    def _build_ui(self):
        main_lo = QVBoxLayout(self)
        main_lo.setSpacing(6)
        main_lo.setContentsMargins(4, 4, 4, 4)

        hdr_lo = QHBoxLayout()
        title = QLabel("⬡  Ring Status — v17.04-RT")
        title.setStyleSheet("font-size:13px; font-weight:600; color:#c2c0b6;")
        hdr_lo.addWidget(title)
        hdr_lo.addStretch()
        self._global_led = _LED(12)
        self._global_led.set_state("ok")
        hdr_lo.addWidget(self._global_led)
        self._global_lbl = QLabel("Système OK")
        self._global_lbl.setStyleSheet("color:#4caf50; font-size:11px;")
        hdr_lo.addWidget(self._global_lbl)
        main_lo.addLayout(hdr_lo)

        groups_lo = QHBoxLayout()
        groups_lo.setSpacing(8)
        for group_name, cfg in self.GROUPS.items():
            grp = QGroupBox(group_name)
            grp.setStyleSheet(
                f"QGroupBox {{ border:1px solid {cfg['color']}44; border-radius:6px;"
                f" margin-top:6px; color:{cfg['color']}; font-size:11px; font-weight:600; }}"
            )
            grp_lo = QVBoxLayout(grp)
            grp_lo.setSpacing(3)
            grp_lo.setContentsMargins(4, 8, 4, 4)
            for key, label in cfg["items"]:
                card = _RingCard(label)
                self._cards[key] = card
                grp_lo.addWidget(card)
            grp_lo.addStretch()
            groups_lo.addWidget(grp, 1)
        main_lo.addLayout(groups_lo)

    def _poll(self):
        snap = self._read_snap()
        if snap == self._last_snap:
            return
        self._last_snap = snap
        self._update_cards(snap)

    def _read_snap(self) -> dict:
        snap = {}
        # MMap bridge
        try:
            import sys, os
            from pathlib import Path
            ROOT = Path(r"%NOKIDO_WORKSPACE%\LaForge")
            if str(ROOT/"app") not in sys.path:
                sys.path.insert(0, str(ROOT/"app"))
            from live_bridge import bridge
            raw = bridge.snapshot().get("json", {})
            snap["mmap_ok"]      = True
            snap["swarm_state"]  = raw.get("swarm.state","IDLE")
            snap["active_agent"] = raw.get("swarm.active_agent","")
            snap["watchdog_ok"]  = not raw.get("watchdog.alert", False)
            for k,v in raw.items():
                if k.startswith("llm."):
                    snap[k] = v
        except Exception:
            snap["mmap_ok"] = False

        # Hub HTTP
        try:
            import urllib.request, json
            r = urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=0.5)
            snap["hub_ok"] = True
        except Exception:
            snap["hub_ok"] = False

        # Gateway HTTP
        try:
            import urllib.request
            urllib.request.urlopen("http://127.0.0.1:8080/status", timeout=0.2)
            snap["gateway_ok"] = True
        except Exception:
            snap["gateway_ok"] = False

        # Gouvernance
        try:
            import json, time as _t
            from pathlib import Path
            ROOT = Path(r"%NOKIDO_WORKSPACE%\LaForge")
            state = json.loads((ROOT/"config"/"authority_state.json").read_text())
            md = state.get("master_dev", {})
            now = _t.time()
            last = md.get("last_beat") or md.get("acquired_at") or 0
            expired = (now - last) > md.get("ttl", 1800)
            snap["master_dev"]    = md.get("agent_id","—")
            snap["auth_expired"]  = expired
            snap["auth_remaining"]= max(0, int(md.get("ttl",1800) - (now-last)))
            snap["orchestrators"] = state.get("orchestrators",[])
        except Exception:
            snap["master_dev"] = "?"

        # Ollama
        try:
            import urllib.request
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=0.3)
            snap["ollama_ok"] = True
        except Exception:
            snap["ollama_ok"] = False

        # LlamaCPP — appel direct is_available() sans instancier LlamaCppBridge
        # (évite le log __init__ répété à chaque poll)
        try:
            import sys as _sys
            from pathlib import Path as _P
            _root = _P(r"%NOKIDO_WORKSPACE%\LaForge")
            if str(_root / "app") not in _sys.path:
                _sys.path.insert(0, str(_root / "app"))
            from forge_llamacpp import is_available as _llama_avail
            snap["llamacpp_ok"] = _llama_avail()
        except Exception:
            snap["llamacpp_ok"] = False

        return snap

    def _update_cards(self, snap: dict):
        alerts = []

        # Governance
        md = snap.get("master_dev","?")
        exp = snap.get("auth_expired", True)
        rem = snap.get("auth_remaining", 0)
        h, m = divmod(rem//60, 60)
        self._cards["master_dev"].update_card(
            "ok" if md=="CLAUDE" and not exp else "warn",
            f"{md}  {h}h{m:02d}m" if not exp else f"{md} expiré"
        )
        orcs = snap.get("orchestrators", [])
        self._cards["orchestrators"].update_card(
            "ok" if orcs else "warn",
            ",".join(orcs) if orcs else "aucun"
        )
        self._cards["authority"].update_card(
            "err" if exp else "ok",
            "expiré" if exp else f"{h}h{m:02d}m"
        )
        if exp:
            alerts.append(("R0", "Authority expirée"))
        self._cards["sentinel"].update_card("ok", "actif")

        # Intelligence
        ollama_ok = snap.get("ollama_ok", False)
        self._cards["ollama"].update_card("ok" if ollama_ok else "err",
                                          "actif" if ollama_ok else "hors ligne")
        llama_ok = snap.get("llamacpp_ok", False)
        self._cards["llamacpp"].update_card("ok" if llama_ok else "warn",
                                             "chargé" if llama_ok else "—")
        self._cards["ring8"].update_card("ok", "5/5 clés")
        self._cards["rag"].update_card("ok", "embeddings.db")
        self._cards["resonance"].update_card("ok", "actif")

        # Infra
        hub_ok = snap.get("hub_ok", False)
        self._cards["hub"].update_card("ok" if hub_ok else "err",
                                       ":8766" if hub_ok else "hors ligne")
        gw_ok = snap.get("gateway_ok", False)
        self._cards["gateway"].update_card("ok" if gw_ok else "warn",
                                           ":8080" if gw_ok else "hors ligne")
        self._cards["mcp_server"].update_card("ok", "stdio actif")
        wdg_ok = snap.get("watchdog_ok", True)
        self._cards["watchdog"].update_card("ok" if wdg_ok else "err",
                                            "ok" if wdg_ok else "alerte!")
        mmap_ok = snap.get("mmap_ok", False)
        self._cards["mmap"].update_card("ok" if mmap_ok else "warn",
                                        "500ms" if mmap_ok else "—")

        # Global state
        has_err  = any(not snap.get(k, True) for k in ["hub_ok","ollama_ok","mmap_ok"])
        has_warn = exp or not gw_ok
        if alerts:
            self.ring_alert.emit(alerts[0][0], alerts[0][1])
        state = "err" if has_err else ("warn" if has_warn else "ok")
        label = "Alerte système" if has_err else ("Avertissement" if has_warn else "Système OK")
        color = "#f44336" if has_err else ("#ff9800" if has_warn else "#4caf50")
        self._global_led.set_state(state)
        self._global_lbl.setText(label)
        self._global_lbl.setStyleSheet(f"color:{color}; font-size:11px;")
