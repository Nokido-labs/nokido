"""
forge_desktop/views/graph_canvas_view.py
AUTONOMOUS_ORCHESTRATOR_V17 — GraphCanvas_Interactive
Visualise le DAG en temps reel. Style Cellular_Atomic_V2.
MMap_500ms_Visualizer integre.
"""
from __future__ import annotations
import sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
APP  = ROOT / "app"

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QScrollArea,
    QSizePolicy, QFrame,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont,
    QPainterPath, QLinearGradient,
)

MONO = "font-family:'Cascadia Code','Consolas';"

STATUS_COLORS = {
    "pending":  "#333",
    "running":  "#00bcd4",
    "done":     "#4caf50",
    "failed":   "#f44336",
    "blocked":  "#9c27b0",
}


# --------------------------------------------------------------------------
# Worker QThread — execute l'orchestrateur autonome
# --------------------------------------------------------------------------

class _OrchestratorWorker(QThread):
    node_updated  = Signal(dict)
    graph_ready   = Signal(dict)
    run_done      = Signal(dict)

    def __init__(self, instruction: str, use_llm: bool = False, parent=None):
        super().__init__(parent)
        self._instruction = instruction
        self._use_llm     = use_llm

    def run(self):
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        try:
            from forge_autonomous_orchestrator import get_orchestrator
            orc = get_orchestrator(on_update=lambda d: self.node_updated.emit(d))
            result = orc.run_sync(self._instruction, self._use_llm)
            graph  = orc.last_graph()
            if graph:
                self.graph_ready.emit(graph)
            self.run_done.emit(result)
        except Exception as e:
            import traceback
            self.run_done.emit({"ok": 0, "total": 0, "error": str(e)[:300]})


# --------------------------------------------------------------------------
# Canvas SVG-like — dessine le DAG
# --------------------------------------------------------------------------

class _DAGCanvas(QWidget):
    """Widget de dessin du DAG — style Cellular_Atomic_V2."""
    node_clicked = Signal(str)

    NODE_W = 130
    NODE_H = 48

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes: list[dict] = []
        self._edges: list[dict] = []
        self.setMinimumHeight(280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Timer 60fps pour animation pulse
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self.update)
        self._anim_timer.start(16)
        self._t = 0.0

    def set_graph(self, nodes: list[dict], edges: list[dict]):
        self._nodes = nodes
        self._edges = edges
        self.update()

    def update_node(self, node: dict):
        for i, n in enumerate(self._nodes):
            if n["id"] == node["id"]:
                self._nodes[i] = node
                break
        self.update()

    def paintEvent(self, _):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._t += 0.05
        w, h = self.width(), self.height()

        # Fond
        p.fillRect(0, 0, w, h, QColor(8, 8, 12))

        if not self._nodes:
            p.setPen(QPen(QColor("#333")))
            f = QFont("Cascadia Code", 11)
            p.setFont(f)
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "En attente d'une instruction…")
            p.end()
            return

        # Mise a l'echelle : adapter les coordonnees au canvas
        if self._nodes:
            xs = [n.get("x", 0) for n in self._nodes]
            ys = [n.get("y", 0) for n in self._nodes]
            max_x = max(xs) + self.NODE_W + 40
            max_y = max(ys) + self.NODE_H + 40
            scale_x = (w - 40) / max(1, max_x)
            scale_y = (h - 40) / max(1, max_y)
            scale   = min(scale_x, scale_y, 1.0)
        else:
            scale = 1.0

        def sx(x): return 20 + x * scale
        def sy(y): return 20 + y * scale
        nw = self.NODE_W * scale
        nh = self.NODE_H * scale

        # Index noeuds par id
        node_map = {n["id"]: n for n in self._nodes}

        # Dessiner edges
        for e in self._edges:
            fn = node_map.get(e.get("from",""))
            tn = node_map.get(e.get("to",""))
            if not fn or not tn:
                continue
            x1 = sx(fn.get("x",0)) + nw
            y1 = sy(fn.get("y",0)) + nh/2
            x2 = sx(tn.get("x",0))
            y2 = sy(tn.get("y",0)) + nh/2
            # Couleur selon statut source
            src_status = fn.get("status","pending")
            edge_col = QColor(STATUS_COLORS.get(src_status, "#333"))
            edge_col.setAlpha(120)
            pen = QPen(edge_col, 1.5)
            pen.setStyle(Qt.DashLine if src_status == "pending" else Qt.SolidLine)
            p.setPen(pen)
            # Bezier
            path = QPainterPath()
            path.moveTo(x1, y1)
            cx = (x1 + x2) / 2
            path.cubicTo(cx, y1, cx, y2, x2, y2)
            p.drawPath(path)
            # Fleche
            p.setBrush(QBrush(edge_col))
            p.setPen(Qt.NoPen)
            arr = QPainterPath()
            arr.moveTo(x2, y2)
            arr.lineTo(x2-8*scale, y2-4*scale)
            arr.lineTo(x2-8*scale, y2+4*scale)
            arr.closeSubpath()
            p.drawPath(arr)

        # Dessiner noeuds — style Cellular_Atomic_V2
        for node in self._nodes:
            nx = sx(node.get("x", 0))
            ny = sy(node.get("y", 0))
            status = node.get("status", "pending")
            col    = QColor(STATUS_COLORS.get(status, "#333"))

            # Halo pulse si running
            if status == "running":
                pulse = 0.3 + 0.2 * math.sin(self._t * 3)
                halo  = QColor(col)
                halo.setAlphaF(pulse)
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(halo))
                p.drawRoundedRect(QRectF(nx-6, ny-6, nw+12, nh+12), 10, 10)

            # Corps du noeud
            grad = QLinearGradient(nx, ny, nx, ny+nh)
            dark = QColor(col); dark.setAlpha(30)
            mid  = QColor(col); mid.setAlpha(15)
            grad.setColorAt(0.0, dark)
            grad.setColorAt(1.0, mid)
            p.setBrush(QBrush(grad))
            p.setPen(QPen(col, 1))
            p.drawRoundedRect(QRectF(nx, ny, nw, nh), 6, 6)

            # Label
            f = QFont("Cascadia Code", max(7, int(9*scale)))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QPen(col))
            p.drawText(QRectF(nx+4, ny, nw-8, nh*0.55),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       node.get("label","")[:14])

            # Agent + elapsed
            f2 = QFont("Cascadia Code", max(6, int(7*scale)))
            p.setFont(f2)
            col2 = QColor(col); col2.setAlpha(150)
            p.setPen(QPen(col2))
            agent_str = node.get("agent","")[:10]
            elapsed   = node.get("elapsed_ms",0)
            sub = agent_str + (f" {elapsed}ms" if elapsed else "")
            p.drawText(QRectF(nx+4, ny+nh*0.52, nw-8, nh*0.48),
                       Qt.AlignLeft | Qt.AlignVCenter, sub)

        p.end()

    def mousePressEvent(self, ev):
        pos = ev.position()
        mx, my = pos.x(), pos.y()
        if self._nodes:
            xs = [n.get("x",0) for n in self._nodes]
            ys = [n.get("y",0) for n in self._nodes]
            max_x = max(xs) + self.NODE_W + 40
            max_y = max(ys) + self.NODE_H + 40
            scale = min((self.width()-40)/max(1,max_x),
                        (self.height()-40)/max(1,max_y), 1.0)
            nw = self.NODE_W * scale
            nh = self.NODE_H * scale
            for node in self._nodes:
                nx = 20 + node.get("x",0) * scale
                ny = 20 + node.get("y",0) * scale
                if nx <= mx <= nx+nw and ny <= my <= ny+nh:
                    self.node_clicked.emit(node["id"])
                    break


# --------------------------------------------------------------------------
# GraphCanvasView — vue principale
# --------------------------------------------------------------------------

class GraphCanvasView(QWidget):
    """
    Vue GraphCanvas_Interactive.
    Input instruction -> Intent -> DAG -> Execution temps reel.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _OrchestratorWorker | None = None
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setFixedHeight(40)
        hdr.setStyleSheet("background:#0d0d0d; border-bottom:1px solid #1a1a1a;")
        hdr_lo = QHBoxLayout(hdr)
        hdr_lo.setContentsMargins(12, 0, 12, 0)
        title = QLabel("⬡  Autonomous Orchestrator v17 — Intent to Action Graph")
        title.setStyleSheet("font-size:12px; font-weight:600; color:#c2c0b6;")
        hdr_lo.addWidget(title)
        hdr_lo.addStretch()
        self._status_badge = QLabel("IDLE")
        self._status_badge.setStyleSheet(
            "color:#444; font-size:10px; font-weight:600; padding:2px 8px;"
            " border:1px solid #222; border-radius:4px;"
            " font-family:'Cascadia Code','Consolas';"
        )
        hdr_lo.addWidget(self._status_badge)
        lo.addWidget(hdr)

        # Input strip
        inp = QWidget()
        inp.setFixedHeight(38)
        inp.setStyleSheet("background:#0a0a0a; border-bottom:1px solid #111;")
        inp_lo = QHBoxLayout(inp)
        inp_lo.setContentsMargins(10, 4, 10, 4)
        inp_lo.setSpacing(6)
        prompt_lbl = QLabel(">")
        prompt_lbl.setStyleSheet("color:#4caf50; font-size:13px; font-weight:700; font-family:'Cascadia Code';")
        inp_lo.addWidget(prompt_lbl)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Instruction en langage naturel… ex: Cree un script Python de tri rapide")
        self._input.setStyleSheet(
            "background:transparent; color:#c2c0b6; border:none;"
            " padding:4px; font-size:12px; font-family:'Cascadia Code','Consolas';"
        )
        self._input.returnPressed.connect(self._run)
        inp_lo.addWidget(self._input, 1)
        self._run_btn = QPushButton("Execute")
        self._run_btn.setFixedWidth(80)
        self._run_btn.setStyleSheet(
            "background:#0a1a0a; border:1px solid #4caf50; color:#4caf50;"
            " border-radius:4px; font-size:11px;"
        )
        self._run_btn.clicked.connect(self._run)
        inp_lo.addWidget(self._run_btn)
        lo.addWidget(inp)

        # Intent info strip
        self._intent_bar = QLabel("  Verbes: —  |  Entites: —  |  Schema: —  |  Confiance: —")
        self._intent_bar.setFixedHeight(22)
        self._intent_bar.setStyleSheet(
            "background:#050508; color:#333; font-size:10px;"
            " padding:0 12px; border-bottom:1px solid #111;"
            " font-family:'Cascadia Code','Consolas';"
        )
        lo.addWidget(self._intent_bar)

        # Canvas DAG
        self._canvas = _DAGCanvas()
        self._canvas.node_clicked.connect(self._on_node_click)
        lo.addWidget(self._canvas, 1)

        # Detail node panel
        self._detail = QLabel("Cliquez sur un noeud pour voir son output")
        self._detail.setFixedHeight(60)
        self._detail.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet(
            "background:#050508; color:#555; font-size:10px; padding:6px 12px;"
            " border-top:1px solid #111; font-family:'Cascadia Code','Consolas';"
        )
        lo.addWidget(self._detail)

    def _run(self):
        instruction = self._input.text().strip()
        if not instruction:
            return
        if self._worker and self._worker.isRunning():
            return
        self._canvas.set_graph([], [])
        self._set_badge("PARSING")
        self._detail.setText("Analyse de l'intention…")
        self._worker = _OrchestratorWorker(instruction, parent=self)
        self._worker.node_updated.connect(self._on_node_update)
        self._worker.graph_ready.connect(self._on_graph_ready)
        self._worker.run_done.connect(self._on_done)
        self._worker.start()
        self._run_btn.setEnabled(False)

    def _on_graph_ready(self, graph: dict):
        nodes = graph.get("nodes", [])
        edges = graph.get("nodes_edges", [])
        # Reconstuire edges depuis depends_on
        edges = []
        for n in nodes:
            for dep in n.get("depends_on", []):
                edges.append({"from": dep, "to": n["id"], "label": ""})
        self._canvas.set_graph(nodes, edges)
        intent = graph.get("intent", {})
        if intent:
            self._intent_bar.setText(
                f"  Verbes: {intent.get('verbs',[])[:3]}  |"
                f"  Entites: {intent.get('entities',[])[:3]}  |"
                f"  Schema: {intent.get('schema_hint','')}  |"
                f"  Confiance: {intent.get('confidence',0):.0%}"
            )
            self._intent_bar.setStyleSheet(
                "background:#050508; color:#666; font-size:10px;"
                " padding:0 12px; border-bottom:1px solid #111;"
                " font-family:'Cascadia Code','Consolas';"
            )
        self._set_badge("RUNNING")

    def _on_node_update(self, node: dict):
        self._canvas.update_node(node)
        status = node.get("status","")
        if status == "running":
            self._set_badge("RUNNING")

    def _on_done(self, result: dict):
        ok    = result.get("ok", 0)
        total = result.get("total", 0)
        ms    = result.get("elapsed_ms", 0)
        err   = result.get("error", "")
        if err:
            self._set_badge("FAILED")
            self._detail.setText(f"Erreur: {err[:200]}")
        else:
            self._set_badge("DONE")
            ctx = result.get("context", "")[:300]
            self._detail.setText(f"{ok}/{total} noeuds OK | {ms}ms\n{ctx}")
        self._run_btn.setEnabled(True)

    def _on_node_click(self, node_id: str):
        for n in self._canvas._nodes:
            if n["id"] == node_id:
                out = n.get("output","")[:400]
                ms  = n.get("elapsed_ms",0)
                self._detail.setText(
                    f"[{node_id}] {n.get('label','')} | {n.get('agent','')} | {ms}ms\n{out}"
                )
                break

    def _set_badge(self, status: str):
        colors = {
            "IDLE":    ("#444",    "#111"),
            "PARSING": ("#ff9800", "#1a1200"),
            "RUNNING": ("#00bcd4", "#001a1a"),
            "DONE":    ("#4caf50", "#001a00"),
            "FAILED":  ("#f44336", "#1a0000"),
        }
        col, bg = colors.get(status, ("#444","#111"))
        self._status_badge.setText(status)
        self._status_badge.setStyleSheet(
            f"color:{col}; background:{bg}; font-size:10px; font-weight:600;"
            f" padding:2px 8px; border:1px solid {col}44; border-radius:4px;"
            " font-family:'Cascadia Code','Consolas';"
        )