"""
forge_desktop/views/main_window.py — Fenêtre principale Forge-Sync OS
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "app"))

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QTabWidget, QStatusBar, QLabel, QToolBar, QPushButton,
    QMessageBox,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette, QFont, QAction

# Imports minimaux au top-level — le reste est lazy dans _make_*()
# RingMeterV2 est visible dès le démarrage → import immédiat
from forge_desktop.widgets.ring_meter_v2 import RingMeterV2
from forge_desktop.core.desktop_bridge import (
    MMapPollerWorker, HubPollerWorker,
    WindowsServicesWorker, EventsDBWorker,
    ServiceController,
)
from forge_desktop.core.gui_mmap import gui_mmap

# Lazy imports pour les widgets non visibles au démarrage
def _import_ring_group():
    from forge_desktop.widgets.ring_group_widget import RingGroupWidget
    return RingGroupWidget

def _import_security():
    from forge_desktop.widgets.security_shield import SecurityShield
    return SecurityShield

def _import_timeline():
    from forge_desktop.widgets.debate_timeline import DebateTimeline
    return DebateTimeline

def _import_command_palette():
    from forge_desktop.widgets.command_palette import CommandPalette
    from forge_desktop.widgets.forge_command_palette import ForgeCommandPalette
    return CommandPalette, ForgeCommandPalette

DARK_CSS = """
QMainWindow, QWidget { background:#0e1117; color:#c2c0b6;
    font-family:'Segoe UI'; font-size:13px; }
QTabWidget::pane { border:1px solid #3d3d3a; border-radius:4px; }
QTabBar::tab { background:#1a1a1a; color:#888; padding:6px 16px;
    border:1px solid #333; border-bottom:none; border-radius:4px 4px 0 0; }
QTabBar::tab:selected { background:#0e1117; color:#c2c0b6; border-color:#555; }
QTabBar::tab:hover { background:#222; }
QStatusBar { background:#0a0a0a; color:#666; font-size:11px; }
QToolBar { background:#111; border-bottom:1px solid #333; spacing:6px; }
QPushButton { background:#1e1e1e; border:1px solid #444; border-radius:4px;
    padding:4px 12px; color:#c2c0b6; }
QPushButton:hover { background:#2a2a2a; border-color:#888; }
QPushButton#kill_btn { background:#4a1515; border-color:#f44336; color:#f44336;
    font-weight:600; }
QPushButton#kill_btn:hover { background:#6a1515; }
QLabel#state_idle    { color:#4caf50; font-weight:600; }
QLabel#state_think   { color:#ff9800; font-weight:600; }
QLabel#state_stream  { color:#2196f3; font-weight:600; }
QLabel#state_rag     { color:#9c27b0; font-weight:600; }
QLabel#watchdog_ok   { color:#4caf50; }
QLabel#watchdog_warn { color:#ff5722; font-weight:600; }
"""

STATE_LABEL_IDS = {
    "IDLE":        "state_idle",
    "THINKING":    "state_think",
    "STREAMING":   "state_stream",
    "SYNCING_RAG": "state_rag",
}


class MainWindow(QMainWindow):

    def __init__(self, watchdog_pid: int = 0, parent=None):
        super().__init__(parent)
        self.watchdog_pid = watchdog_pid
        self.setWindowTitle("Forge-Sync OS  v1.0")
        self.resize(1400, 900)
        self.setStyleSheet(DARK_CSS)

        self._ctrl = ServiceController()
        self._ctrl.action_done.connect(self._on_action_done)

        self._setup_toolbar()
        self._setup_tabs()
        self._setup_statusbar()
        self._setup_workers()
        self._setup_heartbeat()

    # ── Toolbar ───────────────────────────────────────────────────────────────
    def _setup_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(__import__("PySide6.QtCore", fromlist=["QSize"]).QSize(16,16))
        self.addToolBar(tb)

        title = QLabel("  ⚒  Forge-Sync OS  ")
        title.setStyleSheet("font-weight:600; font-size:14px; color:#c2c0b6;")
        tb.addWidget(title)

        tb.addSeparator()

        # Swarm state badge
        self._swarm_badge = QLabel("● IDLE")
        self._swarm_badge.setObjectName("state_idle")
        tb.addWidget(QLabel("Swarm : "))
        tb.addWidget(self._swarm_badge)

        tb.addSeparator()

        # Watchdog badge
        self._wd_badge = QLabel("● Watchdog OK")
        self._wd_badge.setObjectName("watchdog_ok")
        tb.addWidget(self._wd_badge)

        tb.addSeparator()

        # Hub badge
        self._hub_badge = QLabel("● Hub offline")
        self._hub_badge.setStyleSheet("color:#f44336;")
        tb.addWidget(self._hub_badge)

        # Spacer
        spacer = QWidget(); spacer.setSizePolicy(
            __import__("PySide6.QtWidgets",fromlist=["QSizePolicy"]).QSizePolicy.Expanding,
            __import__("PySide6.QtWidgets",fromlist=["QSizePolicy"]).QSizePolicy.Preferred,
        )
        tb.addWidget(spacer)

        # Kill Switch
        kill_btn = QPushButton("☠  KILL SWITCH")
        kill_btn.setObjectName("kill_btn")
        kill_btn.setFixedHeight(28)
        kill_btn.clicked.connect(self._on_kill_switch)
        tb.addWidget(kill_btn)

    # ── Tabs — Lazy Loading ───────────────────────────────────────────────────
    # Chaque onglet est un placeholder vide jusqu'au premier clic.
    # L'instanciation réelle se fait dans _materialize_tab().
    # Gain : démarrage 5× plus rapide (14 views → 1 view au démarrage).

    _TAB_DEFS = [
        # Onglets actifs
        ("⬡  ForgeOS",        "_make_forge_os"),
        ("📊  Dashboard",      "_make_dashboard"),
        ("⏱  Time-Machine",   "_make_timemachine"),
        ("⚙  Services",       "_make_services"),
        ("📚  RAG",            "_make_rag"),
        ("📊  Mermaid",        "_make_mermaid"),
        ("⬡  Ring",           "_make_ring"),
        ("⚙  Debug Loop",     "_make_debug_loop"),
        ("⚖  Triad",          "_make_triad"),
        ("🧬  Cerberus",       "_make_cerberus"),
        ("🔧  Forge Externe",  "_make_external_forge"),
    ]

    def _setup_tabs(self):
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tab_loaded  = {}   # index → bool
        self._tab_widgets = {}   # index → real widget (après matérialisation)

        # Wrapper tabs + RingMeterV2
        from PySide6.QtWidgets import QVBoxLayout as _VBox
        _wrapper = QWidget()
        _vlo = _VBox(_wrapper)
        _vlo.setContentsMargins(0,0,0,0)
        _vlo.setSpacing(0)
        _vlo.addWidget(self._tabs)
        self._ring_meter = RingMeterV2()
        _vlo.addWidget(self._ring_meter)
        self.setCentralWidget(_wrapper)

        # Créer les placeholders — ultra-rapide
        for i, (label, _) in enumerate(self._TAB_DEFS):
            placeholder = self._make_placeholder(label)
            self._tabs.addTab(placeholder, label)
            self._tab_loaded[i] = False

        # Matérialiser l'onglet 0 immédiatement (visible au démarrage)
        self._materialize_tab(0)

        # Connecter le signal APRÈS avoir chargé l'onglet 0
        self._tabs.currentChanged.connect(self._on_tab_changed)

    def _make_placeholder(self, label: str) -> QWidget:
        """Placeholder léger affiché avant la matérialisation."""
        from PySide6.QtWidgets import QVBoxLayout as _VBox
        w = QWidget()
        lo = _VBox(w)
        lo.setAlignment(Qt.AlignCenter)
        lbl = QLabel(f"⏳  Chargement {label.strip()} ...")
        lbl.setStyleSheet("color:#444; font-size:13px;")
        lo.addWidget(lbl)
        return w

    def _materialize_tab(self, index: int):
        """Instancie la vraie view pour l'onglet index (si pas encore fait)."""
        if self._tab_loaded.get(index):
            return
        self._tab_loaded[index] = True

        if index >= len(self._TAB_DEFS):
            return

        _, factory_name = self._TAB_DEFS[index]
        factory = getattr(self, factory_name, None)
        if factory is None:
            return

        try:
            real_widget = factory()
            if real_widget is not None:
                self._tab_widgets[index] = real_widget
                self._tabs.removeTab(index)
                self._tabs.insertTab(index, real_widget, self._TAB_DEFS[index][0])
                self._tabs.setCurrentIndex(index)
        except Exception as e:
            # Afficher l'erreur dans le placeholder plutôt que crasher
            err_w = QWidget()
            from PySide6.QtWidgets import QVBoxLayout as _VBox
            lo = _VBox(err_w)
            lo.setAlignment(Qt.AlignCenter)
            lbl = QLabel(f"❌  Erreur: {e}")
            lbl.setStyleSheet("color:#f44336; font-size:11px;")
            lo.addWidget(lbl)
            self._tabs.removeTab(index)
            self._tabs.insertTab(index, err_w, self._TAB_DEFS[index][0])

    # ── Factories (une par onglet) ────────────────────────────────────────────

    def _make_forge_os(self) -> QWidget:
        from forge_desktop.views.forge_os_canvas import ForgeOSCanvas
        self._forge_os = ForgeOSCanvas()
        return self._forge_os

    def _make_dashboard(self) -> QWidget:
        from forge_desktop.views.dashboard_view import DashboardView
        self._dashboard = DashboardView()
        self._dashboard.node_hot_swap.connect(self._on_hot_swap)
        self._dashboard.node_selected.connect(self._on_node_selected)
        return self._dashboard

    def _make_timemachine(self) -> QWidget:
        from forge_desktop.views.timemachine_view import TimeMachineView
        self._timemachine = TimeMachineView()
        return self._timemachine

    def _make_services(self) -> QWidget:
        from forge_desktop.views.services_view import ServicesView
        self._services = ServicesView(self._ctrl)
        return self._services

    def _make_rag(self) -> QWidget:
        from forge_desktop.views.rag_view import RAGView
        self._rag = RAGView()
        self._rag.ingest_requested.connect(self._on_ingest)
        return self._rag

    def _make_mermaid(self) -> QWidget:
        from forge_desktop.views.mermaid_view import MermaidView
        self._mermaid = MermaidView()
        return self._mermaid

    def _make_ring(self) -> QWidget:
        RingGroupWidget = _import_ring_group()
        self._ring_group = RingGroupWidget()
        self._ring_group.ring_alert.connect(
            lambda ring, msg: self._status_left.setText(f"[{ring}] {msg}")
        )
        return self._ring_group

    def _make_debug_loop(self) -> QWidget:
        from forge_desktop.views.debug_loop_view import DebugLoopView
        self._debug_loop = DebugLoopView()
        return self._debug_loop

    def _make_triad(self) -> QWidget:
        from forge_desktop.views.triad_view import TriadView
        self._triad = TriadView()
        return self._triad

    def _make_cerberus(self) -> QWidget:
        from forge_desktop.views.cerberus_view import CerberusView
        self._cerberus = CerberusView()
        return self._cerberus

    def _make_external_forge(self) -> QWidget:
        from forge_desktop.views.external_forge_view import ExternalForgeView
        self._external_forge = ExternalForgeView()
        return self._external_forge

    # ── Status bar ────────────────────────────────────────────────────────────
    def _setup_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_left  = QLabel("Prêt")
        self._status_right = QLabel(
            "Watchdog PID=" + str(self.watchdog_pid)
        )
        sb.addWidget(self._status_left)
        sb.addPermanentWidget(self._status_right)

    # ── Workers QThread ───────────────────────────────────────────────────────
    def _setup_workers(self):
        # MMap — primaire, démarrage immédiat (lecture locale, non-bloquant)
        self._mmap_worker = MMapPollerWorker(interval_ms=500)
        self._mmap_worker.swarm_updated.connect(self._on_swarm_update)
        self._mmap_worker.llm_updated.connect(self._on_llm_update)
        self._mmap_worker.watchdog_alert.connect(self._on_watchdog_alert)
        self._mmap_worker.llm_updated.connect(self._on_agents_thinking)
        self._mmap_worker.start()

        # Hub HTTP — démarrage différé 2s (Hub peut ne pas être prêt)
        self._hub_worker = HubPollerWorker(interval_ms=10000)  # 10s — réduit les pings /metrics
        self._hub_worker.data_ready.connect(self._on_hub_data)
        self._hub_worker.hub_offline.connect(self._on_hub_offline)
        QTimer.singleShot(2000, self._hub_worker.start)

        # Services Windows — démarrage différé 3s (subprocess sc query)
        self._svc_worker = WindowsServicesWorker(interval_ms=5000)
        self._svc_worker.services_ready.connect(self._on_services_data)
        QTimer.singleShot(3000, self._svc_worker.start)

        # Events DB — démarrage différé 4s
        self._events_worker = EventsDBWorker(interval_ms=5000)
        self._events_worker.events_ready.connect(self._on_events_data)
        QTimer.singleShot(4000, self._events_worker.start)

    # ── Heartbeat GUI → MMap (1s) ─────────────────────────────────────────────
    def _setup_heartbeat(self):
        self._hb_timer = QTimer(self)
        self._hb_timer.timeout.connect(self._beat)
        self._hb_timer.start(1000)

    def _beat(self):
        view_names = ["dashboard","debate","timemachine","services"]
        cur = view_names[min(self._tabs.currentIndex(), len(view_names)-1)]
        gui_mmap.beat(cur)

    # ── Slots signaux workers ─────────────────────────────────────────────────
    def _on_swarm_update(self, data: dict):
        state = data.get("state", "IDLE")
        agent = data.get("active_agent", "")
        # Toolbar badge
        text = "● " + state + (" (" + agent + ")" if agent else "")
        self._swarm_badge.setText(text)
        obj_id = STATE_LABEL_IDS.get(state, "state_idle")
        self._swarm_badge.setObjectName(obj_id)
        self._swarm_badge.setStyle(self._swarm_badge.style())
        # Propager au dashboard
        if agent:
            self._dashboard.graph.update_node_state(agent, state)
        # Status bar
        self._status_left.setText("Swarm : " + state
                                   + ("  agent=" + agent if agent else "")
                                   + "  seq=" + str(data.get("seq",0)))

    def _on_llm_update(self, llm_data: dict):
        self._dashboard.brain_rail.update_participants(
            [{"id": k, "label": k, **v} for k, v in llm_data.items()],
            {}
        )

    def _on_watchdog_alert(self, alert: bool):
        if alert:
            self._wd_badge.setText("⚠ Watchdog ALERT")
            self._wd_badge.setObjectName("watchdog_warn")
            self._wd_badge.setStyle(self._wd_badge.style())
            self._status_left.setText("⚠ WATCHDOG ALERTE — GUI trop lente")
        else:
            self._wd_badge.setText("● Watchdog OK")
            self._wd_badge.setObjectName("watchdog_ok")
            self._wd_badge.setStyle(self._wd_badge.style())

    def _on_hub_data(self, data: dict):
        health  = data.get("health", {})
        metrics = data.get("metrics", {})
        team    = data.get("team", {})
        ver     = health.get("version", "?")
        self._hub_badge.setText("● Hub v" + ver)
        self._hub_badge.setStyleSheet("color:#4caf50;")
        # Charger le graphe nodal si team a changé (view peut ne pas être chargée)
        if team.get("active_count", 0) > 0:
            if hasattr(self, "_dashboard") and hasattr(self._dashboard, "graph"):
                try:
                    self._dashboard.graph.load_team(
                        {"participants": team.get("active", [])}
                    )
                except Exception:
                    pass
        # Métriques dans services (lazy — peut ne pas exister encore)
        if hasattr(self, "_services") and hasattr(self._services, "update_metrics"):
            try:
                self._services.update_metrics(metrics)
            except Exception:
                pass

    def _on_hub_offline(self):
        self._hub_badge.setText("● Hub offline")
        self._hub_badge.setStyleSheet("color:#f44336;")

    def _on_services_data(self, data: dict):
        # Guard — ServicesView peut ne pas encore être matérialisée
        if hasattr(self, "_services") and hasattr(self._services, "update_services"):
            try:
                self._services.update_services(data)
            except Exception:
                pass
        # RAM dans status bar right (toujours disponible)
        mem = data.get("memory", {})
        if mem:
            self._status_right.setText(
                "RAM " + str(mem.get("pct", 0)) + "%  "
                + "libre " + str(mem.get("avail_gb", 0)) + "GB  "
                + "WD PID=" + str(self.watchdog_pid)
            )

    def _on_events_data(self, events: list):
        # Guard — DashboardView peut ne pas encore être matérialisée
        if not (hasattr(self, "_dashboard")
                and hasattr(self._dashboard, "terminal")):
            return
        try:
            self._dashboard.terminal.append_raw(
                "─── " + str(len(events)) + " events ───"
            )
            for ev in events[:5]:
                self._dashboard.terminal.append_event(ev)
        except Exception:
            pass

    def _on_tab_changed(self, idx: int):
        # Lazy loading — matérialiser l'onglet si pas encore fait
        self._materialize_tab(idx)
        # Mettre à jour la mmap
        views = ["forge_os","dashboard","timemachine","services",
                 "rag","mermaid","ring","debug_loop","triad",
                 "cerberus","external_forge"]
        if idx < len(views):
            try:
                gui_mmap.beat(views[idx])
            except Exception:
                pass

    # ── Actions ───────────────────────────────────────────────────────────────
    def _on_kill_switch(self):
        reply = QMessageBox.warning(
            self, "Kill Switch",
            "Tuer TOUS les processus Nokido ?\n(Ollama, Hub, MCP, Bridge...)",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply == QMessageBox.Yes:
            self._ctrl.kill_switch()

    def _on_hot_swap(self, node_id: str, model: str):
        self._status_left.setText(
            "Hot-swap : " + node_id + " → " + model
        )
        # TODO : écrire dans mmap llm.{node_id}.model_pending
        try:
            gui_mmap._bridge.json_set(
                "llm." + node_id + ".model_pending", model
            )
        except Exception:
            pass

    def _on_node_selected(self, node_id: str):
        self._status_left.setText("Node sélectionné : " + node_id)

    def _on_agents_thinking(self, llm_data: dict):
        """Reçoit les données agents depuis MMap (100ms) → vue Conscience."""
        self._consciousness.update_agents(llm_data)
        # Lire aussi résonance depuis mmap
        try:
            from forge_desktop.core.gui_mmap import gui_mmap
            from forge_desktop.core.desktop_bridge import MMapPollerWorker
            snap = gui_mmap.full_snapshot()
            resonance = {
                'last_agent':  snap.get('resonance.last_agent', ''),
                'last_action': snap.get('resonance.last_action', 'pass'),
                'drift_score': snap.get('resonance.drift_score', 0.0),
            }
            self._consciousness.update_resonance(resonance)
        except Exception:
            pass

    def _on_ingest(self, path_or_url: str, db_path: str):
        """Délègue l'ingestion à forge_web_service (DETACHED)."""
        import sys
        from pathlib import Path as _P
        _ROOT = _P(__file__).resolve().parent.parent.parent
        if str(_ROOT / 'app') not in sys.path:
            sys.path.insert(0, str(_ROOT / 'app'))
        try:
            from forge_web_service import svc
            if path_or_url.startswith('http'):
                r = svc.rag_warmup()
            else:
                r = svc.rag_reindex(changed_only=False)
            self._rag.log_ingest(
                ('✅ Ingéré : ' + path_or_url[:40]) if r else '❌ Erreur',
                db_path
            )
        except Exception as e:
            self._status_left.setText('Ingest ERR: ' + str(e)[:60])

    def _on_action_done(self, name: str, ok: bool, msg: str):
        icon = "✅" if ok else "❌"
        self._status_left.setText(icon + " " + name + " : " + msg)

    # ── Shutdown propre ────────────────────────────────────────────────────────
    def closeEvent(self, event):
        """Arrêt propre — stoppe tous les workers avant de quitter."""
        # 1. Stopper les workers de polling
        for attr in ["_mmap_worker", "_hub_worker",
                     "_svc_worker", "_events_worker"]:
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                w.stop()
                w.wait(1000)
                if w.isRunning():
                    w.terminate()
            except Exception:
                pass

        # 2. Fermer RingMeterV2 (son HealthWorker)
        try:
            self._ring_meter.closeEvent(event)
        except Exception:
            pass

        # 3. Fermer les views matérialisées (leur closeEvent stoppe leurs workers)
        for widget in self._tab_widgets.values():
            try:
                widget.closeEvent(event)
            except Exception:
                pass

        # 4. Signaler la fermeture propre au watchdog (il s'auto-exitera)
        try:
            gui_mmap.set("gui.heartbeat", 0.0)
            gui_mmap.set("gui.pid",       0)
        except Exception:
            pass

        # 5. MMap shutdown
        try:
            gui_mmap.shutdown()
        except Exception:
            pass

        event.accept()
