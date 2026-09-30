"""
forge_desktop/views/triad_view.py
LAFORGE_MULTI_AGENT_SYNTAX_V1 — Triad_Authority UI
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
APP  = ROOT / "app"
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTextEdit, QFrame, QSplitter,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QColor, QFont

C = {"bg":"#1E1E2E","bg2":"#181825","surface":"#313244","overlay":"#45475A",
     "text":"#CDD6F4","sub":"#BAC2DE","blue":"#89B4FA","cyan":"#89DCEB",
     "green":"#A6E3A1","yellow":"#F9E2AF","red":"#F38BA8","mauve":"#CBA6F7"}
MONO = "font-family:'Cascadia Code','Consolas'; font-size:11px;"

STEP_CFG = {
    "audit":   ("Audit",   "auditor",      C["mauve"]),
    "plan":    ("Plan",    "orchestrator", C["blue"]),
    "execute": ("Execute", "worker",       C["cyan"]),
    "verify":  ("Verify",  "auditor",      C["green"]),
}


class _TriadWorker(QThread):
    step_update = Signal(str, str, str)
    done        = Signal(dict)

    def __init__(self, target: str, parent=None):
        super().__init__(parent)
        self._target = target

    def run(self):
        if str(APP) not in sys.path: sys.path.insert(0, str(APP))
        try:
            from forge_triad_authority import TriadOrchestrator
            def _cb(step, status, msg):
                self.step_update.emit(step, status, msg)
            orc    = TriadOrchestrator(on_update=_cb)
            result = orc.run(self._target)
            self.done.emit(result)
        except Exception as e:
            self.done.emit({"passed":False,"status":"error","error":str(e)[:300]})


class _StepIndicator(QFrame):
    def __init__(self, step_id: str, parent=None):
        super().__init__(parent)
        label, role, col = STEP_CFG.get(step_id, (step_id, step_id, C["overlay"]))
        self._col = col
        self.setStyleSheet(
            f"QFrame{{background:{C['bg2']};border:1px solid {col}22;border-radius:6px;margin:2px 0;}}"
        )
        lo = QVBoxLayout(self); lo.setContentsMargins(10,6,10,6); lo.setSpacing(3)
        hdr = QHBoxLayout()
        role_lbl = QLabel(f"[{role.upper()}]")
        role_lbl.setStyleSheet(f"color:{col};font-size:9px;font-weight:700;{MONO}width:90px;")
        hdr.addWidget(role_lbl)
        self._status_lbl = QLabel("PENDING")
        self._status_lbl.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        hdr.addWidget(self._status_lbl)
        hdr.addStretch()
        self._ms_lbl = QLabel("")
        self._ms_lbl.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        hdr.addWidget(self._ms_lbl)
        lo.addLayout(hdr)
        self._out_lbl = QLabel(label)
        self._out_lbl.setStyleSheet(f"color:{C['sub']};font-size:10px;{MONO}")
        self._out_lbl.setWordWrap(True)
        lo.addWidget(self._out_lbl)

    def set_status(self, status: str, msg: str = ""):
        col = C["green"] if status == "done" else C["red"] if status == "fail" else C["cyan"] if status == "running" else C["overlay"]
        self._status_lbl.setText(status.upper())
        self._status_lbl.setStyleSheet(f"color:{col};font-size:9px;font-weight:700;{MONO}")
        if msg: self._out_lbl.setText(msg[:120])
        self.setStyleSheet(
            f"QFrame{{background:{C['bg2']};border:1px solid {col}44;border-radius:6px;margin:2px 0;}}"
        )


class TriadView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._indicators = {}
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self); lo.setContentsMargins(0,0,0,0); lo.setSpacing(0)
        # Header
        hdr = QWidget(); hdr.setFixedHeight(40)
        hdr.setStyleSheet(f"background:{C['bg2']};border-bottom:1px solid {C['surface']}")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(14,0,14,0)
        title = QLabel("Triad Authority — Audit > Plan > Execute > Verify")
        title.setStyleSheet(f"color:{C['text']};font-size:12px;font-weight:600;{MONO}")
        hl.addWidget(title)
        hl.addStretch()
        self._verdict_lbl = QLabel("")
        self._verdict_lbl.setStyleSheet(f"font-size:11px;font-weight:700;{MONO}")
        hl.addWidget(self._verdict_lbl)
        lo.addWidget(hdr)
        # Input
        inp = QWidget(); inp.setFixedHeight(42)
        inp.setStyleSheet(f"background:{C['bg']};border-bottom:1px solid {C['surface']}")
        il = QHBoxLayout(inp); il.setContentsMargins(12,6,12,6); il.setSpacing(8)
        self._target_input = QLineEdit()
        self._target_input.setPlaceholderText("Module cible… ex: app/forge_llamacpp.py ou forge_desktop/core/canvas_nodes.py")
        self._target_input.setStyleSheet(
            f"background:{C['bg2']};color:{C['text']};border:1px solid {C['surface']};border-radius:6px;padding:5px 12px;font-size:12px;{MONO}"
        )
        self._target_input.returnPressed.connect(self._run)
        il.addWidget(self._target_input, 1)
        self._run_btn = QPushButton("▶ Run Triad")
        self._run_btn.setFixedSize(100, 28)
        self._run_btn.setStyleSheet(
            f"background:{C['mauve']}22;color:{C['mauve']};border:1px solid {C['mauve']}55;border-radius:5px;font-size:11px;{MONO}"
        )
        self._run_btn.clicked.connect(self._run)
        il.addWidget(self._run_btn)
        lo.addWidget(inp)
        # Splitter : steps | output
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet(f"background:{C['bg']}")
        # Steps
        steps_w = QWidget(); steps_w.setFixedWidth(260)
        steps_w.setStyleSheet(f"background:{C['bg']}")
        sl = QVBoxLayout(steps_w); sl.setContentsMargins(8,8,8,8); sl.setSpacing(6)
        steps_title = QLabel("Pipeline Triad")
        steps_title.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        sl.addWidget(steps_title)
        for step_id in ["audit","plan","execute","verify"]:
            ind = _StepIndicator(step_id)
            self._indicators[step_id] = ind
            sl.addWidget(ind)
        sl.addStretch()
        splitter.addWidget(steps_w)
        # Output
        out_w = QWidget(); out_w.setStyleSheet(f"background:{C['bg']}")
        ol = QVBoxLayout(out_w); ol.setContentsMargins(8,8,8,8); ol.setSpacing(4)
        out_title = QLabel("Output")
        out_title.setStyleSheet(f"color:{C['overlay']};font-size:9px;{MONO}")
        ol.addWidget(out_title)
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Cascadia Code", 10))
        self._output.setStyleSheet(
            f"background:{C['bg2']};color:{C['text']};border:1px solid {C['surface']};border-radius:4px;"
        )
        ol.addWidget(self._output, 1)
        splitter.addWidget(out_w)
        splitter.setSizes([260, 460])
        lo.addWidget(splitter, 1)
        # Footer
        self._footer = QLabel("  En attente…")
        self._footer.setFixedHeight(24)
        self._footer.setStyleSheet(
            f"background:{C['bg2']};color:{C['overlay']};font-size:10px;{MONO}padding:0 12px;border-top:1px solid {C['surface']}"
        )
        lo.addWidget(self._footer)

    def _run(self):
        target = self._target_input.text().strip()
        if not target or (self._worker and self._worker.isRunning()): return
        for ind in self._indicators.values(): ind.set_status("pending", "")
        self._output.clear()
        self._verdict_lbl.setText("")
        self._run_btn.setEnabled(False)
        self._footer.setText("  Demarrage Triad Authority…")
        self._worker = _TriadWorker(target, parent=self)
        self._worker.step_update.connect(self._on_step)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_step(self, step: str, status: str, msg: str):
        if step in self._indicators:
            self._indicators[step].set_status(status, msg)
        self._output.append(f"[{step.upper()}] {status}: {msg}")
        self._footer.setText(f"  [{step.upper()}] {status} — {msg[:60]}")

    def _on_done(self, result: dict):
        status  = result.get("status","?")
        elapsed = result.get("elapsed_ms", 0)
        passed  = result.get("passed", False)
        col = C["green"] if passed else C["red"]
        self._verdict_lbl.setText(f"  {status}  {elapsed}ms")
        self._verdict_lbl.setStyleSheet(f"color:{col};font-size:11px;font-weight:700;{MONO}")
        # Afficher le rapport complet
        for sname, sdata in result.get("steps",{}).items():
            out = sdata.get("output","")[:400]
            self._output.append(f"\n=== {sname.upper()} [{sdata.get('agent','?')}] {sdata.get('elapsed_ms',0)}ms ===")
            self._output.append(out)
        self._footer.setText(f"  DONE — {status} — {elapsed}ms")
        self._run_btn.setEnabled(True)

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