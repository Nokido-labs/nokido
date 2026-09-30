"""
forge_desktop/views/forge_os_canvas.py
USER_FRIENDLY_FORGE_OS -- Action_Over_Chat
Canvas interactif : Omnibar -> Nodes -> Execution
Glassmorphism_Deep_Dark | Cellular_OneMCP_Atomic
double_click=Inspect | right_click=Swap_LLM | drag=Chain
"""
from __future__ import annotations
import math, sys, time, json
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
APP  = ROOT / "app"

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QMenu, QSizePolicy, QFrame,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QRectF, QPointF
from forge_desktop.core.canvas_nodes import NODE_CATALOG, get_runner
from forge_desktop.widgets.flux_console import FluxConsole
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont,
    QPainterPath, QLinearGradient,
)

GLASS_BG  = QColor(12, 12, 18, 255)
ACCENT_Q  = QColor(83, 74, 183)
STATUS_COL = {
    "idle":    QColor(60,  60,  80),
    "pending": QColor(80,  80, 100),
    "running": QColor(0,  188, 212),
    "done":    QColor(76, 175,  80),
    "failed":  QColor(244, 67,  54),
    "blocked": QColor(156, 39, 176),
}
ALL_PROVIDERS = [
    "laforge","llamacpp","gemini","groq_direct","groq_70b",
    "deepseek_direct","mistral_direct","xai_grok","nokido_mcp",
]


class ForgeNode:
    W = 150
    H = 56

    def __init__(self, nid, label, agent, x=100.0, y=100.0):
        self.id = nid; self.label = label; self.agent = agent
        self.x = x; self.y = y
        self.status = "idle"; self.output = ""; self.elapsed = 0
        self.selected = False; self._pulse = 0.0
        self.vx = 0.0; self.vy = 0.0   # spring physics
        self._hover = False             # ghost preview

    def rect(self):
        return (self.x, self.y, self.W, self.H)

    def center(self):
        return (self.x + self.W/2, self.y + self.H/2)

    def hit(self, mx, my):
        return self.x <= mx <= self.x+self.W and self.y <= my <= self.y+self.H

    def to_dict(self):
        return {
            "id": self.id, "label": self.label, "agent": self.agent,
            "x": self.x, "y": self.y, "status": self.status,
            "output": self.output[:200], "elapsed_ms": self.elapsed,
        }


class ForgeEdge:
    def __init__(self, from_id, to_id, label=""):
        self.from_id = from_id; self.to_id = to_id; self.label = label


class _OrcWorker(QThread):
    node_update = Signal(str, str, str, int)
    done        = Signal(dict)

    def __init__(self, instruction, parent=None):
        super().__init__(parent)
        self._instruction = instruction

    def run(self):
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        try:
            from forge_autonomous_orchestrator import get_orchestrator
            def _cb(d):
                self.node_update.emit(
                    d.get("id",""), d.get("status",""),
                    d.get("output","")[:300], d.get("elapsed_ms",0)
                )
            orc    = get_orchestrator(on_update=_cb)
            result = orc.run_sync(self._instruction)
            self.done.emit(result)
        except Exception as e:
            self.done.emit({"ok":0,"total":0,"error":str(e)[:200]})


class FlowCanvas(QWidget):
    node_inspected   = Signal(dict)
    provider_swapped = Signal(str, str)
    edge_chained     = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._nodes = []
        self._edges = []
        self._drag_node = None
        self._drag_edge_from = None
        self._drag_edge_to   = None
        self._drag_offset    = QPointF(0, 0)
        self._t = 0.0
        self._grid = 20                    # Magnetic_Grid_Snapping
        self._rubber_start  = None         # Rubber_Band_Selection
        self._rubber_end    = None
        self._rubbing       = False
        self._hover_node    = None         # ghost preview
        self._flow_offset   = 0.0          # Flowing_Neon_Line anim
        self._suggestion_node = None       # smart suggestion
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        self._t += 0.04
        self._flow_offset = (self._flow_offset + 2) % 20
        for n in self._nodes:
            if n.status == "running":
                n._pulse = 0.5 + 0.5 * math.sin(self._t * 4)
            # Elastic spring : amortir vers la grille
            if self._drag_node is not n and (abs(n.vx)+abs(n.vy)) > 0.1:
                n.x += n.vx; n.y += n.vy
                n.vx *= 0.82; n.vy *= 0.82
        self.update()

    def set_nodes(self, node_dicts):
        self._nodes = []
        self._edges = []
        for i, d in enumerate(node_dicts):
            n = ForgeNode(
                nid=d["id"], label=d.get("label", d["id"]),
                agent=d.get("agent","laforge"),
                x=float(d.get("x", 80 + i*180)),
                y=float(d.get("y", 160)),
            )
            n.status  = d.get("status", "idle")
            n.output  = d.get("output", "")
            n.elapsed = d.get("elapsed_ms", 0)
            self._nodes.append(n)
        for d in node_dicts:
            for dep in d.get("depends_on", []):
                self._edges.append(ForgeEdge(dep, d["id"]))

    def update_node(self, nid, status, output, ms):
        for n in self._nodes:
            if n.id == nid:
                n.status = status; n.output = output; n.elapsed = ms
                break

    def clear(self):
        self._nodes.clear(); self._edges.clear()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, GLASS_BG)
        # Grille
        p.setPen(QPen(QColor(40, 40, 60, 70), 1))
        for gx in range(0, w, 32):
            for gy in range(0, h, 32):
                p.drawPoint(gx, gy)
        if not self._nodes:
            p.setPen(QPen(QColor("#2a2a3a")))
            p.setFont(QFont("Cascadia Code", 13))
            msg = "Tape une instruction dans l'omnibar\nou Ctrl+K pour la palette"
            p.drawText(QRectF(0,0,w,h), Qt.AlignCenter, msg)
            p.end(); return
        self._draw_edges(p)
        if self._drag_edge_from and self._drag_edge_to:
            cx, cy = self._drag_edge_from.center()
            x2, y2 = self._drag_edge_to.x(), self._drag_edge_to.y()
            p.setPen(QPen(ACCENT_Q, 1.5, Qt.DashLine))
            path = QPainterPath(QPointF(cx, cy))
            mx = (cx+x2)/2
            path.cubicTo(mx, cy, mx, y2, x2, y2)
            p.drawPath(path)
        for node in self._nodes:
            self._draw_node(p, node)
        # Rubber_Band_Selection
        if self._rubbing and self._rubber_start and self._rubber_end:
            rx1=min(self._rubber_start.x(),self._rubber_end.x())
            ry1=min(self._rubber_start.y(),self._rubber_end.y())
            rx2=max(self._rubber_start.x(),self._rubber_end.x())
            ry2=max(self._rubber_start.y(),self._rubber_end.y())
            rb_col=QColor(ACCENT_Q); rb_col.setAlpha(40)
            p.setBrush(QBrush(rb_col))
            rb_border=QColor(ACCENT_Q); rb_border.setAlpha(160)
            p.setPen(QPen(rb_border,1,Qt.DashLine))
            p.drawRect(QRectF(rx1,ry1,rx2-rx1,ry2-ry1))
        p.end()

    def _draw_edges(self, p):
        nm = {n.id: n for n in self._nodes}
        for e in self._edges:
            fn = nm.get(e.from_id); tn = nm.get(e.to_id)
            if not fn or not tn: continue
            x1,y1 = fn.x+fn.W, fn.y+fn.H/2
            x2,y2 = tn.x,      tn.y+tn.H/2
            ec = QColor(STATUS_COL.get(fn.status, STATUS_COL["idle"]))
            ec.setAlpha(100 if fn.status=="idle" else 180)
            dash = fn.status in ("idle","pending")
            if fn.status == "running":
                # Flowing_Neon_Line
                flow_pen = QPen(ec, 2.5, Qt.CustomDashLine)
                flow_pen.setDashPattern([6,4])
                flow_pen.setDashOffset(-self._flow_offset)
                p.setPen(flow_pen)
            else:
                p.setPen(QPen(ec, 1.5, Qt.DashLine if dash else Qt.SolidLine))
            path = QPainterPath(QPointF(x1, y1))
            mx = (x1+x2)/2
            path.cubicTo(mx,y1,mx,y2,x2,y2)
            p.drawPath(path)
            p.setBrush(QBrush(ec)); p.setPen(Qt.NoPen)
            arr = QPainterPath(QPointF(x2,y2))
            arr.lineTo(x2-9,y2-4); arr.lineTo(x2-9,y2+4); arr.closeSubpath()
            p.drawPath(arr)

    def _draw_node(self, p, n):
        col = STATUS_COL.get(n.status, STATUS_COL["idle"])
        nx, ny, nw, nh = n.x, n.y, n.W, n.H
        if n.status == "running" and n._pulse > 0:
            halo = QColor(col); halo.setAlphaF(n._pulse * 0.35)
            p.setPen(Qt.NoPen); p.setBrush(QBrush(halo))
            p.drawRoundedRect(QRectF(nx-10,ny-10,nw+20,nh+20),14,14)
        if n.selected:
            sg = QColor(ACCENT_Q); sg.setAlpha(80)
            p.setPen(QPen(sg,2)); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(nx-4,ny-4,nw+8,nh+8),10,10)
        grad = QLinearGradient(nx,ny,nx,ny+nh)
        c1 = QColor(col); c1.setAlpha(35)
        c2 = QColor(col); c2.setAlpha(12)
        grad.setColorAt(0,c1); grad.setColorAt(1,c2)
        p.setBrush(QBrush(grad))
        bc = QColor(col); bc.setAlpha(160 if n.selected else 90)
        p.setPen(QPen(bc,1))
        p.drawRoundedRect(QRectF(nx,ny,nw,nh),8,8)
        p.setPen(Qt.NoPen); p.setBrush(QBrush(col))
        p.drawRoundedRect(QRectF(nx,ny+8,3,nh-16),2,2)
        p.setPen(QPen(col))
        p.setFont(QFont("Cascadia Code",10,QFont.Bold))
        p.drawText(QRectF(nx+10,ny+2,nw-20,nh*0.52),
                   Qt.AlignLeft|Qt.AlignVCenter, n.label[:16])
        p.setFont(QFont("Cascadia Code",8))
        ac = QColor(col); ac.setAlpha(160); p.setPen(QPen(ac))
        sub = n.agent[:12] + (f" {n.elapsed}ms" if n.elapsed else "")
        p.drawText(QRectF(nx+10,ny+nh*0.52,nw-20,nh*0.48),
                   Qt.AlignLeft|Qt.AlignVCenter, sub)
        p.setPen(Qt.NoPen); p.setBrush(QBrush(col))
        p.drawRoundedRect(QRectF(nx+nw-6,ny+nh/2-4,8,8),2,2)
        # Ghost_Mode : Show_Data_Preview_On_Hover
        if n._hover and n.output:
            p.setFont(QFont("Cascadia Code",7))
            gc = QColor(col); gc.setAlpha(100)
            p.setPen(QPen(gc))
            preview = n.output[:60].replace("\n"," ")
            p.drawText(QRectF(nx, ny+nh+4, nw+60, 22),
                       Qt.AlignLeft|Qt.AlignVCenter, preview)
            n._hover = False

    def _snap(self, v):
        return round(v / self._grid) * self._grid

    def mousePressEvent(self, ev):
        pos = ev.position(); mx, my = pos.x(), pos.y()
        ctrl = ev.modifiers() & Qt.ControlModifier
        if not ctrl:
            for n in self._nodes: n.selected = False
        hit = next((n for n in self._nodes if n.hit(mx,my)), None)
        if hit:
            hit.selected = True
            px,py = hit.x+hit.W-6, hit.y+hit.H/2-4
            if px<=mx<=px+8 and py<=my<=py+8:
                # Smart_Port_Magnetism : si port vide, suggerer un noeud
                if not any(e.from_id==hit.id for e in self._edges):
                    self._suggestion_node = hit
                self._drag_edge_from = hit; return
            self._drag_node   = hit
            self._drag_offset = QPointF(mx-hit.x, my-hit.y)
        else:
            # Rubber_Band_Selection
            self._rubber_start = QPointF(mx, my)
            self._rubber_end   = QPointF(mx, my)
            self._rubbing      = True

    def mouseMoveEvent(self, ev):
        pos = ev.position(); mx,my = pos.x(),pos.y()
        # Ghost preview hover
        self._hover_node = next((n for n in self._nodes if n.hit(mx,my)), None)
        if self._hover_node:
            self._hover_node._hover = True
        if self._drag_node:
            # Magnetic_Grid_Snapping
            tx = self._snap(mx - self._drag_offset.x())
            ty = self._snap(my - self._drag_offset.y())
            self._drag_node.vx = (tx - self._drag_node.x) * 0.4
            self._drag_node.vy = (ty - self._drag_node.y) * 0.4
            self._drag_node.x  = tx
            self._drag_node.y  = ty
        elif self._drag_edge_from:
            self._drag_edge_to = QPointF(mx,my)
        elif self._rubbing and self._rubber_start:
            self._rubber_end = QPointF(mx,my)
            # Selectionner les noeuds dans le rubber band
            rx1 = min(self._rubber_start.x(), mx)
            ry1 = min(self._rubber_start.y(), my)
            rx2 = max(self._rubber_start.x(), mx)
            ry2 = max(self._rubber_start.y(), my)
            for n in self._nodes:
                cx,cy = n.center()
                n.selected = rx1<=cx<=rx2 and ry1<=cy<=ry2

    def mouseReleaseEvent(self, ev):
        pos = ev.position(); mx,my = pos.x(),pos.y()
        if self._drag_edge_from and self._drag_edge_to:
            # Smart_Port_Magnetism : snap sur le noeud le plus proche
            closest = None; best_d = 40.0
            for n in self._nodes:
                if n.id == self._drag_edge_from.id: continue
                cx,cy = n.center()
                d = math.hypot(cx-mx, cy-my)
                if d < best_d: best_d=d; closest=n
            target = closest or next(
                (n for n in self._nodes if n.hit(mx,my)
                 and n.id!=self._drag_edge_from.id), None)
            if target:
                fid,tid = self._drag_edge_from.id, target.id
                if not any(e.from_id==fid and e.to_id==tid for e in self._edges):
                    self._edges.append(ForgeEdge(fid,tid,"chain"))
                    self.edge_chained.emit(fid,tid)
            elif self._suggestion_node:
                # Port vide relache dans le vide -> emit suggestion
                self.node_inspected.emit(
                    {"id": "__suggest__",
                     "from": self._suggestion_node.id,
                     "label": "suggestion"})
        self._rubbing = False
        self._rubber_start = None; self._rubber_end = None
        self._suggestion_node = None
        self._drag_node=None; self._drag_edge_from=None; self._drag_edge_to=None

    def keyPressEvent(self, ev):
        k = ev.key()
        sel = [n for n in self._nodes if n.selected]
        if k in (Qt.Key_Delete, Qt.Key_X) and sel:
            # Hotkey_Del_or_X_Button — supprimer
            del_ids = {n.id for n in sel}
            self._nodes = [n for n in self._nodes if n.id not in del_ids]
            self._edges = [e for e in self._edges
                           if e.from_id not in del_ids and e.to_id not in del_ids]
        elif k == Qt.Key_D and (ev.modifiers() & Qt.ControlModifier) and sel:
            # Ctrl+D — clone
            import time as _t
            for n in list(sel):
                clone = ForgeNode(
                    nid=n.id+"_c"+str(int(_t.time()*10)%1000),
                    label=n.label, agent=n.agent,
                    x=n.x+self._grid*3, y=n.y+self._grid*2
                )
                self._nodes.append(clone)
        elif k == Qt.Key_L and (ev.modifiers() & Qt.ControlModifier):
            # Ctrl+L — Hierarchical_Tree_Reset layout
            self._auto_layout()
        ev.accept()

    def _auto_layout(self):
        """Hierarchical_Tree_Reset — BFS depuis racines."""
        if not self._nodes: return
        children = {n.id: [] for n in self._nodes}
        parents  = {n.id: [] for n in self._nodes}
        for e in self._edges:
            if e.from_id in children: children[e.from_id].append(e.to_id)
            if e.to_id   in parents:  parents[e.to_id].append(e.from_id)
        roots = [n.id for n in self._nodes if not parents[n.id]]
        if not roots: roots = [self._nodes[0].id]
        levels = {}; queue = list(roots)
        for r in roots: levels[r] = 0
        while queue:
            cur = queue.pop(0)
            for ch in children.get(cur,[]):
                if ch not in levels:
                    levels[ch] = levels[cur]+1; queue.append(ch)
        lvl_map = {}
        for nid,lvl in levels.items(): lvl_map.setdefault(lvl,[]).append(nid)
        nm = {n.id:n for n in self._nodes}
        col_w = 200; row_h = 100; margin = 60
        for lvl, nids in lvl_map.items():
            for i, nid in enumerate(nids):
                n = nm.get(nid)
                if n:
                    tx = margin + lvl*col_w
                    ty = margin + i*row_h
                    n.vx = (tx-n.x)*0.3; n.vy = (ty-n.y)*0.3

    def mouseDoubleClickEvent(self, ev):
        pos = ev.position()
        hit = next((n for n in self._nodes if n.hit(pos.x(),pos.y())), None)
        if hit: self.node_inspected.emit(hit.to_dict())

    def contextMenuEvent(self, ev):
        pos = ev.pos()
        hit = next((n for n in self._nodes if n.hit(pos.x(),pos.y())), None)
        if not hit: return
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#0d0d14;color:#c2c0b6;border:1px solid #534AB7;"
            "border-radius:6px;padding:4px;"
            "font-family:'Cascadia Code';font-size:11px;}"
            "QMenu::item{padding:4px 16px;border-radius:3px;}"
            "QMenu::item:selected{background:#1a1a2a;}"
        )
        t = menu.addAction(f"Agent: {hit.agent}")
        t.setEnabled(False)
        menu.addSeparator()
        for prov in ALL_PROVIDERS:
            ico = "* " if prov==hit.agent else "  "
            act = menu.addAction(ico+prov)
            act.setData(prov)
        chosen = menu.exec(ev.globalPos())
        if chosen and chosen.data():
            hit.agent = chosen.data()
            self.provider_swapped.emit(hit.id, hit.agent)


class ForgeOSCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker      = None
        self._error_count = 0
        # Init sequence : KnowledgeHarvester -> FlowCanvas
        self._harvester = None
        try:
            import sys
            from pathlib import Path as _P
            _app = _P(__file__).resolve().parent.parent.parent / "app"
            if str(_app) not in sys.path: sys.path.insert(0, str(_app))
            from forge_knowledge_harvester import get_harvester
            self._harvester = get_harvester()
        except Exception:
            pass
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0,0,0,0)
        lo.setSpacing(0)

        # Omnibar
        omni = QWidget(); omni.setFixedHeight(52)
        omni.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #0e0e18,stop:1 #080810);"
            "border-bottom:1px solid #534AB755;"
        )
        ol = QHBoxLayout(omni); ol.setContentsMargins(16,0,16,0); ol.setSpacing(10)
        logo = QLabel("forgeOS")
        logo.setStyleSheet("color:#534AB7;font-size:13px;font-weight:700;"
                           "font-family:'Cascadia Code';padding-right:4px;")
        ol.addWidget(logo)
        self._omni = QLineEdit()
        self._omni.setPlaceholderText(
            "Que faire ? ex: Cree un test pytest, Analyse le hub, Compare asyncio vs threads…"
        )
        self._omni.setStyleSheet(
            "background:rgba(22,22,40,180);color:#e0ddd4;"
            "border:1px solid #534AB744;border-radius:8px;"
            "padding:8px 14px;font-size:13px;"
            "font-family:'Cascadia Code','Consolas';"
        )
        self._omni.returnPressed.connect(self._on_submit)
        ol.addWidget(self._omni, 1)
        self._intent_lbl = QLabel("")
        self._intent_lbl.setStyleSheet(
            "color:#534AB7;font-size:9px;padding:2px 8px;"
            "border:1px solid #534AB733;border-radius:4px;"
            "font-family:'Cascadia Code';"
        )
        ol.addWidget(self._intent_lbl)
        self._go_btn = QPushButton("Execute")
        self._go_btn.setFixedSize(80,32)
        self._go_btn.setStyleSheet(
            "background-color: rgba(83,74,183,180);"
            "border-radius: 8px; color: #CDD6F4;"
            "border: 1px solid #45475A; font-size: 12px;"
            "font-family: 'Cascadia Code';"
        )
        self._go_btn.clicked.connect(self._on_submit)
        ol.addWidget(self._go_btn)
        self._status = QLabel("IDLE")
        self._status.setFixedWidth(70); self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color:#444;font-size:10px;font-weight:700;"
                                   "font-family:'Cascadia Code';")
        ol.addWidget(self._status)
        lo.addWidget(omni)

        # Node palette toolbar (GIT/RAG/LLM/CI)
        palette_bar = QWidget()
        palette_bar.setFixedHeight(38)
        palette_bar.setStyleSheet(
            "background:#080810; border-bottom:1px solid #534AB722;"
        )
        pb_lo = QHBoxLayout(palette_bar)
        pb_lo.setContentsMargins(12, 0, 12, 0)
        pb_lo.setSpacing(8)
        node_colors = {"GIT":"#f44336","RAG":"#4caf50","LLM":"#2196f3","CI":"#ff9800"}
        for node_type, cfg in NODE_CATALOG.items():
            col = node_colors.get(node_type, "#888")
            btn = QPushButton(f"+ {node_type}")
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: rgba(30,30,46,180);"
                f" border-radius: 8px; color: {col};"
                f" border: 1px solid {col}66;"
                f" font-size: 10px; padding: 0 10px;"
                f" font-family: 'Cascadia Code','Consolas'; }}"
                f"QPushButton:hover {{ background-color: rgba(83,74,183,80);"
                f" border-color: {col}; }}"
            )
            btn.clicked.connect(lambda checked, nt=node_type: self._add_node(nt))
            pb_lo.addWidget(btn)
        pb_lo.addStretch()
        # Ring0 sentinel badge
        self._ring0_badge = QLabel("Ring0 OK")
        self._ring0_badge.setStyleSheet(
            "color:#1a3a1a;font-size:9px;font-family:'Cascadia Code';"
            "border:1px solid #1a3a1a;border-radius:3px;padding:1px 6px;"
        )
        pb_lo.addWidget(self._ring0_badge)
        lo.addWidget(palette_bar)

        # Canvas
        self._canvas = FlowCanvas()
        self._canvas.node_inspected.connect(self._on_inspect)
        self._canvas.provider_swapped.connect(self._on_swap)
        self._canvas.edge_chained.connect(self._on_chain)
        lo.addWidget(self._canvas, 1)

        # Inspect panel
        self._inspect_frame = QFrame()
        self._inspect_frame.setFixedHeight(64)
        self._inspect_frame.setStyleSheet(
            "QFrame{background:rgba(12,12,22,220);"
            "border-top:1px solid #534AB744;}"
        )
        il = QVBoxLayout(self._inspect_frame)
        il.setContentsMargins(14,6,14,6)
        self._inspect_lbl = QLabel(
            "Double-clic = inspecter | Clic-droit = changer LLM | Drag port = chaîner"
        )
        self._inspect_lbl.setWordWrap(True)
        self._inspect_lbl.setStyleSheet(
            "color:#333;font-size:10px;font-family:'Cascadia Code';"
        )
        il.addWidget(self._inspect_lbl)
        lo.addWidget(self._inspect_frame)

        # FluxConsole — FLUX_VISIBILITY_V2_EXPERT
        self._flux = FluxConsole()
        self._flux.setFixedHeight(180)
        self._flux.retry_requested.connect(self._on_submit)
        self._flux.run_requested.connect(
            lambda path: self._flux.log('INFO', f'Run: {path}')
        )
        lo.addWidget(self._flux)

    def _on_submit(self):
        instr = self._omni.text().strip()
        if not instr or (self._worker and self._worker.isRunning()):
            return
        try:
            if str(APP) not in sys.path:
                sys.path.insert(0, str(APP))
            from forge_intent_parser import parse_intent
            intent = parse_intent(instr)
            self._intent_lbl.setText(
                f"{intent.schema_hint} | {intent.action} | {intent.confidence:.0%}"
            )
        except Exception:
            pass
        self._canvas.clear()
        self._set_status("BUILDING")
        self._error_count = 0
        self._worker = _OrcWorker(instr, parent=self)
        self._worker.node_update.connect(self._on_node_update)
        self._worker.done.connect(self._on_done)
        self._worker.start()
        self._go_btn.setEnabled(False)
        # Ring0 refresh toutes les 10s
        self._ring0_timer = QTimer(self)
        self._ring0_timer.timeout.connect(self._refresh_ring0)
        self._ring0_timer.start(10000)
        QTimer.singleShot(500, self._refresh_ring0)

    def _on_node_update(self, nid, status, output, ms):
        self._canvas.update_node(nid, status, output, ms)
        if output:
            self._flux.log_agent(nid, output, ms)
        if status == "failed":
            self._error_count += 1
            self._flux.log('ERROR', f'[FAIL] {nid}: {output[:80]}')
            
            
        self._set_status(status.upper())

    def _on_done(self, result):
        ok    = result.get("ok",0)
        total = result.get("total",0)
        ms    = result.get("elapsed_ms",0)
        err   = result.get("error","")
        all_r = result.get("results",[])
        if all_r:
            self._canvas.set_nodes(all_r)
        # Harvest knowledge si succes
        if not err and self._harvester:
            try:
                self._harvester.harvest_on_success(
                    self._omni.text().strip(),
                    result.get("context",""),
                    ""
                )
            except Exception:
                pass
        if err:
            self._set_status("FAILED")
            self._flux.log('ERROR', f'Erreur: {err[:100]}')
            
        else:
            self._set_status("DONE")
            ctx = result.get("context","")[:100]
            self._inspect_lbl.setText(f"{ok}/{total} noeuds OK -- {ms}ms -- {ctx}")
            self._inspect_lbl.setStyleSheet(
                "color:#4caf5088;font-size:10px;font-family:'Cascadia Code';"
            )
            agents = result.get('agents', [])
            if agents:
                self._flux.suggest_agents(self._omni.text(), agents)
        self._go_btn.setEnabled(True)

    def _on_inspect(self, node):
        status = node.get("status","")
        out    = node.get("output","")[:280]
        ms     = node.get("elapsed_ms",0)
        col = {"done":"#4caf50","failed":"#f44336","running":"#00bcd4"}.get(status,"#888")
        self._inspect_lbl.setText(
            f"[{node.get('label','')}] {node.get('agent','')} | {status} | {ms}ms\n{out}"
        )
        self._inspect_lbl.setStyleSheet(
            f"color:{col}88;font-size:10px;font-family:'Cascadia Code';"
        )

    def _on_swap(self, nid, new_agent):
        self._flux.log('INFO', f'Swap: {nid} -> {new_agent}')
        

    def _on_chain(self, from_id, to_id):
        self._flux.log('INFO', f'Chain: {from_id} -> {to_id}')
        

    def _add_node(self, node_type: str):
        """Ajoute un noeud OneMCP au canvas."""
        import time as _t
        nid = f"{node_type}_{int(_t.time()*100)%10000}"
        cfg = NODE_CATALOG.get(node_type, {})
        actions = list(cfg.get("actions", {}).keys())
        first_action = actions[0] if actions else "run"
        col = {"GIT":"#f44336","RAG":"#4caf50","LLM":"#2196f3","CI":"#ff9800"}.get(node_type,"#888")
        # Créer le noeud avec position aléatoire
        import random
        x = random.randint(60, max(60, self._canvas.width()-200))
        y = random.randint(60, max(60, self._canvas.height()-100))
        from forge_desktop.views.forge_os_canvas import ForgeNode
        n = ForgeNode(nid=nid, label=node_type, agent=first_action, x=x, y=y)
        n.output = f"Actions: {', '.join(actions[:3])}"
        self._canvas._nodes.append(n)
        # Brancher le runner OneMCP
        runner = get_runner(on_update=lambda d: self._canvas.update_node(
            d["id"], d["status"], d.get("output",""), d.get("elapsed_ms",0)
        ))
        # Exécuter la première action
        instr = self._omni.text().strip() or f"Tâche {node_type}"
        runner.run_async(nid, node_type, first_action, instr)

    def _refresh_ring0(self):
        """Met à jour le badge Ring0 Sentinel."""
        try:
            import json as _j
            from pathlib import Path as _P
            state = _j.loads((_P(__file__).resolve().parent.parent.parent
                              / "config" / "authority_state.json"
                              ).read_text(encoding="utf-8"))
            md = state.get("master_dev", {})
            import time as _t
            now = _t.time()
            last = md.get("last_beat") or md.get("acquired_at") or 0
            expired = (now - last) > md.get("ttl", 1800)
            if not expired and md.get("agent_id") == "CLAUDE":
                self._ring0_badge.setText("Ring0 CLAUDE")
                self._ring0_badge.setStyleSheet(
                    "color:#4caf50;font-size:9px;font-family:'Cascadia Code';"
                    "border:1px solid #4caf5044;border-radius:3px;padding:1px 6px;"
                )
            else:
                self._ring0_badge.setText("Ring0 expired")
                self._ring0_badge.setStyleSheet(
                    "color:#f44336;font-size:9px;font-family:'Cascadia Code';"
                    "border:1px solid #f4433644;border-radius:3px;padding:1px 6px;"
                )
        except Exception:
            pass

    def _set_status(self, s):
        c = {"IDLE":"#333","BUILDING":"#ff9800","RUNNING":"#00bcd4",
             "DONE":"#4caf50","FAILED":"#f44336"}.get(s,"#333")
        self._status.setText(s)
        self._status.setStyleSheet(
            f"color:{c};font-size:10px;font-weight:700;font-family:'Cascadia Code';"
        )

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