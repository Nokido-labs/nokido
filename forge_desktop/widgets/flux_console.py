"""
forge_desktop/widgets/flux_console.py
=======================================
FLUX_VISIBILITY_V2_EXPERT
Console de sortie experte :
- Stream tokens LLM en temps reel
- MCP calls verbose inline
- Filtrage agents Smart (Local > Free > Paid)
- Artifact tracking avec actions Open/Run/Copy
- Copy button sur code, Retry sur echec, Drawer logs
Palette : Catppuccin Mocha (#1E1E2E base)
"""
from __future__ import annotations
import re, sys, time, json, subprocess, os
from pathlib import Path
from typing import Optional, Callable

ROOT_PATH = Path(__file__).resolve().parent.parent.parent
APP_PATH  = ROOT_PATH / "app"

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QFrame, QApplication,
    QSizePolicy, QScrollArea, QFileDialog,
)
from PySide6.QtCore import Qt, Signal, QTimer, QThread, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import (
    QColor, QFont, QTextCharFormat, QTextCursor,
    QSyntaxHighlighter, QBrush,
)

# ── Palette Catppuccin Mocha ──────────────────────────────────────────────────
C = {
    "bg":       "#1E1E2E",
    "bg2":      "#181825",
    "surface":  "#313244",
    "overlay":  "#45475A",
    "text":     "#CDD6F4",
    "subtext":  "#BAC2DE",
    "blue":     "#89B4FA",
    "cyan":     "#89DCEB",
    "green":    "#A6E3A1",
    "yellow":   "#F9E2AF",
    "red":      "#F38BA8",
    "mauve":    "#CBA6F7",
    "pink":     "#F5C2E7",
    "teal":     "#94E2D5",
    "lavender": "#B4BEFE",
}

MONO = "font-family:'Cascadia Code','JetBrains Mono','Consolas'; font-size:11px;"

# Priorité agents : Local > Free > Paid
AGENT_PRIORITY = [
    # Local
    ("llamacpp",       "LOCAL",  C["green"],  0),
    ("laforge",        "LOCAL",  C["teal"],   1),
    ("ollama_qwen3_8b","LOCAL",  C["teal"],   2),
    # Free
    ("gemini",         "FREE",   C["blue"],   10),
    ("groq_direct",    "FREE",   C["blue"],   11),
    ("groq_70b",       "FREE",   C["blue"],   12),
    ("deepseek_direct","FREE",   C["blue"],   13),
    ("mistral_direct", "FREE",   C["blue"],   14),
    ("xai_grok",       "FREE",   C["blue"],   15),
    # Paid
    ("nokido_mcp",    "PAID",   C["mauve"],  20),
]

def agent_tier(agent_id: str) -> tuple:
    for pid, tier, col, prio in AGENT_PRIORITY:
        if pid.lower() in agent_id.lower():
            return (tier, col, prio)
    return ("LOCAL", C["teal"], 5)

def sort_agents(agents: list[str]) -> list[str]:
    return sorted(agents, key=lambda a: agent_tier(a)[2])

# ── Syntax Highlighter ────────────────────────────────────────────────────────
class _FluxHighlighter(QSyntaxHighlighter):
    """Prismjs_Style — colore les tokens selon leur type."""

    def __init__(self, doc):
        super().__init__(doc)
        def fmt(color, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QBrush(QColor(color)))
            if bold:   f.setFontWeight(700)
            if italic: f.setFontItalic(True)
            return f

        self._rules = [
            # MCP calls
            (re.compile(r"\[MCP\][^\n]*"),           fmt(C["mauve"], bold=True)),
            (re.compile(r"\[TOOL\][^\n]*"),           fmt(C["lavender"], bold=True)),
            # Statuts
            (re.compile(r"\[(OK|DONE|SUCCESS)\]"),     fmt(C["green"], bold=True)),
            (re.compile(r"\[(FAIL|ERR|ERROR)\]"),      fmt(C["red"],   bold=True)),
            (re.compile(r"\[(WARN|WARNING)\]"),        fmt(C["yellow"],bold=True)),
            (re.compile(r"\[(RUN|RUNNING)\]"),         fmt(C["cyan"],  bold=True)),
            (re.compile(r"\[(INFO)\]"),                fmt(C["blue"])),
            # Chemins fichiers
            (re.compile(r"[A-Za-z]:\\[^\s]+|/[^\s]+\.py"),  fmt(C["cyan"])),
            # Timestamps
            (re.compile(r"\d{2}:\d{2}:\d{2}"),        fmt(C["overlay"])),
            # Nombres
            (re.compile(r"\b\d+(\.\d+)?(ms|s|%|L)?\b"), fmt(C["yellow"])),
            # Strings
            (re.compile(r"\"[^\"]*\""),               fmt(C["green"])),
            # Keywords Python
            (re.compile(r"\b(def|class|import|from|return|if|else|for|try|except)\b"),
             fmt(C["mauve"])),
            # Agent tiers inline
            (re.compile(r"\[(LOCAL|FREE|PAID)\]"),     fmt(C["teal"])),
        ]

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end()-m.start(), fmt)


# ── Artifact detector ─────────────────────────────────────────────────────────
def detect_artifacts(text: str) -> list[dict]:
    """Detecte chemins, scripts, fichiers executables dans le texte."""
    artifacts = []
    # Chemins Windows/Unix
    path_re = re.compile(
        r"([A-Za-z]:\\[^\s\n,;]+|/(?:home|tmp|app|forge)[^\s\n,;]+\.(?:py|sh|bat|json|db|txt))"
    )
    for m in path_re.finditer(text):
        raw = m.group(1)
        p   = Path(raw)
        artifacts.append({
            "path":    raw,
            "name":    p.name,
            "exists":  p.exists(),
            "runnable": p.suffix in (".py",".bat",".sh"),
        })
    return artifacts[:5]


# ── Code block widget ─────────────────────────────────────────────────────────
class _CodeBlock(QFrame):
    """Bloc de code avec bouton Copy."""
    def __init__(self, code: str, lang: str = "", parent=None):
        super().__init__(parent)
        self._code = code
        self.setStyleSheet(
            f"QFrame{{background:{C['bg2']};border:1px solid {C['surface']};"
            f"border-radius:6px;margin:2px 0;}}"
        )
        lo = QVBoxLayout(self)
        lo.setContentsMargins(8,4,8,4)
        lo.setSpacing(3)
        # Header
        hdr = QHBoxLayout()
        lang_lbl = QLabel(lang or "code")
        lang_lbl.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        hdr.addWidget(lang_lbl)
        hdr.addStretch()
        copy_btn = QPushButton("Copy")
        copy_btn.setFixedSize(42,18)
        copy_btn.setStyleSheet(
            f"background:{C['surface']};color:{C['subtext']};border:none;"
            f"border-radius:3px;font-size:9px;"
        )
        copy_btn.clicked.connect(self._copy)
        hdr.addWidget(copy_btn)
        lo.addLayout(hdr)
        # Code
        lbl = QLabel(code[:400])
        lbl.setFont(QFont("Cascadia Code", 10))
        lbl.setStyleSheet(f"color:{C['text']};")
        lbl.setWordWrap(True)
        lo.addWidget(lbl)

    def _copy(self):
        QApplication.clipboard().setText(self._code)


# ── Artifact bar ──────────────────────────────────────────────────────────────
class _ArtifactBar(QFrame):
    """Barre d'artifact avec actions Open/Run/Copy."""
    run_requested  = Signal(str)
    open_requested = Signal(str)

    def __init__(self, artifact: dict, parent=None):
        super().__init__(parent)
        self._path = artifact["path"]
        exists = artifact["exists"]
        col = C["cyan"] if exists else C["overlay"]
        self.setStyleSheet(
            f"QFrame{{background:{C['bg2']};border-left:2px solid {col};"
            f"border-radius:3px;margin:1px 0;}}"
        )
        lo = QHBoxLayout(self)
        lo.setContentsMargins(8,3,8,3)
        lo.setSpacing(6)
        # Icone + chemin
        ico = QLabel("F" if exists else "?")
        ico.setFixedWidth(14)
        ico.setStyleSheet(f"color:{col};font-size:10px;font-weight:700;")
        lo.addWidget(ico)
        name_lbl = QLabel(artifact["name"])
        name_lbl.setStyleSheet(
            f"color:{col};font-size:10px;font-weight:600;"
            f"text-decoration:underline;{MONO}"
        )
        lo.addWidget(name_lbl, 1)
        # Actions
        for label, slot in [
            ("Open",  self._open),
            ("Copy",  self._copy),
        ]:
            btn = QPushButton(label)
            btn.setFixedSize(36, 18)
            btn.setStyleSheet(
                f"background:{C['surface']};color:{C['subtext']};"
                f"border:none;border-radius:3px;font-size:9px;"
            )
            btn.clicked.connect(slot)
            lo.addWidget(btn)
        if artifact.get("runnable") and exists:
            run_btn = QPushButton("Run")
            run_btn.setFixedSize(30, 18)
            run_btn.setStyleSheet(
                f"background:{C['green']}22;color:{C['green']};"
                f"border:1px solid {C['green']}44;border-radius:3px;font-size:9px;"
            )
            run_btn.clicked.connect(self._run)
            lo.addWidget(run_btn)

    def _open(self):
        p = Path(self._path)
        if p.parent.exists():
            os.startfile(str(p.parent))
    def _copy(self):
        QApplication.clipboard().setText(self._path)
    def _run(self):
        self.run_requested.emit(self._path)


# ── Log Drawer ────────────────────────────────────────────────────────────────
class _LogEntry(QFrame):
    """Entree de log expandable — Drawer_Style."""
    def __init__(self, level: str, msg: str, ts: str, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._msg      = msg
        level_col = {
            "ERROR": C["red"], "WARN": C["yellow"],
            "INFO":  C["blue"],"OK":   C["green"],
            "MCP":   C["mauve"],"TOKEN":C["cyan"],
        }.get(level, C["subtext"])
        self.setStyleSheet(
            f"QFrame{{background:transparent;border-left:1px solid {level_col}22;"
            f"margin:0;padding:0;}}"
        )
        lo = QVBoxLayout(self)
        lo.setContentsMargins(6,1,4,1)
        lo.setSpacing(0)
        # Header cliquable
        hdr = QHBoxLayout()
        ts_lbl = QLabel(ts)
        ts_lbl.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        ts_lbl.setFixedWidth(60)
        hdr.addWidget(ts_lbl)
        lvl_lbl = QLabel(f"[{level}]")
        lvl_lbl.setFixedWidth(52)
        lvl_lbl.setStyleSheet(f"color:{level_col};font-size:9px;font-weight:700;{MONO}")
        hdr.addWidget(lvl_lbl)
        preview = msg[:80].replace("\n"," ")
        self._preview_lbl = QLabel(preview)
        self._preview_lbl.setStyleSheet(f"color:{C['text']};font-size:10px;{MONO}")
        hdr.addWidget(self._preview_lbl, 1)
        if len(msg) > 80:
            self._expand_btn = QPushButton("v")
            self._expand_btn.setFixedSize(16, 16)
            self._expand_btn.setStyleSheet(
                f"background:transparent;color:{C['overlay']};"
                f"border:none;font-size:9px;"
            )
            self._expand_btn.clicked.connect(self._toggle)
            hdr.addWidget(self._expand_btn)
        lo.addLayout(hdr)
        # Detail (masque par defaut)
        self._detail = QLabel(msg)
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet(f"color:{C['subtext']};font-size:9px;{MONO}padding:2px 4px;")
        self._detail.hide()
        lo.addWidget(self._detail)

    def _toggle(self):
        self._expanded = not self._expanded
        self._detail.setVisible(self._expanded)
        if hasattr(self, "_expand_btn"):
            self._expand_btn.setText("^" if self._expanded else "v")


# ── FluxConsole ───────────────────────────────────────────────────────────────
class FluxConsole(QWidget):
    """
    FLUX_VISIBILITY_V2_EXPERT
    Console de sortie experte.
    API publique :
        console.log(level, message)
        console.stream_token(token)
        console.log_mcp(tool, args, result)
        console.log_agent(agent_id, text, elapsed_ms)
        console.suggest_agents(task, available)
        console.set_retry_callback(fn)
    """
    retry_requested = Signal()
    run_requested   = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._retry_cb: Optional[Callable] = None
        self._token_buffer = ""
        self._token_flush  = QTimer(self)
        self._token_flush.timeout.connect(self._flush_tokens)
        self._token_flush.start(50)
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0,0,0,0)
        lo.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setFixedHeight(30)
        hdr.setStyleSheet(f"background:{C['bg2']};border-bottom:1px solid {C['surface']};")
        hdr_lo = QHBoxLayout(hdr)
        hdr_lo.setContentsMargins(10,0,10,0)
        title = QLabel("Flux Console")
        title.setStyleSheet(f"color:{C['subtext']};font-size:11px;font-weight:600;{MONO}")
        hdr_lo.addWidget(title)
        hdr_lo.addStretch()
        # Agent filter badge
        self._filter_lbl = QLabel("All agents")
        self._filter_lbl.setStyleSheet(
            f"color:{C['overlay']};font-size:9px;{MONO}"
            f"border:1px solid {C['surface']};border-radius:3px;padding:0 5px;"
        )
        hdr_lo.addWidget(self._filter_lbl)
        # Clear
        clr = QPushButton("Clear")
        clr.setFixedSize(40,20)
        clr.setStyleSheet(
            f"background:{C['surface']};color:{C['subtext']};"
            f"border:none;border-radius:3px;font-size:9px;"
        )
        clr.clicked.connect(self.clear)
        hdr_lo.addWidget(clr)
        lo.addWidget(hdr)

        # Agent suggestion strip (masque par defaut)
        self._suggest_frame = QFrame()
        self._suggest_frame.setStyleSheet(
            f"QFrame{{background:{C['bg2']};border-bottom:1px solid {C['surface']};}}"
        )
        self._suggest_lo = QHBoxLayout(self._suggest_frame)
        self._suggest_lo.setContentsMargins(10,4,10,4)
        self._suggest_lo.setSpacing(6)
        self._suggest_frame.hide()
        lo.addWidget(self._suggest_frame)

        # Main scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea{{background:{C['bg']};border:none;}}"
            f"QScrollBar:vertical{{background:{C['bg2']};width:6px;}}"
            f"QScrollBar::handle:vertical{{background:{C['surface']};border-radius:3px;}}"
        )
        self._container = QWidget()
        self._container.setStyleSheet(f"background:{C['bg']};")
        self._log_lo = QVBoxLayout(self._container)
        self._log_lo.setSpacing(1)
        self._log_lo.setContentsMargins(4,4,4,4)
        self._log_lo.addStretch()
        scroll.setWidget(self._container)
        self._scroll = scroll
        lo.addWidget(scroll, 1)

        # Token stream area
        self._token_frame = QFrame()
        self._token_frame.setStyleSheet(
            f"QFrame{{background:{C['bg2']};border-top:1px solid {C['surface']};}}"
        )
        tok_lo = QHBoxLayout(self._token_frame)
        tok_lo.setContentsMargins(10,2,10,2)
        self._stream_lbl = QLabel("")
        self._stream_lbl.setStyleSheet(f"color:{C['cyan']};font-size:10px;{MONO}")
        self._stream_lbl.setWordWrap(False)
        tok_lo.addWidget(self._stream_lbl, 1)
        self._tok_count = QLabel("0 tok")
        self._tok_count.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        tok_lo.addWidget(self._tok_count)
        self._token_frame.hide()
        lo.addWidget(self._token_frame)

        # Footer : retry + status
        ftr = QWidget()
        ftr.setFixedHeight(26)
        ftr.setStyleSheet(f"background:{C['bg2']};border-top:1px solid {C['surface']};")
        ftr_lo = QHBoxLayout(ftr)
        ftr_lo.setContentsMargins(10,0,10,0)
        self._status_lbl = QLabel("Pret")
        self._status_lbl.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        ftr_lo.addWidget(self._status_lbl, 1)
        self._retry_btn = QPushButton("Retry")
        self._retry_btn.setFixedSize(46,18)
        self._retry_btn.setStyleSheet(
            f"background:{C['red']}22;color:{C['red']};"
            f"border:1px solid {C['red']}44;border-radius:3px;font-size:9px;"
        )
        self._retry_btn.hide()
        self._retry_btn.clicked.connect(self._on_retry)
        ftr_lo.addWidget(self._retry_btn)
        lo.addWidget(ftr)
        self._tok_total = 0

    # ── Public API ─────────────────────────────────────────────────────────────

    def log(self, level: str, message: str):
        """Ajoute une entree de log."""
        ts  = time.strftime("%H:%M:%S")
        entry = _LogEntry(level, message, ts)
        self._insert(entry)
        self._set_status(level, message)
        # Detecter artifacts
        for art in detect_artifacts(message):
            bar = _ArtifactBar(art)
            bar.run_requested.connect(self.run_requested)
            self._insert(bar)
        # Afficher retry si erreur
        if level in ("ERROR","FAIL","ERR"):
            self._retry_btn.show()

    def log_mcp(self, tool: str, args: dict, result: str = ""):
        """Log un appel MCP — verbose_inline."""
        args_str = json.dumps(args, ensure_ascii=False)[:80]
        msg = f"[MCP] {tool}({args_str})"
        if result:
            ok = "error" not in result.lower()
            msg += f" -> [{'OK' if ok else 'FAIL'}] {result[:60]}"
        self.log("MCP", msg)

    def log_agent(self, agent_id: str, text: str, elapsed_ms: int = 0):
        """Log une reponse agent avec badge tier."""
        tier, col, _ = agent_tier(agent_id)
        ms_str = f" {elapsed_ms}ms" if elapsed_ms else ""
        header = f"[{tier}] {agent_id}{ms_str}"
        self.log("INFO", f"{header}\n{text[:300]}")

    def stream_token(self, token: str):
        """Ajoute un token au buffer de streaming."""
        self._token_buffer += token
        self._tok_total    += 1
        self._token_frame.show()

    def _flush_tokens(self):
        if not self._token_buffer:
            return
        preview = self._token_buffer[-80:]
        self._stream_lbl.setText(preview)
        self._tok_count.setText(f"{self._tok_total} tok")
        if len(self._token_buffer) > 2000:
            # Flush dans le log principal
            self.log("TOKEN", self._token_buffer[:1000])
            self._token_buffer = ""

    def flush_stream(self, agent_id: str = ""):
        """Termine le stream en cours."""
        if self._token_buffer:
            self.log("TOKEN", self._token_buffer)
            self._token_buffer = ""
        self._stream_lbl.setText("")
        self._token_frame.hide()

    def suggest_agents(self, task: str, available: list[str]):
        """
        Smart_Filtering : affiche les agents capables, tries Local > Free > Paid.
        """
        # Filtrer selon la tache
        task_l = task.lower()
        if any(w in task_l for w in ["code","python","script","test","debug"]):
            preferred = ["llamacpp","laforge","groq_direct","deepseek_direct"]
        elif any(w in task_l for w in ["analyse","rapport","document","resume"]):
            preferred = ["gemini","groq_70b","laforge","mistral_direct"]
        else:
            preferred = available

        sorted_av = sort_agents([a for a in available if a in preferred or a in available])
        # Vider la strip
        while self._suggest_lo.count():
            item = self._suggest_lo.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        lbl = QLabel("Agents:")
        lbl.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        self._suggest_lo.addWidget(lbl)

        for agent in sorted_av[:6]:
            tier, col, _ = agent_tier(agent)
            btn = QPushButton(f"{agent[:10]} [{tier[0]}]")
            btn.setFixedHeight(20)
            btn.setStyleSheet(
                f"background:{col}18;color:{col};border:1px solid {col}44;"
                f"border-radius:4px;font-size:9px;{MONO}padding:0 6px;"
            )
            self._suggest_lo.addWidget(btn)

        self._suggest_lo.addStretch()
        self._filter_lbl.setText(f"{len(sorted_av)} agents | Local > Free > Paid")
        self._suggest_frame.show()

    def add_code_block(self, code: str, lang: str = "python"):
        """Insere un bloc de code avec Copy button."""
        block = _CodeBlock(code, lang)
        self._insert(block)

    def set_retry_callback(self, fn: Callable):
        self._retry_cb = fn

    def clear(self):
        while self._log_lo.count() > 1:
            item = self._log_lo.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._retry_btn.hide()
        self._suggest_frame.hide()
        self._tok_total = 0

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _insert(self, widget: QWidget):
        self._log_lo.insertWidget(self._log_lo.count()-1, widget)
        QTimer.singleShot(20, lambda:
            self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()
            )
        )

    def _set_status(self, level: str, msg: str):
        col = {
            "ERROR": C["red"], "FAIL": C["red"],
            "OK":    C["green"], "DONE": C["green"],
            "MCP":   C["mauve"], "TOKEN": C["cyan"],
        }.get(level, C["subtext"])
        self._status_lbl.setText(f"[{level}] {msg[:60]}")
        self._status_lbl.setStyleSheet(f"color:{col};font-size:9px;{MONO}")

    def _on_retry(self):
        self._retry_btn.hide()
        if self._retry_cb:
            self._retry_cb()
        self.retry_requested.emit()
