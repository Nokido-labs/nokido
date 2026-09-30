"""
forge_desktop/widgets/command_palette.py
=========================================
Smart Omnibar — Dark_Glass — Slide_Down_Spring
BGE-M3 RAG suggestions + Hub v16.5 live query
Ctrl+K global
"""
from __future__ import annotations
import time
import sys
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parent.parent.parent
APP_PATH  = ROOT_PATH / "app"

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QListWidget, QListWidgetItem, QLabel, QFrame, QGraphicsOpacityEffect,
)
from PySide6.QtCore import (
    Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve,
    QPoint, QParallelAnimationGroup, QAbstractAnimation,
)
from PySide6.QtGui import (
    QKeySequence, QShortcut, QColor, QPainter, QPen, QBrush,
    QLinearGradient, QPainterPath,
)

# ── Catalogue commandes ───────────────────────────────────────────────────────
COMMANDS = [
    ("RAG",      "@rag",          "Gestion base de connaissances",    "@rag list"),
    ("RAG",      "@rag reindex",  "Réindexer les documents",          "@rag reindex"),
    ("RAG",      "@rag build",    "Construire embeddings BGE-M3",     "@rag build"),
    ("RAG",      "@rag drop",     "Supprimer un document",            "@rag drop rapport.pdf"),
    ("Agent",    "@mode",         "Changer mode agent",               "@mode set auto"),
    ("Agent",    "@ollama",       "Gérer modèles Ollama",             "@ollama list"),
    ("Agent",    "@debate",       "Débat multi-agent",                "@debate"),
    ("Agent",    "@chain",        "Pipeline chaîné",                  "@chain @ci run | @workflow deploy"),
    ("Agent",    "@mem",          "Mémoire agent",                    "@mem status"),
    ("Infra",    "@run",          "Exécuter commande shell",          "@run df -h"),
    ("Infra",    "@ssh",          "Connexion SSH Freebox",            "@ssh connect"),
    ("Infra",    "@ci",           "CI/CD pipeline",                   "@ci run"),
    ("Infra",    "@workflow",     "Gérer workflows",                  "@workflow list"),
    ("Infra",    "@scan",         "Scanner réseau/ports",             "@scan reseau"),
    ("Dev",      "@test",         "Tester code Python sandbox",       "@test print('ok')"),
    ("Dev",      "@nr",           "Non-régression Nokido",           "@nr"),
    ("Dev",      "@git",          "Opérations git",                   "@git status"),
    ("Dev",      "@loop",         "Boucle autopilot",                 "@loop start"),
    ("Dev",      "@ids",          "IPs suspectes",                    "@ids status"),
    ("Pipeline", "enqueue",       "Ajouter tâche pipeline",           "enqueue <task>"),
    ("Pipeline", "run_next",      "Exécuter prochaine tâche",         "run_next"),
    ("Pipeline", "clear_done",    "Vider tâches terminées",           "clear_done"),
    ("System",   "@proxy",        "Proxy interne",                    "@proxy status"),
    ("System",   "@agentic",      "Mode agentique",                   "@agentic start"),
]

CAT_COL = {
    "RAG":      "#4caf50",
    "Agent":    "#2196f3",
    "Infra":    "#ff9800",
    "Dev":      "#9c27b0",
    "System":   "#f44336",
    "Pipeline": "#00bcd4",
}

MONO = "font-family:'Cascadia Code','Consolas'; font-size:11px;"

# ── At-command syntax highlighter (QLineEdit inline) ──────────────────────────
AT_KEYWORDS = [c[1] for c in COMMANDS if c[1].startswith("@")]


# ── BGE-M3 suggestion worker ──────────────────────────────────────────────────
def _rag_suggest(query: str) -> list[tuple]:
    """Interroge le RAG BGE-M3 pour des suggestions contextuelles."""
    if not query or len(query) < 3:
        return []
    try:
        if str(APP_PATH) not in sys.path:
            sys.path.insert(0, str(APP_PATH))
        from forge_rag_engine import RAGEngine
        engine = RAGEngine()
        hits = engine.search(query, top_k=3)
        suggestions = []
        for h in hits:
            title = h.get("title", h.get("source",""))[:40]
            score = h.get("score", 0)
            suggestions.append(("RAG", f"@rag → {title}", "Suggestion RAG", f"@rag {title}", score))
        return suggestions
    except Exception:
        return []


# ── Hub live query ────────────────────────────────────────────────────────────
def _hub_query(cmd: str) -> str:
    """Envoie une commande au Hub v16.5 et retourne la réponse."""
    try:
        import urllib.request, json
        payload = json.dumps({"command": cmd, "source": "palette"}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8766/command",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        r = urllib.request.urlopen(req, timeout=2)
        data = json.loads(r.read())
        return data.get("result", "")[:120]
    except Exception:
        return ""


# ── Glass background frame ────────────────────────────────────────────────────
class _GlassFrame(QFrame):
    """Fond Dark_Glass avec dégradé subtil et bordure lumineuse."""
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        path = QPainterPath()
        path.addRoundedRect(r.x(), r.y(), r.width(), r.height(), 10, 10)

        # Fond dark glass
        grad = QLinearGradient(0, 0, 0, r.height())
        grad.setColorAt(0.0, QColor(18, 18, 22, 248))
        grad.setColorAt(1.0, QColor(10, 10, 14, 252))
        p.fillPath(path, QBrush(grad))

        # Bordure lumineuse subtile
        pen = QPen(QColor(80, 80, 100, 80), 1)
        p.setPen(pen)
        p.drawPath(path)

        # Ligne highlight haut
        pen2 = QPen(QColor(120, 120, 160, 60), 1)
        p.setPen(pen2)
        p.drawLine(12, 1, r.width()-12, 1)
        p.end()


# ── Vue d'un item de commande ─────────────────────────────────────────────────
class _CmdItemWidget(QWidget):
    def __init__(self, cat: str, cmd: str, desc: str, example: str,
                 highlight: str = "", is_rag: bool = False):
        super().__init__()
        self.setAttribute(Qt.WA_TranslucentBackground)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(8, 3, 8, 3)
        lo.setSpacing(10)

        col = CAT_COL.get(cat, "#888")

        # Badge catégorie
        badge = QLabel(cat)
        badge.setFixedWidth(58)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"color:{col}; font-size:9px; font-weight:700;"
            f" border:1px solid {col}55; border-radius:3px;"
            f" background:{col}18; padding:1px 0;"
            f" font-family:'Cascadia Code','Consolas';"
        )
        lo.addWidget(badge)

        # Commande avec highlight @
        cmd_html = cmd
        if highlight and highlight in cmd:
            cmd_html = cmd.replace(
                highlight,
                f'<span style="color:#4caf50;">{highlight}</span>'
            )
        cmd_lbl = QLabel()
        cmd_lbl.setText(f'<span style="color:#e0ddd4;">{cmd_html}</span>')
        cmd_lbl.setFixedWidth(160)
        cmd_lbl.setStyleSheet(f"{MONO}")
        lo.addWidget(cmd_lbl)

        # Description
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet("color:#555; font-size:10px;")
        lo.addWidget(desc_lbl, 1)

        # Example
        ex_col = "#1a4a3a" if not is_rag else "#1a3a4a"
        ex_lbl = QLabel(example[:40])
        ex_lbl.setStyleSheet(
            f"color:{ex_col}; font-size:9px;"
            f" font-family:'Cascadia Code','Consolas';"
        )
        lo.addWidget(ex_lbl)


# ── CommandPalette principale ─────────────────────────────────────────────────
class CommandPalette(_GlassFrame):
    """
    Smart Omnibar — Dark_Glass — Slide_Down_Spring
    Features :
      • Syntax highlighting @ commandes en temps réel
      • Suggestions BGE-M3 RAG (debounce 300ms)
      • Hub v16.5 live preview
      • Animation Slide_Down_Spring (QPropertyAnimation)
      • Ctrl+K global, Esc ferme, ↑↓ navigation
    """
    command_selected = Signal(str, str)

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        self.setObjectName("CommandPalette")

        self._all_cmds     = list(COMMANDS)
        self._rag_timer    = QTimer()
        self._rag_timer.setSingleShot(True)
        self._rag_timer.timeout.connect(self._fetch_rag)
        self._last_query   = ""
        self._hub_preview  = ""

        self._build()
        self.setFixedWidth(620)
        self.adjustSize()
        self.hide()

        # Animation slide-down spring
        self._opacity_eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_eff)
        self._anim_pos = QPropertyAnimation(self, b"pos")
        self._anim_pos.setEasingCurve(QEasingCurve.OutBack)
        self._anim_pos.setDuration(220)
        self._anim_opacity = QPropertyAnimation(self._opacity_eff, b"opacity")
        self._anim_opacity.setDuration(180)

        # Shortcut Ctrl+K
        sc = QShortcut(QKeySequence("Ctrl+K"), parent)
        sc.activated.connect(self.toggle)

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(10, 10, 10, 10)
        lo.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        ico = QLabel(">_")
        ico.setStyleSheet(
            "color:#4caf50; font-size:15px; font-weight:700;"
            " font-family:'Cascadia Code','Consolas';"
        )
        hdr.addWidget(ico)
        hdr.addSpacing(4)
        title = QLabel("Nokido — Smart Omnibar")
        title.setStyleSheet("color:#666; font-size:11px;")
        hdr.addWidget(title)
        hdr.addStretch()
        self._hub_badge = QLabel("Hub v16.5")
        self._hub_badge.setStyleSheet(
            "color:#00bcd4; font-size:9px; border:1px solid #00bcd422;"
            " border-radius:3px; padding:1px 5px;"
            " font-family:'Cascadia Code','Consolas';"
        )
        hdr.addWidget(self._hub_badge)
        hint = QLabel("Ctrl+K · Esc")
        hint.setStyleSheet("color:#2a2a2a; font-size:9px; margin-left:8px;")
        hdr.addWidget(hint)
        lo.addLayout(hdr)

        # ── Omnibar input ─────────────────────────────────────────────────────
        inp_frame = QFrame()
        inp_frame.setStyleSheet(
            "QFrame { background:#0a0a0e; border:1px solid #2a2a3a;"
            " border-radius:6px; }"
        )
        inp_lo = QHBoxLayout(inp_frame)
        inp_lo.setContentsMargins(10, 0, 10, 0)

        self._prompt_lbl = QLabel("$")
        self._prompt_lbl.setStyleSheet(
            "color:#4caf5088; font-size:13px; font-weight:700;"
            " font-family:'Cascadia Code','Consolas';"
        )
        inp_lo.addWidget(self._prompt_lbl)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type @ command or search…")
        self._input.setStyleSheet(
            "background:transparent; color:#e0ddd4; border:none;"
            " padding:8px 4px; font-size:13px;"
            " font-family:'Cascadia Code','Consolas';"
            " selection-background-color:#1a3a5a;"
        )
        self._input.textChanged.connect(self._on_text)
        self._input.returnPressed.connect(self._execute_selected)
        inp_lo.addWidget(self._input, 1)

        # Live type indicator
        self._type_lbl = QLabel("")
        self._type_lbl.setFixedWidth(60)
        self._type_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._type_lbl.setStyleSheet("color:#333; font-size:9px;")
        inp_lo.addWidget(self._type_lbl)

        lo.addWidget(inp_frame)

        # ── Liste résultats ───────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background:transparent; border:none; outline:none; }"
            "QListWidget::item { border-radius:4px; padding:1px; }"
            "QListWidget::item:selected { background:#1a2a3a; }"
            "QListWidget::item:hover { background:#111118; }"
        )
        self._list.setFrameShape(QFrame.NoFrame)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.setFixedHeight(260)
        lo.addWidget(self._list)

        # ── Footer preview ────────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#1a1a22; border:none; max-height:1px;")
        lo.addWidget(sep)

        ftr = QHBoxLayout()
        self._footer_lbl = QLabel("24 commandes")
        self._footer_lbl.setStyleSheet(
            "color:#333; font-size:9px;"
            " font-family:'Cascadia Code','Consolas';"
        )
        ftr.addWidget(self._footer_lbl)
        ftr.addStretch()
        self._preview_lbl = QLabel("")
        self._preview_lbl.setStyleSheet(
            "color:#1a4a3a; font-size:9px;"
            " font-family:'Cascadia Code','Consolas';"
        )
        ftr.addWidget(self._preview_lbl)
        lo.addLayout(ftr)

        self._populate(self._all_cmds)

    # ── Populate ──────────────────────────────────────────────────────────────
    def _populate(self, cmds: list, highlight: str = ""):
        self._list.clear()
        for entry in cmds:
            cat, cmd, desc, example = entry[0], entry[1], entry[2], entry[3]
            is_rag = (len(entry) > 4)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, (cmd, example))
            w = _CmdItemWidget(cat, cmd, desc, example, highlight, is_rag)
            item.setSizeHint(w.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, w)
        if self._list.count():
            self._list.setCurrentRow(0)
        self._footer_lbl.setText(f"{len(cmds)} résultat{'s' if len(cmds)>1 else ''}")

    # ── Omnibar logic ─────────────────────────────────────────────────────────
    def _on_text(self, text: str):
        self._last_query = text
        q = text.lower().strip()

        # Détecter le type d'input
        if q.startswith("@"):
            self._type_lbl.setText("cmd")
            self._type_lbl.setStyleSheet("color:#4caf50; font-size:9px;")
            self._prompt_lbl.setStyleSheet(
                "color:#4caf50; font-size:13px; font-weight:700;"
                " font-family:'Cascadia Code','Consolas';"
            )
        elif q:
            self._type_lbl.setText("search")
            self._type_lbl.setStyleSheet("color:#2196f3; font-size:9px;")
            self._prompt_lbl.setStyleSheet(
                "color:#2196f388; font-size:13px; font-weight:700;"
                " font-family:'Cascadia Code','Consolas';"
            )
        else:
            self._type_lbl.setText("")
            self._prompt_lbl.setStyleSheet(
                "color:#4caf5088; font-size:13px; font-weight:700;"
                " font-family:'Cascadia Code','Consolas';"
            )

        if not q:
            self._populate(self._all_cmds)
            self._preview_lbl.setText("")
            return

        # Filtre local
        filtered = [c for c in self._all_cmds
                    if q in c[1].lower() or q in c[2].lower() or q in c[0].lower()]

        # Highlight @ si pertinent
        hl = q if q.startswith("@") else ""
        self._populate(filtered, highlight=hl)

        # RAG debounce 300ms
        if len(q) >= 3 and not q.startswith("@"):
            self._rag_timer.start(300)

        # Preview hub
        if filtered:
            self._preview_lbl.setText(filtered[0][3][:50])

    def _fetch_rag(self):
        """Suggestions BGE-M3 — appelé après debounce."""
        q = self._last_query
        if not q or q.startswith("@"):
            return
        suggestions = _rag_suggest(q)
        if suggestions:
            current = [c for c in self._all_cmds
                       if q.lower() in c[1].lower() or q.lower() in c[2].lower()]
            self._populate(current + suggestions)

    # ── Execute ───────────────────────────────────────────────────────────────
    def _execute_selected(self):
        item = self._list.currentItem()
        if not item:
            # Exécuter le texte brut si pas de sélection
            txt = self._input.text().strip()
            if txt:
                self.command_selected.emit(txt, txt)
                self._close_palette()
            return
        cmd, example = item.data(Qt.UserRole)
        self.command_selected.emit(cmd, example)
        self._close_palette()

    def _on_double_click(self, item):
        cmd, example = item.data(Qt.UserRole)
        self.command_selected.emit(cmd, example)
        self._close_palette()

    def _close_palette(self):
        self._animate_out()

    # ── Animation Slide_Down_Spring ───────────────────────────────────────────
    def _animate_in(self, target_pos: QPoint):
        start_pos = QPoint(target_pos.x(), target_pos.y() - 30)
        self.move(start_pos)
        self.show()

        self._anim_pos.stop()
        self._anim_pos.setStartValue(start_pos)
        self._anim_pos.setEndValue(target_pos)
        self._anim_pos.start()

        self._anim_opacity.stop()
        self._anim_opacity.setStartValue(0.0)
        self._anim_opacity.setEndValue(1.0)
        self._anim_opacity.start()

    def _animate_out(self):
        end_pos = QPoint(self.pos().x(), self.pos().y() - 20)
        self._anim_pos.stop()
        self._anim_pos.setStartValue(self.pos())
        self._anim_pos.setEndValue(end_pos)
        self._anim_pos.start()

        self._anim_opacity.stop()
        self._anim_opacity.setStartValue(1.0)
        self._anim_opacity.setEndValue(0.0)
        self._anim_opacity.finished.connect(self._on_hide_done)
        self._anim_opacity.start()

    def _on_hide_done(self):
        self.hide()
        self._input.clear()
        self._populate(self._all_cmds)
        try:
            self._anim_opacity.finished.disconnect(self._on_hide_done)
        except Exception:
            pass

    # ── Toggle ────────────────────────────────────────────────────────────────
    def toggle(self):
        if self.isVisible():
            self._close_palette()
        else:
            parent = self.parent()
            if parent:
                pg = parent.geometry()
                x = pg.x() + (pg.width() - self.width()) // 2
                y = pg.y() + int(pg.height() * 0.18)
                self._animate_in(QPoint(x, y))
            else:
                self.show()
            self._input.setFocus()

    # ── Navigation clavier ────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key_Escape:
            self._close_palette()
        elif k == Qt.Key_Down:
            cur = self._list.currentRow()
            self._list.setCurrentRow(min(cur+1, self._list.count()-1))
        elif k == Qt.Key_Up:
            cur = self._list.currentRow()
            self._list.setCurrentRow(max(cur-1, 0))
        elif k == Qt.Key_Tab:
            # Auto-complétion @ commande
            item = self._list.currentItem()
            if item:
                _, ex = item.data(Qt.UserRole)
                self._input.setText(ex)
                self._input.setCursorPosition(len(ex))
        else:
            super().keyPressEvent(event)
