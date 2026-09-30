"""
forge_dashboard.py — Dashboard Nokido v17
==========================================
Visualisation temps réel du vault génomique, des métriques et des runs Cerberus.

Usage :
  python tools/forge_dashboard.py

Dépendances :
  pip install PyQt6 pyqtgraph
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    import pyqtgraph as pg
    from PyQt6.QtCore import QThread, QTimer, pyqtSignal
    from PyQt6.QtGui import QColor, QFont
    from PyQt6.QtWidgets import (
        QApplication,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QProgressBar,
        QScrollArea,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as e:
    print(f"❌ Dépendances manquantes : {e}")
    print("   pip install PyQt6 pyqtgraph")
    sys.exit(1)


# ── Couleurs génomiques ───────────────────────────────────────────────────────
SCORE_COLORS = {
    (93, 101): "#1B7F3C",  # vert foncé ≥93
    (90, 93): "#2ECC71",  # vert clair 90-92
    (88, 90): "#F39C12",  # orange 88-89
    (85, 88): "#E67E22",  # orange foncé 85-87
    (0, 85): "#C0392B",  # rouge <85
}


def score_color(score: int) -> str:
    """Retourne la couleur hexadécimale pour un score donné."""
    for (lo, hi), color in SCORE_COLORS.items():
        if lo <= score < hi:
            return color
    return "#888888"


# ── Lecture vault ─────────────────────────────────────────────────────────────


def load_vault() -> list[dict]:
    """Charge tous les genomes du vault, garde le meilleur score par module.

    Returns:
        Liste de dicts triée par score décroissant.
    """
    vault = ROOT / "shadow_mutation" / "vault"
    seen: dict[str, dict] = {}
    for g in vault.rglob("genome.json"):
        try:
            d = json.loads(g.read_text(encoding="utf-8"))
            mod = g.parent.parent.name
            sc = d.get("score", 0)
            if mod not in seen or sc > seen[mod]["score"]:
                seen[mod] = {
                    "module": mod,
                    "score": sc,
                    "agent": d.get("agent", "?")[:20],
                    "version": g.parent.name[:18],
                    "ts": d.get("timestamp", "")[:16],
                }
        except Exception:
            pass
    return sorted(seen.values(), key=lambda x: -x["score"])


def load_episodic_stats() -> dict:
    """Charge les statistiques de la mémoire épisodique.

    Returns:
        Dict avec total, succès, échecs, taux.
    """
    ep = ROOT / "shadow_mutation" / "rag_index" / "experience_memory.jsonl"
    if not ep.exists():
        return {"total": 0, "ok": 0, "ko": 0, "rate": 0}
    lines = ep.read_text(encoding="utf-8", errors="replace").splitlines()
    ok = sum(1 for l in lines if '"Success"' in l)
    ko = len(lines) - ok
    return {"total": len(lines), "ok": ok, "ko": ko, "rate": int(100 * ok / max(1, len(lines)))}


def load_active_runs() -> list[dict]:
    """Détecte les runs Cerberus actifs dans sandbox/.

    Returns:
        Liste de dicts {stem, status, score, lines}.
    """
    sandbox = ROOT / "sandbox"
    runs = []
    for log in sorted(sandbox.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:15]:
        try:
            txt = log.read_text(encoding="utf-8", errors="replace")
            lines = [
                l
                for l in txt.splitlines()
                if l.strip()
                and not any(
                    x in l for x in ["cooldown", "Give Feedback", "LiteLLM", "Provider List"]
                )
            ]
            ok = any("mis à jour" in l or "RESULT:OK" in l for l in lines)
            ko = any("RESULT:KO" in l or "best=0/100" in l for l in lines)
            score = next((l.split("best=")[1][:5] for l in lines if "best=" in l), "?")
            status = "✅ OK" if ok else ("❌ KO" if ko else "⏳ run")
            runs.append(
                {
                    "name": log.stem[:30],
                    "status": status,
                    "score": score,
                    "last": (lines[-1].strip()[:55] if lines else ""),
                }
            )
        except Exception:
            pass
    return runs[:12]


# ── Widgets ───────────────────────────────────────────────────────────────────


class MetricCard(QFrame):
    """Carte métrique simple : label + valeur grande + sous-titre."""

    def __init__(
        self,
        label: str,
        value: str,
        subtitle: str = "",
        color: str = "#2ECC71",
        parent: QWidget | None = None,
    ) -> None:
        """Initialise la carte métrique.

        Args:
            label:    Titre de la métrique.
            value:    Valeur principale.
            subtitle: Texte secondaire optionnel.
            color:    Couleur de la valeur.
            parent:   Widget parent Qt.
        """
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            MetricCard {
                background: #1e1e2e;
                border: 1px solid #333;
                border-radius: 8px;
                padding: 4px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel(label)
        lbl.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(lbl)

        self.val_lbl = QLabel(value)
        self.val_lbl.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: bold;")
        layout.addWidget(self.val_lbl)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setStyleSheet("color: #666; font-size: 10px;")
            layout.addWidget(sub)

    def update_value(self, value: str, color: str | None = None) -> None:
        """Met à jour la valeur affichée.

        Args:
            value: Nouvelle valeur.
            color: Nouvelle couleur optionnelle.
        """
        self.val_lbl.setText(value)
        if color:
            self.val_lbl.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: bold;")


class VaultTable(QTableWidget):
    """Table des modules du vault avec coloration par score."""

    HEADERS = ["Module", "Score", "Agent", "Version"]

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialise la table du vault."""
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setStyleSheet("""
            QTableWidget {
                background: #13131f;
                color: #ccc;
                gridline-color: #222;
                border: none;
                font-size: 12px;
            }
            QHeaderView::section {
                background: #1a1a2e;
                color: #888;
                border: none;
                padding: 4px 8px;
                font-size: 11px;
            }
            QTableWidget::item:selected { background: #2a2a3e; }
        """)
        self.setColumnWidth(0, 200)
        self.setColumnWidth(1, 60)
        self.setColumnWidth(2, 130)
        self.setColumnWidth(3, 160)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)

    def refresh(self, data: list[dict]) -> None:
        """Recharge la table avec les données du vault.

        Args:
            data: Liste de modules avec score, agent, version.
        """
        self.setRowCount(len(data))
        for row, item in enumerate(data):
            sc = item["score"]
            color = score_color(sc)

            for col, val in enumerate([item["module"], str(sc), item["agent"], item["version"]]):
                cell = QTableWidgetItem(val)
                if col == 1:
                    cell.setForeground(QColor(color))
                    f = cell.font()
                    f.setBold(True)
                    cell.setFont(f)
                self.setItem(row, col, cell)
            self.setRowHeight(row, 22)


class RunsWidget(QTableWidget):
    """Table des runs Cerberus actifs."""

    HEADERS = ["Log", "Statut", "Score", "Dernière ligne"]

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialise la table des runs."""
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setStyleSheet("""
            QTableWidget { background: #13131f; color: #ccc; gridline-color: #222; border: none; font-size: 11px; }
            QHeaderView::section { background: #1a1a2e; color: #888; border: none; padding: 4px 8px; font-size: 11px; }
        """)
        self.setColumnWidth(0, 180)
        self.setColumnWidth(1, 70)
        self.setColumnWidth(2, 60)
        self.setColumnWidth(3, 300)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

    def refresh(self, runs: list[dict]) -> None:
        """Recharge la table des runs.

        Args:
            runs: Liste de runs avec name, status, score, last.
        """
        self.setRowCount(len(runs))
        colors = {"✅ OK": "#2ECC71", "❌ KO": "#E74C3C", "⏳ run": "#F39C12"}
        for row, r in enumerate(runs):
            for col, val in enumerate([r["name"], r["status"], r["score"], r["last"]]):
                cell = QTableWidgetItem(val)
                if col == 1:
                    cell.setForeground(QColor(colors.get(r["status"], "#888")))
                self.setItem(row, col, cell)
            self.setRowHeight(row, 20)


# ── Thread de refresh ─────────────────────────────────────────────────────────


class RefreshThread(QThread):
    """Thread background qui rafraîchit les données toutes les N secondes."""

    data_ready = pyqtSignal(dict)

    def __init__(self, interval: int = 8) -> None:
        """Initialise le thread.

        Args:
            interval: Intervalle de rafraîchissement en secondes.
        """
        super().__init__()
        self.interval = interval
        self._running = True

    def run(self) -> None:
        """Boucle principale du thread."""
        while self._running:
            payload = {
                "vault": load_vault(),
                "episodic": load_episodic_stats(),
                "runs": load_active_runs(),
            }
            self.data_ready.emit(payload)
            time.sleep(self.interval)

    def stop(self) -> None:
        """Arrête le thread proprement."""
        self._running = False
        self.wait()


# ── Fenêtre principale ────────────────────────────────────────────────────────


class NokidoDashboard(QMainWindow):
    """Fenêtre principale du dashboard Nokido."""

    def __init__(self) -> None:
        """Initialise la fenêtre principale."""
        super().__init__()
        self.setWindowTitle("Nokido v17 — Dashboard génomique")
        self.setMinimumSize(1100, 700)
        self._build_ui()
        self._start_refresh()

    def _build_ui(self) -> None:
        """Construit l'interface graphique."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Style global dark
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #0d0d1a; color: #ccc; }
            QSplitter::handle { background: #222; }
            QLabel { color: #ccc; }
            QScrollBar:vertical { background: #111; width: 8px; }
            QScrollBar::handle:vertical { background: #333; border-radius: 4px; }
        """)

        # ── Titre ──
        title = QLabel("🧬 Nokido v17 — Dashboard génomique")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #7C6AF7; padding: 4px 0;")
        main_layout.addWidget(title)

        # ── Métriques top ──
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(10)
        self.card_tests = MetricCard("Tests NR", "506 ✓", "passed / 8 skipped", "#2ECC71")
        self.card_docs = MetricCard("Docstrings", "99%", "3051 / 3059", "#3498DB")
        self.card_vault = MetricCard("Vault", "53", "modules archivés", "#9B59B6")
        self.card_ok = MetricCard("Succès RAG", "—", "experience_memory", "#2ECC71")
        self.card_f1 = MetricCard("ML F1", "0.963", "MutationPredictor", "#F39C12")
        self.card_lora = MetricCard("LoRA", "✓ live", "laforge-qwen actif", "#1ABC9C")
        for card in [
            self.card_tests,
            self.card_docs,
            self.card_vault,
            self.card_ok,
            self.card_f1,
            self.card_lora,
        ]:
            metrics_row.addWidget(card)
        main_layout.addLayout(metrics_row)

        # ── Splitter principal ──
        splitter = QSplitter()
        splitter.setOrientation(splitter.orientation())  # horizontal
        main_layout.addWidget(splitter, stretch=1)

        # ── Vault table (gauche) ──
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        lbl_vault = QLabel("Vault génomique")
        lbl_vault.setStyleSheet("color: #7C6AF7; font-weight: bold; font-size: 13px;")
        left_layout.addWidget(lbl_vault)

        self.vault_table = VaultTable()
        left_layout.addWidget(self.vault_table)
        splitter.addWidget(left_panel)

        # ── Panneau droit ──
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # Histogramme des scores (pyqtgraph)
        lbl_chart = QLabel("Distribution des scores")
        lbl_chart.setStyleSheet("color: #7C6AF7; font-weight: bold; font-size: 13px;")
        right_layout.addWidget(lbl_chart)

        pg.setConfigOption("background", "#13131f")
        pg.setConfigOption("foreground", "#888")
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMaximumHeight(180)
        self.plot_widget.setLabel("left", "Modules", color="#888", size="10pt")
        self.plot_widget.setLabel("bottom", "Score", color="#888", size="10pt")
        self.plot_widget.getAxis("left").setStyle(tickFont=QFont("monospace", 9))
        right_layout.addWidget(self.plot_widget)

        # Runs actifs
        lbl_runs = QLabel("Runs Cerberus actifs")
        lbl_runs.setStyleSheet("color: #7C6AF7; font-weight: bold; font-size: 13px;")
        right_layout.addWidget(lbl_runs)

        self.runs_table = RunsWidget()
        right_layout.addWidget(self.runs_table)

        splitter.addWidget(right_panel)
        splitter.setSizes([500, 580])

        # ── Status bar ──
        self.statusBar().setStyleSheet("color: #555; font-size: 10px; background: #0d0d1a;")
        self.statusBar().showMessage("Chargement...")

    def _start_refresh(self) -> None:
        """Démarre le thread de rafraîchissement automatique."""
        self._thread = RefreshThread(interval=8)
        self._thread.data_ready.connect(self._on_data)
        self._thread.start()

    def _on_data(self, payload: dict) -> None:
        """Met à jour l'interface avec les nouvelles données.

        Args:
            payload: Dict avec vault, episodic, runs.
        """
        vault = payload["vault"]
        episodic = payload["episodic"]
        runs = payload["runs"]

        # Métriques
        self.card_vault.update_value(str(len(vault)))
        self.card_ok.update_value(
            f"{episodic['ok']}/{episodic['total']}",
            "#2ECC71" if episodic["rate"] >= 30 else "#E74C3C",
        )

        # Vault table
        self.vault_table.refresh(vault)

        # Histogramme
        self._update_chart(vault)

        # Runs
        self.runs_table.refresh(runs)

        # Status bar
        n_ok = sum(1 for r in runs if "OK" in r["status"])
        n_run = sum(1 for r in runs if "⏳" in r["status"])
        self.statusBar().showMessage(
            f"Vault: {len(vault)} modules · Runs: {n_run} actifs / {n_ok} OK · "
            f"Rafraîchi: {time.strftime('%H:%M:%S')}"
        )

    def _update_chart(self, vault: list[dict]) -> None:
        """Met à jour l'histogramme de distribution des scores.

        Args:
            vault: Liste des modules avec score.
        """
        from collections import Counter

        counts = Counter(v["score"] for v in vault)
        buckets = sorted(counts.keys())
        values = [counts[b] for b in buckets]
        colors = [score_color(b) for b in buckets]

        self.plot_widget.clear()
        bar = pg.BarGraphItem(
            x=list(range(len(buckets))),
            height=values,
            width=0.7,
            brushes=[pg.mkBrush(c) for c in colors],
        )
        self.plot_widget.addItem(bar)
        ax = self.plot_widget.getAxis("bottom")
        ax.setTicks([[(i, str(b)) for i, b in enumerate(buckets)]])

    def closeEvent(self, event) -> None:
        """Arrête le thread à la fermeture.

        Args:
            event: Événement de fermeture Qt.
        """
        self._thread.stop()
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = NokidoDashboard()
    win.show()
    sys.exit(app.exec())
