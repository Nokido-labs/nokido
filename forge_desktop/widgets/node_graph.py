"""
forge_desktop/widgets/node_graph.py
=====================================
Graphe nodal des agents — QGraphicsScene.
Affiche les bulles d'agents reliées par des arêtes animées.
Éclairs lumineux pour les requêtes actives.
Hot-swap via drag&drop d'un modèle sur un nœud.
"""
from __future__ import annotations
import math
from typing import Optional

try:
    from PySide6.QtWidgets import (
        QGraphicsScene, QGraphicsView, QGraphicsItem,
        QGraphicsEllipseItem, QGraphicsLineItem,
        QGraphicsTextItem, QGraphicsDropShadowEffect,
        QWidget, QVBoxLayout,
    )
    from PySide6.QtCore import (
        Qt, QTimer, QPointF, QRectF, QPropertyAnimation,
        QEasingCurve, Signal, QObject, Property,
    )
    from PySide6.QtGui import (
        QPainter, QPen, QBrush, QColor, QRadialGradient,
        QFont, QFontMetrics, QLinearGradient, QPainterPath,
    )
    HAS_QT = True
except ImportError:
    HAS_QT = False


# ── Couleurs par kind de participant ─────────────────────────────────────────
KIND_COLORS = {
    "orchestrator": "#0f6e56",
    "local_llm":    "#3b6d11",
    "remote_llm":   "#185fa5",
    "agent":        "#993c1d",
    "rag":          "#534ab7",
    "idle":         "#2c2c2a",
}

STATE_COLORS = {
    "IDLE":        "#444441",
    "THINKING":    "#ff9800",
    "STREAMING":   "#2196f3",
    "SYNCING_RAG": "#9c27b0",
}


if HAS_QT:

    class AgentNode(QGraphicsItem):
        """
        Bulle d'agent dans le graphe.
        Affiche : icône, label, état, barre de progression.
        Supporte le drag & drop pour hot-swap de modèle.
        """
        def __init__(self, node_id: str, label: str, kind: str,
                     x: float, y: float, radius: float = 52):
            super().__init__()
            self.node_id  = node_id
            self.label    = label
            self.kind     = kind
            self.radius   = radius
            self.state    = "IDLE"
            self.progress = 0
            self.active   = False
            self._pulse   = 0.0   # 0..1 animation

            self.setPos(x, y)
            self.setFlag(QGraphicsItem.ItemIsMovable, True)
            self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
            self.setAcceptDrops(True)
            self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
            self.setZValue(1)

        def boundingRect(self) -> QRectF:
            r = self.radius + 8
            return QRectF(-r, -r, r * 2, r * 2)

        def update_state(self, state: str, progress: int = 0):
            self.state    = state
            self.progress = progress
            self.active   = state != "IDLE"
            self.update()

        def paint(self, painter: QPainter, option, widget=None):
            r = self.radius
            # Glow si actif
            if self.active:
                glow_r = r + 6 + int(self._pulse * 8)
                glow   = QRadialGradient(0, 0, glow_r)
                col    = QColor(STATE_COLORS.get(self.state, "#ff9800"))
                col.setAlpha(80)
                glow.setColorAt(0, col)
                glow.setColorAt(1, QColor(0, 0, 0, 0))
                painter.setBrush(QBrush(glow))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(-glow_r, -glow_r, glow_r*2, glow_r*2)

            # Cercle principal
            base_col = QColor(KIND_COLORS.get(self.kind, "#444"))
            if self.active:
                base_col = base_col.lighter(130)
            painter.setBrush(QBrush(base_col))
            border_col = QColor(STATE_COLORS.get(self.state, "#888"))
            border_w   = 2.5 if self.active else 1.0
            painter.setPen(QPen(border_col, border_w))
            painter.drawEllipse(-r, -r, r*2, r*2)

            # Label
            font = QFont("Segoe UI", 9, QFont.Medium)
            painter.setFont(font)
            painter.setPen(QColor("#ffffff"))
            fm    = QFontMetrics(font)
            short = self.label[:12] + ("…" if len(self.label) > 12 else "")
            tw    = fm.horizontalAdvance(short)
            painter.drawText(-tw//2, 5, short)

            # État sous le label
            font2 = QFont("Segoe UI", 7)
            painter.setFont(font2)
            painter.setPen(QColor(STATE_COLORS.get(self.state, "#888")))
            fm2   = QFontMetrics(font2)
            stw   = fm2.horizontalAdvance(self.state)
            painter.drawText(-stw//2, 18, self.state)

            # Barre de progression (arc)
            if self.active and self.progress > 0:
                painter.setPen(QPen(QColor("#4caf50"), 3))
                painter.setBrush(Qt.NoBrush)
                span = int(self.progress * 360 / 100 * 16)
                painter.drawArc(-r+4, -r+4, (r-4)*2, (r-4)*2, 90*16, -span)

        def dragEnterEvent(self, event):
            if event.mimeData().hasText():
                event.acceptProposedAction()

        def dropEvent(self, event):
            model = event.mimeData().text()
            self.scene().hot_swap_requested.emit(self.node_id, model)
            event.acceptProposedAction()


    class EdgeItem(QGraphicsItem):
        """Arête animée entre deux nœuds avec éclair lumineux."""

        def __init__(self, src: AgentNode, dst: AgentNode,
                     parent=None):
            super().__init__(parent)
            self.src       = src
            self.dst       = dst
            self._active   = False
            self._spark_t  = 0.0   # 0..1 position de l'éclair
            self.setZValue(0)

        def boundingRect(self) -> QRectF:
            sp = self.src.pos()
            dp = self.dst.pos()
            return QRectF(
                min(sp.x(), dp.x()) - 20,
                min(sp.y(), dp.y()) - 20,
                abs(sp.x() - dp.x()) + 40,
                abs(sp.y() - dp.y()) + 40,
            )

        def set_active(self, active: bool):
            self._active = active
            self.update()

        def advance_spark(self, dt: float = 0.05):
            if self._active:
                self._spark_t = (self._spark_t + dt) % 1.0
                self.update()

        def paint(self, painter: QPainter, option, widget=None):
            sp = self.src.pos()
            dp = self.dst.pos()
            r  = self.src.radius

            # Direction
            dx = dp.x() - sp.x()
            dy = dp.y() - sp.y()
            dist = math.sqrt(dx*dx + dy*dy) or 1
            ux, uy = dx/dist, dy/dist

            # Points de départ/arrivée sur les bords des cercles
            x1, y1 = sp.x() + ux * r, sp.y() + uy * r
            x2, y2 = dp.x() - ux * r, dp.y() - uy * r

            # Arête de base
            col = QColor("#555753") if not self._active else QColor("#888780")
            painter.setPen(QPen(col, 1.5 if not self._active else 2.5))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

            # Éclair lumineux sur l'arête active
            if self._active:
                t  = self._spark_t
                sx = x1 + (x2 - x1) * t
                sy = y1 + (y2 - y1) * t
                glow = QRadialGradient(sx, sy, 12)
                glow.setColorAt(0, QColor(255, 200, 50, 220))
                glow.setColorAt(1, QColor(255, 200, 50, 0))
                painter.setBrush(QBrush(glow))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(sx, sy), 10, 10)


    class NodeGraphScene(QGraphicsScene):
        """Scène du graphe nodal — gère les nœuds, arêtes et animations."""
        hot_swap_requested = Signal(str, str)  # node_id, model_name
        node_clicked       = Signal(str)       # node_id

        def __init__(self, parent=None):
            super().__init__(parent)
            self._nodes: dict[str, AgentNode] = {}
            self._edges: list[EdgeItem]       = []
            self._timer = QTimer()
            self._timer.timeout.connect(self._animate)
            self._timer.start(50)   # 20 fps
            self._pulse_t = 0.0

        def _animate(self):
            self._pulse_t = (self._pulse_t + 0.08) % (2 * math.pi)
            pulse = (math.sin(self._pulse_t) + 1) / 2
            for node in self._nodes.values():
                node._pulse = pulse
                if node.active:
                    node.update()
            for edge in self._edges:
                if edge._active:
                    edge.advance_spark(0.04)

        def add_node(self, node_id: str, label: str, kind: str,
                     x: float, y: float) -> AgentNode:
            node = AgentNode(node_id, label, kind, x, y)
            self._nodes[node_id] = node
            self.addItem(node)
            return node

        def add_edge(self, src_id: str, dst_id: str) -> Optional[EdgeItem]:
            src = self._nodes.get(src_id)
            dst = self._nodes.get(dst_id)
            if not src or not dst:
                return None
            edge = EdgeItem(src, dst)
            self._edges.append(edge)
            self.addItem(edge)
            return edge

        def update_node_state(self, node_id: str, state: str, progress: int = 0):
            node = self._nodes.get(node_id)
            if node:
                node.update_state(state, progress)
            # Activer les arêtes connectées
            for edge in self._edges:
                if edge.src.node_id == node_id or edge.dst.node_id == node_id:
                    edge.set_active(state != "IDLE")

        def load_team(self, team_config: dict):
            """Reconstruit le graphe depuis la config SwarmTeam."""
            self.clear()
            self._nodes.clear()
            self._edges.clear()

            participants = [p for p in team_config.get("participants", [])
                            if p.get("active")]
            n = len(participants)
            if n == 0:
                return

            # Lead Orchestrator au centre
            cx, cy = 0, 0
            self.add_node("Lead_Orchestrator", "Lead\nOrchestrator",
                          "orchestrator", cx, cy)

            # Participants en cercle
            radius_layout = 200
            for i, p in enumerate(participants):
                angle = 2 * math.pi * i / n - math.pi / 2
                x = cx + radius_layout * math.cos(angle)
                y = cy + radius_layout * math.sin(angle)
                node = self.add_node(p["id"], p["label"], p["kind"], x, y)
                self.add_edge("Lead_Orchestrator", p["id"])

            # RAG en bas
            self.add_node("RAG_Sync", "RAG Sync", "rag", cx, cy + 280)
            self.add_edge("Lead_Orchestrator", "RAG_Sync")

        def mousePressEvent(self, event):
            item = self.itemAt(event.scenePos(), __import__("PySide6.QtGui", fromlist=["QTransform"]).QTransform())
            if isinstance(item, AgentNode):
                self.node_clicked.emit(item.node_id)
            super().mousePressEvent(event)


    class NodeGraphWidget(QWidget):
        """Widget complet : NodeGraphScene dans un QGraphicsView."""
        hot_swap_requested = Signal(str, str)
        node_clicked       = Signal(str)

        def __init__(self, parent=None):
            super().__init__(parent)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)

            self.scene = NodeGraphScene()
            self.scene.hot_swap_requested.connect(self.hot_swap_requested)
            self.scene.node_clicked.connect(self.node_clicked)

            self.view = QGraphicsView(self.scene)
            self.view.setRenderHint(QPainter.Antialiasing)
            self.view.setRenderHint(QPainter.SmoothPixmapTransform)
            self.view.setBackgroundBrush(QBrush(QColor("#0e1117")))
            self.view.setDragMode(QGraphicsView.ScrollHandDrag)
            self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
            layout.addWidget(self.view)

        def wheelEvent(self, event):
            factor = 1.15 if event.angleDelta().y() > 0 else 0.87
            self.view.scale(factor, factor)

        def load_team(self, team_config: dict):
            self.scene.load_team(team_config)
            self.view.fitInView(self.scene.sceneRect().adjusted(-40,-40,40,40),
                                Qt.KeepAspectRatio)

        def update_node_state(self, node_id: str, state: str, progress: int = 0):
            self.scene.update_node_state(node_id, state, progress)
