"""
forge_desktop/views/services_view.py — Panneau de Contrôle des Services
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QGroupBox, QPlainTextEdit,
    QFrame, QSizePolicy, QProgressBar, QScrollArea,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont

from forge_desktop.core.desktop_bridge import ServiceController

DARK = ("background:#0a0a0a; color:#c2c0b6;"
        " font-family:'Cascadia Code','Consolas'; font-size:11px;"
        " border:1px solid #333; border-radius:4px;")

SERVICES = ["NokidoHub", "NokidoStreamlit", "LaForgeMCP"]
SVC_LABELS = {
    "NokidoHub":       ("⚒  Hub",       "Port 8766 — API centrale"),
    "NokidoStreamlit": ("📊  Streamlit", "Port 8501 — Web UI"),
    "LaForgeMCP":       ("🔌  MCP",       "Bridge Claude ↔ Nokido"),
}


class ServiceCard(QFrame):
    """Carte d'un service NSSM avec switch on/off et logs."""

    start_requested  = Signal(str)
    stop_requested   = Signal(str)
    restart_requested = Signal(str)
    log_requested    = Signal(str)

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background:#111; border:1px solid #333;"
            " border-radius:8px; padding:8px; }"
        )
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        label, desc = SVC_LABELS.get(name, (name, ""))

        # Header
        header = QHBoxLayout()
        self._icon_label = QLabel("⭕")
        self._icon_label.setStyleSheet("font-size:16px;")
        self._name_label = QLabel(label)
        self._name_label.setStyleSheet("font-size:13px; font-weight:600; color:#c2c0b6;")
        self._pid_label  = QLabel("PID: --")
        self._pid_label.setStyleSheet("font-size:10px; color:#666;")
        header.addWidget(self._icon_label)
        header.addWidget(self._name_label)
        header.addStretch()
        header.addWidget(self._pid_label)
        layout.addLayout(header)

        # Description
        desc_label = QLabel(desc)
        desc_label.setStyleSheet("font-size:10px; color:#555;")
        layout.addWidget(desc_label)

        # Boutons
        btns = QHBoxLayout()
        self._start_btn   = QPushButton("▶ Start")
        self._stop_btn    = QPushButton("⏹ Stop")
        self._restart_btn = QPushButton("↺ Restart")
        self._log_btn     = QPushButton("📄 Logs")

        for btn, slot, color in [
            (self._start_btn,   lambda: self.start_requested.emit(self.name),   "#1a3a1a"),
            (self._stop_btn,    lambda: self.stop_requested.emit(self.name),    "#3a1a1a"),
            (self._restart_btn, lambda: self.restart_requested.emit(self.name), "#1a1a3a"),
            (self._log_btn,     lambda: self.log_requested.emit(self.name),     "#1e1e1e"),
        ]:
            btn.setStyleSheet(
                f"background:{color}; border:1px solid #444; border-radius:4px;"
                " padding:3px 8px; color:#c2c0b6; font-size:11px;"
            )
            btn.clicked.connect(slot)
            btns.addWidget(btn)

        layout.addLayout(btns)

        # Log inline (caché par défaut, visible au hover)
        self._log_box = QPlainTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setMaximumHeight(80)
        self._log_box.setStyleSheet(DARK + "font-size:10px;")
        self._log_box.setVisible(False)
        layout.addWidget(self._log_box)

    def update_state(self, running: bool, pid: int = 0, state_str: str = ""):
        if running:
            self._icon_label.setText("🟢")
            self._name_label.setStyleSheet(
                "font-size:13px; font-weight:600; color:#4caf50;")
        else:
            self._icon_label.setText("⭕")
            self._name_label.setStyleSheet(
                "font-size:13px; font-weight:600; color:#666;")
        self._pid_label.setText("PID: " + (str(pid) if pid else "--"))

    def show_log(self, text: str):
        self._log_box.setPlainText(text)
        self._log_box.setVisible(True)

class ProcessTable(QWidget):
    """Tableau des processus Python actifs avec PID et RAM."""

    kill_requested = Signal(int)   # PID

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        title = QLabel("🐍 Processus Python actifs")
        title.setStyleSheet("font-weight:600; color:#c2c0b6;")
        layout.addWidget(title)

        self._grid_widget = QWidget()
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(4)
        layout.addWidget(self._grid_widget)
        layout.addStretch()

    def update_processes(self, procs: list):
        # Vider la grille
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # En-têtes
        for col, hdr in enumerate(["PID","CMD","RAM MB","CPU%","Kill"]):
            lbl = QLabel(hdr)
            lbl.setStyleSheet("color:#888; font-size:10px; font-weight:600;")
            self._grid.addWidget(lbl, 0, col)
        # Lignes
        for row, p in enumerate(procs[:15], start=1):
            pid  = p.get("pid", 0)
            cmd_full = p.get("cmd","")
            cmd  = cmd_full[:60]
            mb   = p.get("mb", 0)
            cpu  = p.get("cpu", 0)
            for col, val in enumerate([str(pid), cmd, str(mb), str(cpu)+"%"]):
                lbl = QLabel(val)
                lbl.setStyleSheet("font-size:10px; color:#c2c0b6;")
                if col == 1:
                    lbl.setToolTip(cmd_full)
                    lbl.setMinimumWidth(200)
                self._grid.addWidget(lbl, row, col)
            kill_btn = QPushButton("✕")
            kill_btn.setFixedSize(22, 18)
            kill_btn.setStyleSheet(
                "background:#3a1a1a; border:1px solid #f44336;"
                " color:#f44336; border-radius:3px; font-size:10px;"
            )
            kill_btn.clicked.connect(lambda checked, p=pid: self.kill_requested.emit(p))
            self._grid.addWidget(kill_btn, row, 4)


class ServicesView(QWidget):
    """
    Panneau de Contrôle des Services.
    - Interrupteurs NSSM
    - Logs live stream (hover)
    - RAM + VRAM
    - Kill Switch
    - Tableau processus Python
    """

    def __init__(self, ctrl: "ServiceController | None" = None, parent=None):
        super().__init__(parent)
        if ctrl is None:
            from forge_desktop.core.desktop_bridge import ServiceController
            ctrl = ServiceController()
        self._ctrl = ctrl
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Titre
        title = QLabel("⚙  Services & Contrôle système")
        title.setStyleSheet("font-size:14px; font-weight:600; color:#c2c0b6;")
        layout.addWidget(title)

        # ── Section NSSM services ─────────────────────────────────────────────
        svc_group = QGroupBox("Services NSSM")
        svc_group.setStyleSheet(
            "QGroupBox { border:1px solid #3d3d3a; border-radius:6px;"
            " margin-top:8px; color:#888; padding-top:4px; }"
        )
        svc_layout = QHBoxLayout(svc_group)
        self._svc_cards: dict[str, ServiceCard] = {}
        for name in SERVICES:
            card = ServiceCard(name)
            card.start_requested.connect(ctrl.start_service)
            card.stop_requested.connect(ctrl.stop_service)
            card.restart_requested.connect(ctrl.restart_service)
            card.log_requested.connect(self._on_log_request)
            self._svc_cards[name] = card
            svc_layout.addWidget(card)
        layout.addWidget(svc_group)

        # ── RAM + VRAM ────────────────────────────────────────────────────────
        mem_group = QGroupBox("Mémoire")
        mem_group.setStyleSheet(
            "QGroupBox { border:1px solid #3d3d3a; border-radius:6px;"
            " margin-top:8px; color:#888; padding-top:4px; }"
        )
        mem_layout = QHBoxLayout(mem_group)

        self._ram_label = QLabel("RAM : --")
        self._ram_bar   = QProgressBar()
        self._ram_bar.setRange(0, 100)
        self._ram_bar.setFixedHeight(10)
        self._ram_bar.setStyleSheet(
            "QProgressBar { border:1px solid #333; background:#111; border-radius:3px; }"
            "QProgressBar::chunk { background:#2196f3; border-radius:2px; }"
        )
        self._vram_label = QLabel("VRAM : --")

        for w in [self._ram_label, self._ram_bar, self._vram_label]:
            mem_layout.addWidget(w)
        layout.addWidget(mem_group)

        # ── Authority Panel ───────────────────────────────────────────────────
        auth_group = QGroupBox("Gouvernance — MASTER_DEV")
        auth_group.setStyleSheet(
            "QGroupBox { border:1px solid #9c27b0; border-radius:6px;"
            " margin-top:8px; color:#9c27b0; padding-top:4px; }"
        )
        auth_lo = QHBoxLayout(auth_group)

        self._auth_label = QLabel("MASTER_DEV : —")
        self._auth_label.setStyleSheet("color:#c2c0b6; font-size:11px; min-width:160px;")
        auth_lo.addWidget(self._auth_label)

        auth_lo.addStretch()

        self._btn_acquire = QPushButton("⚡ Acquérir")
        self._btn_acquire.setToolTip("Acquérir le token MASTER_DEV (TTL 1800s)")
        self._btn_acquire.setStyleSheet(
            "background:#0a1a0a; border:1px solid #4caf50; color:#4caf50;"
            " border-radius:4px; padding:3px 10px; font-size:11px;"
        )
        self._btn_acquire.clicked.connect(self._on_authority_acquire)
        auth_lo.addWidget(self._btn_acquire)

        self._btn_release = QPushButton("🔓 Libérer")
        self._btn_release.setToolTip("Libérer le token MASTER_DEV")
        self._btn_release.setEnabled(False)
        self._btn_release.setStyleSheet(
            "background:#1a0a0a; border:1px solid #f44336; color:#f44336;"
            " border-radius:4px; padding:3px 10px; font-size:11px;"
        )
        self._btn_release.clicked.connect(self._on_authority_release)
        auth_lo.addWidget(self._btn_release)

        self._btn_to_claude = QPushButton("→ CLAUDE")
        self._btn_to_claude.setToolTip("Transférer MASTER_DEV à CLAUDE")
        self._btn_to_claude.setStyleSheet(
            "background:#0a0a1a; border:1px solid #2196f3; color:#2196f3;"
            " border-radius:4px; padding:3px 10px; font-size:11px;"
        )
        self._btn_to_claude.clicked.connect(lambda: self._on_authority_transfer("CLAUDE"))
        auth_lo.addWidget(self._btn_to_claude)

        layout.addWidget(auth_group)

        # ── Processus Python ──────────────────────────────────────────────────
        self._proc_table = ProcessTable()
        self._proc_table.kill_requested.connect(ctrl.kill_pid)
        layout.addWidget(self._proc_table)

        # ── Kill Switch ────────────────────────────────────────────────────────
        kill_btn = QPushButton("☠  KILL SWITCH — Libérer toute la VRAM")
        kill_btn.setFixedHeight(38)
        kill_btn.setStyleSheet(
            "background:#2a0505; border:2px solid #f44336; color:#f44336;"
            " font-size:14px; font-weight:700; border-radius:6px;"
        )
        kill_btn.clicked.connect(ctrl.kill_switch)
        layout.addWidget(kill_btn)

    # ── Authority handlers ───────────────────────────────────────────────────

    def _on_authority_acquire(self):
        import urllib.request, json as _json
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8080/authority/acquire",
                data=_json.dumps({"ttl": 1800}).encode(),
                headers={"Content-Type": "application/json", "X-Agent-ID": "UI_USER"},
                method="POST",
            )
            r = urllib.request.urlopen(req, timeout=3)
            data = _json.loads(r.read())
            if data.get("ok"):
                self._auth_label.setText(f"MASTER_DEV : {data.get('master_dev','?')} ✓")
                self._btn_acquire.setEnabled(False)
                self._btn_release.setEnabled(True)
            else:
                self._auth_label.setText(f"Refusé : {data.get('reason','?')[:40]}")
        except Exception as e:
            self._auth_label.setText(f"Gateway hors ligne")

    def _on_authority_release(self):
        import urllib.request, json as _json
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8080/authority/release",
                data=b"{}",
                headers={"Content-Type": "application/json", "X-Agent-ID": "UI_USER"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
            self._auth_label.setText("MASTER_DEV : —")
            self._btn_acquire.setEnabled(True)
            self._btn_release.setEnabled(False)
        except Exception as e:
            self._auth_label.setText("Gateway hors ligne")

    def _on_authority_transfer(self, agent_id: str):
        import urllib.request, json as _json
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8080/authority/transfer",
                data=_json.dumps({"new_agent_id": agent_id, "reason": "UI transfer"}).encode(),
                headers={"Content-Type": "application/json", "X-Agent-ID": "UI_USER"},
                method="POST",
            )
            r = urllib.request.urlopen(req, timeout=3)
            data = _json.loads(r.read())
            self._auth_label.setText(f"MASTER_DEV : {data.get('master_dev','?')} ✓")
            self._btn_acquire.setEnabled(False)
            self._btn_release.setEnabled(False)
        except Exception as e:
            self._auth_label.setText("Gateway hors ligne")

    def refresh_authority(self):
        """Appelé par le timer principal pour sync l'état affiché."""
        import urllib.request, json as _json
        try:
            r = urllib.request.urlopen(
                "http://127.0.0.1:8080/status", timeout=2
            )
            data = _json.loads(r.read())
            md = data.get("master_dev") or "—"
            self._auth_label.setText(f"MASTER_DEV : {md}")
            is_me = (md == "UI_USER")
            self._btn_acquire.setEnabled(not is_me)
            self._btn_release.setEnabled(is_me)
        except Exception:
            pass  # Gateway off — silencieux

    def update_services(self, data: dict):
        for name, card in self._svc_cards.items():
            info = data.get("services", {}).get(name, {})
            card.update_state(
                running=info.get("running", False),
                pid=info.get("pid", 0),
                state_str=info.get("state", ""),
            )
        self._proc_table.update_processes(data.get("processes", []))
        # RAM
        mem = data.get("memory", {})
        if mem:
            pct = mem.get("pct", 0)
            self._ram_label.setText(
                f"RAM {mem.get('avail_gb',0)}GB libre / {mem.get('total_gb',0)}GB"
            )
            self._ram_bar.setValue(int(pct))
        # VRAM
        vram = data.get("vram", {})
        if vram:
            gpu_name  = next(iter(vram))
            vram_mb   = vram[gpu_name].get("vram_mb", 0)
            self._vram_label.setText(f"VRAM {vram_mb}MB — {gpu_name[:30]}")

    def update_metrics(self, metrics: dict):
        pass  # réservé pour métriques Hub étendues

    def _on_log_request(self, service_name: str):
        card = self._svc_cards.get(service_name)
        if card:
            text = self._ctrl.read_log_tail(service_name, n=40)
            card.show_log(text)