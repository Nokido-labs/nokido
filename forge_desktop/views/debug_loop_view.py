"""
forge_desktop/views/debug_loop_view.py
========================================
AUTONOMOUS_DEBUG_LOOP_V1 — UI
Step_By_Step_Glow | Show_Changes_Only diff
"""
from __future__ import annotations
import sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
APP  = ROOT / "app"

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTextEdit, QFrame,
    QSizePolicy, QSplitter, QScrollArea,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPainterPath, QTextCursor

# Palette Catppuccin Mocha
C = {
    "bg":      "#1E1E2E", "bg2":    "#181825",
    "surface": "#313244", "overlay":"#45475A",
    "text":    "#CDD6F4", "sub":    "#BAC2DE",
    "blue":    "#89B4FA", "cyan":   "#89DCEB",
    "green":   "#A6E3A1", "yellow": "#F9E2AF",
    "red":     "#F38BA8", "mauve":  "#CBA6F7",
    "teal":    "#94E2D5",
}
MONO = "font-family:'Cascadia Code','Consolas'; font-size:11px;"

STEP_COLORS = {
    "Write":   C["blue"],
    "Test":    C["yellow"],
    "Analyze": C["mauve"],
    "Refactor":C["cyan"],
}

STATUS_COLORS = {
    "pending": C["overlay"],
    "running": C["cyan"],
    "ok":      C["green"],
    "fail":    C["red"],
}


# ── Worker ────────────────────────────────────────────────────────────────────

class _DebugWorker(QThread):
    step_done  = Signal(dict, int)   # step_result.to_dict(), iter_n
    loop_done  = Signal(dict)

    def __init__(self, task: str, parent=None):
        super().__init__(parent)
        self._task = task

    def run(self):
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        try:
            from forge_recursive_debugger import RecursiveDebugger

            def _on_step(step_result, iter_n):
                self.step_done.emit({
                    "step":       step_result.step,
                    "ok":         step_result.ok,
                    "output":     step_result.output[:800],
                    "errors":     step_result.errors[:5],
                    "elapsed_ms": step_result.elapsed_ms,
                    "diff":       step_result.diff[:600],
                    "code":       step_result.code[:2000],
                }, iter_n)

            debugger = RecursiveDebugger(on_step=_on_step)
            result   = debugger.run(self._task)
            self.loop_done.emit(result)
        except Exception as e:
            import traceback
            self.loop_done.emit({
                "passed": False, "iterations": 0,
                "total_ms": 0, "error": str(e)[:400],
                "tb": traceback.format_exc()[-400:],
            })


# ── Step Glow Card ────────────────────────────────────────────────────────────

class _StepCard(QFrame):
    """Carte d'une etape avec glow animé — Step_By_Step_Glow."""

    def __init__(self, step: str, iteration: int, parent=None):
        super().__init__(parent)
        self.step      = step
        self.iteration = iteration
        self._status   = "pending"
        self._pulse    = 0.0
        self._t        = 0.0
        col = STEP_COLORS.get(step, C["blue"])
        self._col = col
        self.setStyleSheet(
            f"QFrame{{background:{C['bg2']};border:1px solid {col}22;"
            f"border-radius:6px;margin:2px 0;}}"
        )
        lo = QVBoxLayout(self)
        lo.setContentsMargins(10,6,10,6)
        lo.setSpacing(4)
        # Header
        hdr = QHBoxLayout()
        self._iter_lbl = QLabel(f"Iter {iteration}")
        self._iter_lbl.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        self._iter_lbl.setFixedWidth(40)
        hdr.addWidget(self._iter_lbl)
        self._step_lbl = QLabel(step)
        self._step_lbl.setStyleSheet(f"color:{col};font-size:11px;font-weight:700;{MONO}")
        self._step_lbl.setFixedWidth(70)
        hdr.addWidget(self._step_lbl)
        self._status_lbl = QLabel("pending")
        self._status_lbl.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        hdr.addWidget(self._status_lbl)
        hdr.addStretch()
        self._elapsed_lbl = QLabel("")
        self._elapsed_lbl.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        hdr.addWidget(self._elapsed_lbl)
        lo.addLayout(hdr)
        # Output preview
        self._out_lbl = QLabel("")
        self._out_lbl.setWordWrap(True)
        self._out_lbl.setStyleSheet(f"color:{C['sub']};font-size:10px;{MONO}")
        lo.addWidget(self._out_lbl)
        # Timer glow
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._update_glow)
        self._anim.start(16)

    def set_running(self):
        self._status = "running"
        self._status_lbl.setText("RUNNING")
        self._status_lbl.setStyleSheet(f"color:{C['cyan']};font-size:9px;font-weight:700;{MONO}")

    def set_result(self, ok: bool, output: str, elapsed_ms: int, diff: str = ""):
        self._status = "ok" if ok else "fail"
        col = C["green"] if ok else C["red"]
        self._status_lbl.setText("OK" if ok else "FAIL")
        self._status_lbl.setStyleSheet(f"color:{col};font-size:9px;font-weight:700;{MONO}")
        self._elapsed_lbl.setText(f"{elapsed_ms}ms")
        preview = output[:120].replace("\n"," ")
        self._out_lbl.setText(preview)
        self._out_lbl.setStyleSheet(f"color:{col}88;font-size:10px;{MONO}")
        self.setStyleSheet(
            f"QFrame{{background:{C['bg2']};border:1px solid {col}55;"
            f"border-radius:6px;margin:2px 0;}}"
        )
        self._anim.stop()

    def _update_glow(self):
        if self._status != "running":
            return
        import math
        self._t += 0.06
        alpha = int(40 + 30 * math.sin(self._t * 3))
        col = self._col.lstrip("#")
        r,g,b = int(col[0:2],16), int(col[2:4],16), int(col[4:6],16)
        self.setStyleSheet(
            f"QFrame{{background:{C['bg2']};border:1px solid rgba({r},{g},{b},{alpha*2});"
            f"border-radius:6px;margin:2px 0;}}"
        )


# ── Diff Viewer ───────────────────────────────────────────────────────────────

class _DiffViewer(QTextEdit):
    """Show_Changes_Only — affiche le diff coloré."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Cascadia Code", 10))
        self.setStyleSheet(
            f"background:{C['bg2']};color:{C['text']};"
            f"border:1px solid {C['surface']};border-radius:4px;"
        )
        self.setFixedHeight(140)

    def show_diff(self, diff: str):
        self.clear()
        cursor = self.textCursor()
        from PySide6.QtGui import QTextCharFormat, QBrush, QColor
        for line in diff.splitlines():
            fmt = QTextCharFormat()
            if line.startswith("+"):
                fmt.setForeground(QBrush(QColor(C["green"])))
                fmt.setBackground(QBrush(QColor(C["green"] + "15")))
            elif line.startswith("-"):
                fmt.setForeground(QBrush(QColor(C["red"])))
                fmt.setBackground(QBrush(QColor(C["red"] + "15")))
            else:
                fmt.setForeground(QBrush(QColor(C["overlay"])))
            cursor.insertText(line + "\n", fmt)


# ── DebugLoopView ─────────────────────────────────────────────────────────────

class DebugLoopView(QWidget):
    """
    AUTONOMOUS_DEBUG_LOOP_V1 — Vue principale.
    Omnibar tache + pipeline step cards + diff + code final.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _DebugWorker | None = None
        self._cards:  list[_StepCard] = []
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0,0,0,0)
        lo.setSpacing(0)

        # Header
        hdr = QWidget(); hdr.setFixedHeight(40)
        hdr.setStyleSheet(f"background:{C['bg2']};border-bottom:1px solid {C['surface']};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(14,0,14,0)
        title = QLabel("RecursiveDebugger — Self_Healing_Code")
        title.setStyleSheet(f"color:{C['text']};font-size:12px;font-weight:600;{MONO}")
        hl.addWidget(title)
        hl.addStretch()
        self._iter_badge = QLabel("0 / 3 iter")
        self._iter_badge.setStyleSheet(
            f"color:{C['overlay']};font-size:10px;{MONO}"
            f"border:1px solid {C['surface']};border-radius:3px;padding:0 6px;"
        )
        hl.addWidget(self._iter_badge)
        lo.addWidget(hdr)

        # Input
        inp = QWidget(); inp.setFixedHeight(44)
        inp.setStyleSheet(f"background:{C['bg']};border-bottom:1px solid {C['surface']};")
        il = QHBoxLayout(inp); il.setContentsMargins(12,6,12,6); il.setSpacing(8)
        self._task_input = QLineEdit()
        self._task_input.setPlaceholderText(
            "Tache a coder et debugger… ex: Ecris une fonction tri_rapide() avec tests pytest"
        )
        self._task_input.setStyleSheet(
            f"background:{C['bg2']};color:{C['text']};"
            f"border:1px solid {C['surface']};border-radius:6px;"
            f"padding:6px 12px;font-size:12px;{MONO}"
        )
        self._task_input.returnPressed.connect(self._run)
        il.addWidget(self._task_input, 1)
        self._run_btn = QPushButton("▶ Debug Loop")
        self._run_btn.setFixedSize(110,28)
        self._run_btn.setStyleSheet(
            f"background:{C['green']}22;color:{C['green']};"
            f"border:1px solid {C['green']}55;border-radius:5px;"
            f"font-size:11px;{MONO}"
        )
        self._run_btn.clicked.connect(self._run)
        il.addWidget(self._run_btn)
        lo.addWidget(inp)

        # Splitter : steps gauche | diff+code droite
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet(f"background:{C['bg']};")

        # Colonne gauche : step cards
        left = QWidget()
        left.setStyleSheet(f"background:{C['bg']};")
        left.setFixedWidth(280)
        ll = QVBoxLayout(left); ll.setContentsMargins(6,6,6,6); ll.setSpacing(4)
        step_title = QLabel("Pipeline")
        step_title.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}padding:2px 0;")
        ll.addWidget(step_title)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{C['bg']};border:none;}}")
        self._steps_container = QWidget()
        self._steps_container.setStyleSheet(f"background:{C['bg']};")
        self._steps_lo = QVBoxLayout(self._steps_container)
        self._steps_lo.setSpacing(2)
        self._steps_lo.setContentsMargins(0,0,0,0)
        self._steps_lo.addStretch()
        scroll.setWidget(self._steps_container)
        self._steps_scroll = scroll
        ll.addWidget(scroll, 1)
        self._pass_lbl = QLabel("")
        self._pass_lbl.setStyleSheet(f"font-size:11px;font-weight:700;{MONO}padding:4px;")
        ll.addWidget(self._pass_lbl)
        splitter.addWidget(left)

        # Colonne droite : diff + code final
        right = QWidget()
        right.setStyleSheet(f"background:{C['bg']};")
        rl = QVBoxLayout(right); rl.setContentsMargins(6,6,6,6); rl.setSpacing(6)
        diff_lbl = QLabel("Diff (Show_Changes_Only)")
        diff_lbl.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        rl.addWidget(diff_lbl)
        self._diff = _DiffViewer()
        rl.addWidget(self._diff)
        code_hdr = QHBoxLayout()
        code_lbl = QLabel("Code final")
        code_lbl.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        code_hdr.addWidget(code_lbl)
        code_hdr.addStretch()
        copy_btn = QPushButton("Copy")
        copy_btn.setFixedSize(42,18)
        copy_btn.setStyleSheet(
            f"background:{C['surface']};color:{C['sub']};"
            f"border:none;border-radius:3px;font-size:9px;"
        )
        copy_btn.clicked.connect(self._copy_code)
        code_hdr.addWidget(copy_btn)
        self._open_btn = QPushButton("Open")
        self._open_btn.setFixedSize(42,18)
        self._open_btn.hide()
        self._open_btn.setStyleSheet(
            f"background:{C['cyan']}22;color:{C['cyan']};"
            f"border:1px solid {C['cyan']}44;border-radius:3px;font-size:9px;"
        )
        self._open_btn.clicked.connect(self._open_file)
        code_hdr.addWidget(self._open_btn)
        rl.addLayout(code_hdr)
        self._code_view = QTextEdit()
        self._code_view.setReadOnly(True)
        self._code_view.setFont(QFont("Cascadia Code", 10))
        self._code_view.setStyleSheet(
            f"background:{C['bg2']};color:{C['text']};"
            f"border:1px solid {C['surface']};border-radius:4px;"
        )
        rl.addWidget(self._code_view, 1)
        splitter.addWidget(right)
        splitter.setSizes([280, 460])
        lo.addWidget(splitter, 1)

        # Footer status
        self._footer = QLabel("En attente…")
        self._footer.setFixedHeight(24)
        self._footer.setStyleSheet(
            f"background:{C['bg2']};color:{C['overlay']};"
            f"font-size:10px;{MONO}padding:0 12px;"
            f"border-top:1px solid {C['surface']};"
        )
        lo.addWidget(self._footer)

        self._final_path = ""

    # ── Logic ─────────────────────────────────────────────────────────────────

    def _run(self):
        task = self._task_input.text().strip()
        if not task or (self._worker and self._worker.isRunning()):
            return
        # Vider
        while self._steps_lo.count() > 1:
            item = self._steps_lo.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._cards.clear()
        self._diff.show_diff("")
        self._code_view.clear()
        self._pass_lbl.setText("")
        self._open_btn.hide()
        self._final_path = ""
        self._iter_badge.setText("0 / 3 iter")
        self._set_footer("running", "Demarrage debug loop…")
        self._run_btn.setEnabled(False)

        self._worker = _DebugWorker(task, parent=self)
        self._worker.step_done.connect(self._on_step)
        self._worker.loop_done.connect(self._on_done)
        self._worker.start()

    def _on_step(self, step_data: dict, iter_n: int):
        step = step_data.get("step","?")
        ok   = step_data.get("ok", False)
        out  = step_data.get("output","")
        ms   = step_data.get("elapsed_ms",0)
        diff = step_data.get("diff","")

        # Créer ou màj la card
        card = _StepCard(step, iter_n)
        card.set_running()
        self._steps_lo.insertWidget(self._steps_lo.count()-1, card)
        self._cards.append(card)
        self._steps_scroll.verticalScrollBar().setValue(
            self._steps_scroll.verticalScrollBar().maximum()
        )
        # Terminer avec résultat
        QTimer.singleShot(100, lambda: card.set_result(ok, out, ms, diff))

        # Afficher diff si Write/Refactor
        if step in ("Write","Refactor") and diff:
            self._diff.show_diff(diff)

        # Code preview si Write
        if step in ("Write","Refactor") and step_data.get("code"):
            self._code_view.setPlainText(step_data["code"][:3000])

        self._iter_badge.setText(f"{iter_n} / 3 iter")
        self._set_footer(
            "ok" if ok else "warn",
            f"[{step}] iter {iter_n} — {'OK' if ok else 'FAIL'} {ms}ms"
        )

    def _on_done(self, result: dict):
        passed  = result.get("passed", False)
        iters   = result.get("iterations", 0)
        total   = result.get("total_ms", 0)
        final   = result.get("final_code","")
        path    = result.get("final_path","")
        err     = result.get("error","")

        if final:
            self._code_view.setPlainText(final)
        if path:
            self._final_path = path
            self._open_btn.show()

        col = C["green"] if passed else C["red"]
        status = "PASSED" if passed else "FAILED"
        self._pass_lbl.setText(f"  {status}  {iters} iter  {total}ms")
        self._pass_lbl.setStyleSheet(
            f"color:{col};font-size:11px;font-weight:700;{MONO}"
            f"padding:4px;background:{col}15;border-radius:4px;"
        )
        self._set_footer(
            "ok" if passed else "fail",
            f"{status} — {iters} iterations — {total}ms" +
            (f" — {err[:60]}" if err else "")
        )
        self._run_btn.setEnabled(True)

    def _set_footer(self, level: str, msg: str):
        col = {
            "ok":"#A6E3A1","fail":"#F38BA8",
            "warn":"#F9E2AF","running":"#89DCEB"
        }.get(level, C["overlay"])
        self._footer.setText(f"  {msg}")
        self._footer.setStyleSheet(
            f"background:{C['bg2']};color:{col};"
            f"font-size:10px;{MONO}padding:0 12px;"
            f"border-top:1px solid {C['surface']};"
        )

    def _copy_code(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._code_view.toPlainText())

    def _open_file(self):
        if self._final_path:
            import os
            os.startfile(str(Path(self._final_path).parent))

    def closeEvent(self, event):
        """Arrêt propre des workers QThread."""
        if hasattr(self, '_worker') and self._worker is not None:
            if hasattr(self._worker, 'stop'):
                self._worker.stop()
            if hasattr(self._worker, 'wait'):
                self._worker.wait(1000)
            if hasattr(self._worker, 'terminate'):
                self._worker.terminate()
        super().closeEvent(event)