"""
forge_desktop/widgets/forge_command_palette.py
===============================================
WIDGET_COMMAND_PALETTE_V1
class : ForgeCommandPalette(QWidget)
key   : Ctrl+K
ipc   : MMap_500ms
bridge: localhost:8766 + win32cred_check
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parent.parent.parent
APP_PATH  = ROOT_PATH / "app"

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QListWidget, QListWidgetItem,
    QLabel, QFrame, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
)
from PySide6.QtCore import (
    Qt, Signal, QTimer, QPoint, QSize,
    QPropertyAnimation, QEasingCurve,
)
from forge_desktop.core.palette_hub_connector import PaletteHubConnector
from PySide6.QtGui import (
    QKeySequence, QShortcut, QColor, QPainter,
    QBrush, QPen, QPainterPath, QLinearGradient,
    QFont,
)

# ── Spec UI ───────────────────────────────────────────────────────────────────
BG_COLOR   = "rgba(30, 30, 45, 230)"
BORDER_COL = "#534AB7"
FONT_FACE  = "Anthropic Sans"
FONT_SIZE  = 11
SHADOW_COL = "rgba(0,0,0,0.5)"

# ── Commandes cibles ──────────────────────────────────────────────────────────
# (id, label, description, mcp_tool, args_hint)
PALETTE_COMMANDS = [
    (
        "@disco",
        "@disco",
        "Découverte — scan agents & services actifs",
        "nokido_dispatch",
        {"command": "@disco"},
    ),
    (
        "@collab",
        "@collab",
        "Mode collaboration multi-agent",
        "nokido_dispatch",
        {"command": "@collab"},
    ),
    (
        "@audit",
        "@audit",
        "Audit sécurité & intégrité du projet",
        "nokido_dispatch",
        {"command": "@audit"},
    ),
    (
        "@commit",
        "@commit",
        "Commit git rapide via CI pipeline",
        "nokido_dispatch",
        {"command": "@ci commit"},
    ),
    (
        "@rag_sync",
        "@rag sync",
        "Synchronisation & rebuild RAG embeddings",
        "nokido_dispatch",
        {"command": "@rag build"},
    ),
]

MONO = f"font-family:'{FONT_FACE}','Cascadia Code','Consolas'; font-size:{FONT_SIZE}pt;"


# ── Auth bridge win32cred ─────────────────────────────────────────────────────
def _win32_auth_check() -> bool:
    """Vérifie que FORGE_MCP_TOKEN est présent dans win32cred."""
    try:
        import win32cred
        cred = win32cred.CredRead("FORGE_MCP_TOKEN@Nokido",
                                  win32cred.CRED_TYPE_GENERIC)
        blob = cred.get("CredentialBlob", b"")
        val  = blob.decode("utf-16-le", "replace").rstrip("\x00") if blob else ""
        return bool(val)
    except Exception:
        return False


# ── MMap IPC reader ───────────────────────────────────────────────────────────
def _mmap_state() -> dict:
    """Lit l'état swarm depuis MMap (500ms polling côté caller)."""
    try:
        if str(APP_PATH) not in sys.path:
            sys.path.insert(0, str(APP_PATH))
        from live_bridge import bridge
        snap = bridge.snapshot().get("json", {})
        return {
            "state":  snap.get("swarm.state", "IDLE"),
            "agent":  snap.get("swarm.active_agent", ""),
            "seq":    snap.get("swarm.seq", 0),
        }
    except Exception:
        return {"state": "—", "agent": "", "seq": 0}


# ── MCP dispatcher ────────────────────────────────────────────────────────────
def _dispatch_mcp(tool: str, args: dict, token: str = "") -> dict:
    """
    Envoie un appel MCP au Hub localhost:8766.
    Utilise le token win32cred si disponible.
    """
    try:
        import urllib.request, json
        if not token:
            try:
                import win32cred
                cred = win32cred.CredRead("FORGE_MCP_TOKEN@Nokido",
                                          win32cred.CRED_TYPE_GENERIC)
                blob = cred.get("CredentialBlob", b"")
                token = blob.decode("utf-16-le","replace").rstrip("\x00") if blob else ""
            except Exception:
                pass

        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }).encode()
        req = urllib.request.Request(
            "http://localhost:8766/mcp",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST"
        )
        r = urllib.request.urlopen(req, timeout=5)
        return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


# ── Fond glass personnalisé ───────────────────────────────────────────────────
class _PaletteBg(QWidget):
    """
    Fond RGBA(30,30,45,230) + bordure #534AB7 + shadow.
    Dessiné via QPainter pour respecter la spec exacte.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 10, 10)

        # Fond RGBA(30,30,45,230)
        p.fillPath(path, QBrush(QColor(30, 30, 45, 230)))

        # Bordure #534AB7
        pen = QPen(QColor("#534AB7"), 1.0)
        p.setPen(pen)
        p.drawPath(path)

        # Ligne highlight haut (effet glass)
        pen2 = QPen(QColor(120, 110, 200, 50), 1)
        p.setPen(pen2)
        p.drawLine(12, 1, w - 12, 1)
        p.end()


# ── Item commande ─────────────────────────────────────────────────────────────
class _PaletteItem(QWidget):
    def __init__(self, cmd_id: str, label: str, desc: str,
                 active: bool = False, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(10, 5, 10, 5)
        lo.setSpacing(12)

        # Icône @ colorée
        at_lbl = QLabel(label)
        at_lbl.setFixedWidth(110)
        at_lbl.setStyleSheet(
            "color:#AFA9EC; font-weight:700;"
            f" font-family:'{FONT_FACE}','Cascadia Code','Consolas';"
            f" font-size:{FONT_SIZE}pt;"
        )
        lo.addWidget(at_lbl)

        # Description
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet(
            f"color:#7F77DD; font-size:{FONT_SIZE - 1}pt;"
        )
        lo.addWidget(desc_lbl, 1)

        # Indicateur MMap actif
        if active:
            act_lbl = QLabel("● actif")
            act_lbl.setStyleSheet(
                f"color:#4caf50; font-size:{FONT_SIZE - 2}pt;"
                f" font-family:'{FONT_FACE}','Cascadia Code','Consolas';"
            )
            lo.addWidget(act_lbl)


# ── ForgeCommandPalette ───────────────────────────────────────────────────────
class ForgeCommandPalette(QWidget):
    """
    WIDGET_COMMAND_PALETTE_V1
    Palette de commandes Nokido.

    Signals :
        command_dispatched(str, dict)  — (cmd_id, result)
        palette_opened()
        palette_closed()

    Usage :
        palette = ForgeCommandPalette(main_window)
        palette.command_dispatched.connect(my_handler)
        # Ctrl+K pour ouvrir
    """
    command_dispatched = Signal(str, dict)
    palette_opened     = Signal()
    palette_closed     = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("ForgeCommandPalette")

        # Auth check
        self._auth_ok = _win32_auth_check()

        # MMap polling 500ms
        self._mmap_data: dict = {}
        self._mmap_timer = QTimer(self)
        self._mmap_timer.timeout.connect(self._poll_mmap)
        self._mmap_timer.start(500)

        # Build
        self._build()
        self.setFixedWidth(580)
        self.adjustSize()
        self.hide()

        # Shadow 0px 10px 30px rgba(0,0,0,0.5)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 127))
        self.setGraphicsEffect(shadow)

        # Opacity pour animation
        self._opacity_eff = QGraphicsOpacityEffect(self)
        # Note: ne pas combiner avec shadow — utiliser setWindowOpacity
        self._anim_opacity = QPropertyAnimation(self, b"windowOpacity")
        self._anim_opacity.setDuration(160)

        # Slide animation
        self._anim_pos = QPropertyAnimation(self, b"pos")
        self._anim_pos.setEasingCurve(QEasingCurve.OutBack)
        self._anim_pos.setDuration(200)

        # PaletteHubConnector — COMMAND_HUB_BRIDGE_V17
        self._connector = PaletteHubConnector(self)
        self._connector.result_ready.connect(self._on_connector_result)
        self._connector.dispatch_failed.connect(
            lambda cid, err: self._status_lbl.setText(f'✗ {cid}: {err[:40]}')
        )

        # Ctrl+K
        shortcut = QShortcut(QKeySequence("Ctrl+K"), parent)
        shortcut.activated.connect(self.toggle)

    def _build(self):
        # Fond custom
        self._bg = _PaletteBg(self)

        lo = QVBoxLayout(self)
        lo.setContentsMargins(1, 1, 1, 1)  # laisser la bordure visible

        inner = QWidget()
        inner.setAttribute(Qt.WA_TranslucentBackground)
        inner_lo = QVBoxLayout(inner)
        inner_lo.setContentsMargins(12, 10, 12, 10)
        inner_lo.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()

        logo = QLabel("⬡ Nokido")
        logo.setStyleSheet(
            f"color:#534AB7; font-weight:700; font-size:{FONT_SIZE + 1}pt;"
            f" font-family:'{FONT_FACE}','Cascadia Code','Consolas';"
        )
        hdr.addWidget(logo)
        hdr.addStretch()

        # Auth badge
        self._auth_badge = QLabel("🔓 auth ok" if self._auth_ok else "🔒 no auth")
        self._auth_badge.setStyleSheet(
            f"color:{'#4caf50' if self._auth_ok else '#f44336'};"
            f" font-size:{FONT_SIZE - 2}pt;"
            f" font-family:'{FONT_FACE}','Cascadia Code','Consolas';"
            " border:1px solid; border-radius:3px; padding:0 5px;"
            f" border-color:{'#4caf5033' if self._auth_ok else '#f4433633'};"
        )
        hdr.addWidget(self._auth_badge)

        # MMap state
        self._mmap_badge = QLabel("MMap ●")
        self._mmap_badge.setStyleSheet(
            f"color:#534AB733; font-size:{FONT_SIZE - 2}pt;"
            f" font-family:'{FONT_FACE}','Cascadia Code','Consolas';"
            " margin-left:8px;"
        )
        hdr.addWidget(self._mmap_badge)

        kb_hint = QLabel("Ctrl+K · Esc · ↑↓")
        kb_hint.setStyleSheet(
            f"color:#3C3489; font-size:{FONT_SIZE - 2}pt; margin-left:8px;"
        )
        hdr.addWidget(kb_hint)
        inner_lo.addLayout(hdr)

        # ── Input ─────────────────────────────────────────────────────────────
        self._input = QLineEdit()
        self._input.setPlaceholderText("@disco  @collab  @audit  @commit  @rag_sync")
        font = QFont(FONT_FACE)
        font.setPointSize(FONT_SIZE + 1)
        self._input.setFont(font)
        self._input.setStyleSheet(
            "background: rgba(20,20,35,200);"
            f" color:#CCC9E8;"
            f" border:1px solid #534AB755;"
            " border-radius:6px;"
            " padding:7px 12px;"
            " selection-background-color:#26215C;"
        )
        self._input.textChanged.connect(self._on_text)
        self._input.returnPressed.connect(self._execute)
        inner_lo.addWidget(self._input)

        # ── Liste ─────────────────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget {"
            "  background:transparent; border:none; outline:none;"
            "}"
            "QListWidget::item {"
            "  border-radius:5px; padding:1px 2px;"
            "}"
            "QListWidget::item:selected {"
            f"  background:rgba(83,74,183,60);"
            "}"
            "QListWidget::item:hover {"
            f"  background:rgba(83,74,183,30);"
            "}"
        )
        self._list.setFrameShape(QFrame.NoFrame)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.setFixedHeight(240)
        inner_lo.addWidget(self._list)

        # ── Footer ────────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#534AB722; border:none; max-height:1px;")
        inner_lo.addWidget(sep)

        ftr = QHBoxLayout()
        self._status_lbl = QLabel("Prêt")
        self._status_lbl.setStyleSheet(
            f"color:#3C3489; font-size:{FONT_SIZE - 1}pt;"
            f" font-family:'{FONT_FACE}','Cascadia Code','Consolas';"
        )
        ftr.addWidget(self._status_lbl)
        ftr.addStretch()
        self._result_lbl = QLabel("")
        self._result_lbl.setStyleSheet(
            f"color:#534AB7; font-size:{FONT_SIZE - 2}pt;"
            f" font-family:'{FONT_FACE}','Cascadia Code','Consolas';"
        )
        ftr.addWidget(self._result_lbl)
        inner_lo.addLayout(ftr)

        lo.addWidget(inner)
        self._bg.lower()
        self._populate(PALETTE_COMMANDS)

    # ── MMap polling ──────────────────────────────────────────────────────────
    def _poll_mmap(self):
        data = _mmap_state()
        if data == self._mmap_data:
            return
        self._mmap_data = data
        state = data.get("state", "IDLE")
        col   = "#4caf50" if state == "RUNNING" else "#534AB755"
        self._mmap_badge.setText(f"MMap {state}")
        self._mmap_badge.setStyleSheet(
            f"color:{col}; font-size:{FONT_SIZE - 2}pt;"
            f" font-family:'{FONT_FACE}','Cascadia Code','Consolas';"
            " margin-left:8px;"
        )

    # ── Populate ──────────────────────────────────────────────────────────────
    def _populate(self, cmds: list):
        self._list.clear()
        active_agent = self._mmap_data.get("agent", "")
        for cmd_id, label, desc, tool, args in cmds:
            active = bool(active_agent and cmd_id in active_agent.lower())
            item = QListWidgetItem()
            item.setData(Qt.UserRole, (cmd_id, tool, args))
            w = _PaletteItem(cmd_id, label, desc, active)
            item.setSizeHint(QSize(0, 38))
            self._list.addItem(item)
            self._list.setItemWidget(item, w)
        if self._list.count():
            self._list.setCurrentRow(0)
        self._status_lbl.setText(f"{len(cmds)} commandes")

    # ── Filter ────────────────────────────────────────────────────────────────
    def _on_text(self, text: str):
        q = text.lower().strip()
        if not q:
            self._populate(PALETTE_COMMANDS)
            return
        filtered = [c for c in PALETTE_COMMANDS
                    if q in c[0].lower() or q in c[2].lower()]
        self._populate(filtered)

    # ── Execute ───────────────────────────────────────────────────────────────
    def _execute(self):
        item = self._list.currentItem()
        raw  = self._input.text().strip()

        if not item and not raw:
            return

        if item:
            cmd_id, tool, args = item.data(Qt.UserRole)
        else:
            cmd_id, tool, args = raw, "nokido_dispatch", {"command": raw}

        self._status_lbl.setText(f"Dispatch → {cmd_id}…")
        self._status_lbl.setStyleSheet(
            f"color:#AFA9EC; font-size:{FONT_SIZE - 1}pt;"
            f" font-family:'{FONT_FACE}','Cascadia Code','Consolas';"
        )

        # Dispatch MCP async (timer pour ne pas bloquer UI)
        QTimer.singleShot(0, lambda: self._do_dispatch(cmd_id, tool, args))
        self._close()

    def _do_dispatch(self, cmd_id: str, tool: str, args: dict):
        """Route vers PaletteHubConnector — COMMAND_HUB_BRIDGE_V17."""
        self._status_lbl.setText(f'Dispatching {cmd_id}…')
        self._connector.dispatch(cmd_id, tool, args)

    def _on_connector_result(self, cmd_id: str, result: dict,
                             seq_id: int, ok: bool):
        self.command_dispatched.emit(cmd_id, result)
        col = '#4caf50' if ok else '#f44336'
        txt = f"✓ seq#{seq_id}" if ok else f"✗ {result.get('error','')[:30]}"
        self._result_lbl.setText(f"{cmd_id} → {txt}")
        self._result_lbl.setStyleSheet(
            f'color:{col}; font-size:{FONT_SIZE - 2}pt;'
            f' font-family:\'Cascadia Code\',\'Consolas\';'
        )
        QTimer.singleShot(5000, lambda: self._result_lbl.setText(''))

    def _on_double_click(self, item):
        self._execute()

    # ── Animation Slide_Down_Spring ───────────────────────────────────────────
    def _open(self, target: QPoint):
        start = QPoint(target.x(), target.y() - 28)
        self.move(start)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        self._anim_pos.stop()
        self._anim_pos.setStartValue(start)
        self._anim_pos.setEndValue(target)
        self._anim_pos.start()

        self._anim_opacity.stop()
        self._anim_opacity.setStartValue(0.0)
        self._anim_opacity.setEndValue(1.0)
        self._anim_opacity.start()

        self._input.setFocus()
        self.palette_opened.emit()

    def _close(self):
        end = QPoint(self.pos().x(), self.pos().y() - 18)
        self._anim_pos.stop()
        self._anim_pos.setStartValue(self.pos())
        self._anim_pos.setEndValue(end)
        self._anim_pos.start()

        self._anim_opacity.stop()
        self._anim_opacity.setStartValue(1.0)
        self._anim_opacity.setEndValue(0.0)
        self._anim_opacity.finished.connect(self._finish_close)
        self._anim_opacity.start()

    def _finish_close(self):
        self.hide()
        self._input.clear()
        self._populate(PALETTE_COMMANDS)
        self.palette_closed.emit()
        try:
            self._anim_opacity.finished.disconnect(self._finish_close)
        except Exception:
            pass

    def toggle(self):
        if self.isVisible():
            self._close()
        else:
            parent = self.parent()
            if parent:
                pg = parent.geometry()
                x  = pg.x() + (pg.width() - self.width()) // 2
                y  = pg.y() + int(pg.height() * 0.20)
                self._open(QPoint(x, y))
            else:
                self.show()

    # ── Resize bg ─────────────────────────────────────────────────────────────
    def resizeEvent(self, event):
        self._bg.resize(self.size())
        super().resizeEvent(event)

    # ── Keyboard ──────────────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key_Escape:
            self._close()
        elif k == Qt.Key_Down:
            n = self._list.count()
            if n:
                self._list.setCurrentRow(
                    min(self._list.currentRow() + 1, n - 1))
        elif k == Qt.Key_Up:
            self._list.setCurrentRow(
                max(self._list.currentRow() - 1, 0))
        elif k == Qt.Key_Tab:
            item = self._list.currentItem()
            if item:
                cmd_id, _, _ = item.data(Qt.UserRole)
                self._input.setText(cmd_id)
                self._input.setCursorPosition(len(cmd_id))
        else:
            super().keyPressEvent(event)
