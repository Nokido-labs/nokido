"""
forge_desktop/views/cerberus_view.py — Dashboard Cerberus intégré
==================================================================
Visualisation vault génomique + runs actifs + métriques évolutives.
Portage PySide6 de tools/forge_dashboard.py pour intégration GUI native.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore  import QThread, QTimer, Signal
from PySide6.QtGui   import QColor, QFont
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QProgressBar, QScrollArea, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

ROOT = Path(__file__).resolve().parent.parent.parent

# ── Couleurs scores ────────────────────────────────────────────────────────────
SCORE_COLORS = {
    (93, 101): "#1B7F3C",
    (90, 93):  "#2ECC71",
    (88, 90):  "#F39C12",
    (85, 88):  "#E67E22",
    (0,  85):  "#C0392B",
}

DARK = "background:#0e1117; color:#c2c0b6; font-family:'Segoe UI'; font-size:12px;"
CARD = "background:#141420; border:1px solid #2a2a3a; border-radius:8px;"

def _score_color(score: int) -> str:
    for (lo, hi), c in SCORE_COLORS.items():
        if lo <= score < hi:
            return c
    return "#888"


# ── Loaders ────────────────────────────────────────────────────────────────────

def _load_vault() -> list[dict]:
    vault = ROOT / "shadow_mutation" / "vault"
    seen: dict[str, dict] = {}
    for g in vault.rglob("genome.json"):
        try:
            d   = json.loads(g.read_text(encoding="utf-8"))
            mod = g.parent.parent.name
            sc  = d.get("score", 0)
            if mod not in seen or sc > seen[mod]["score"]:
                seen[mod] = {
                    "module":  mod,
                    "score":   sc,
                    "agent":   d.get("agent", "?")[:20],
                    "version": g.parent.name[:18],
                    "ts":      d.get("timestamp", "")[:16],
                }
        except Exception:
            pass
    return sorted(seen.values(), key=lambda x: -x["score"])


def _load_stats() -> dict:
    ep = ROOT / "shadow_mutation" / "rag_index" / "experience_memory.jsonl"
    if not ep.exists():
        return {"total": 0, "ok": 0, "ko": 0, "rate": 0}
    lines = ep.read_text(encoding="utf-8", errors="replace").splitlines()
    ok    = sum(1 for l in lines if '"Success"' in l)
    return {"total": len(lines), "ok": ok, "ko": len(lines) - ok,
            "rate": int(100 * ok / max(1, len(lines)))}


def _load_runs() -> list[dict]:
    sandbox = ROOT / "sandbox"
    runs    = []
    for log in sorted(sandbox.glob("*.log"),
                      key=lambda p: p.stat().st_mtime, reverse=True)[:12]:
        try:
            txt   = log.read_text(encoding="utf-8", errors="replace")
            lines = [l for l in txt.splitlines() if l.strip()
                     and not any(x in l for x in ["cooldown","Feedback","LiteLLM"])]
            ok    = any("mis à jour" in l or "RESULT:OK" in l for l in lines)
            ko    = any("RESULT:KO" in l or "best=0/100" in l for l in lines)
            score = next((l.split("best=")[1][:5] for l in lines if "best=" in l), "?")
            status = "✅ OK" if ok else ("❌ KO" if ko else "⏳ run")
            runs.append({"name": log.stem[:30], "status": status,
                         "score": score, "last": (lines[-1][:55] if lines else "")})
        except Exception:
            pass
    return runs


# ── Widgets ────────────────────────────────────────────────────────────────────

class _MetricCard(QFrame):
    def __init__(self, label: str, value: str = "—",
                 color: str = "#2ECC71", parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"QFrame {{ {CARD} padding:8px; }}")
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 8, 12, 8)
        lbl = QLabel(label)
        lbl.setStyleSheet("color:#666; font-size:10px;")
        lo.addWidget(lbl)
        self._val = QLabel(value)
        self._val.setStyleSheet(f"color:{color}; font-size:20px; font-weight:600;")
        lo.addWidget(self._val)

    def set(self, value: str, color: str | None = None) -> None:
        self._val.setText(value)
        if color:
            self._val.setStyleSheet(f"color:{color}; font-size:20px; font-weight:600;")


class _VaultTable(QTableWidget):
    HDRS = ["Module", "Score", "Agent", "Version"]

    def __init__(self, parent=None) -> None:
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(self.HDRS)
        self.setStyleSheet("""
            QTableWidget { background:#0e1117; color:#c2c0b6;
                gridline-color:#1a1a2a; border:none; font-size:12px; }
            QHeaderView::section { background:#141420; color:#666; border:none;
                padding:4px 8px; font-size:10px; }
            QTableWidget::item:selected { background:#1e1e30; }
        """)
        self.setColumnWidth(0, 220)
        self.setColumnWidth(1, 55)
        self.setColumnWidth(2, 140)
        self.setColumnWidth(3, 170)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)

    def refresh(self, data: list[dict]) -> None:
        self.setRowCount(len(data))
        for row, item in enumerate(data):
            sc    = item["score"]
            color = _score_color(sc)
            for col, val in enumerate([item["module"], str(sc),
                                        item["agent"], item["version"]]):
                cell = QTableWidgetItem(val)
                if col == 1:
                    cell.setForeground(QColor(color))
                    f = cell.font(); f.setBold(True); cell.setFont(f)
                self.setItem(row, col, cell)
            self.setRowHeight(row, 22)


class _RunsTable(QTableWidget):
    HDRS = ["Log", "Statut", "Score", "Dernière ligne"]

    def __init__(self, parent=None) -> None:
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(self.HDRS)
        self.setStyleSheet("""
            QTableWidget { background:#0e1117; color:#c2c0b6;
                gridline-color:#1a1a2a; border:none; font-size:11px; }
            QHeaderView::section { background:#141420; color:#666; border:none;
                padding:4px 8px; font-size:10px; }
        """)
        self.setColumnWidth(0, 180); self.setColumnWidth(1, 65)
        self.setColumnWidth(2, 55);  self.setColumnWidth(3, 340)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

    def refresh(self, runs: list[dict]) -> None:
        self.setRowCount(len(runs))
        palette = {"✅ OK": "#2ECC71", "❌ KO": "#E74C3C", "⏳ run": "#F39C12"}
        for row, r in enumerate(runs):
            for col, val in enumerate([r["name"],r["status"],r["score"],r["last"]]):
                cell = QTableWidgetItem(val)
                if col == 1:
                    cell.setForeground(QColor(palette.get(r["status"],"#888")))
                self.setItem(row, col, cell)
            self.setRowHeight(row, 20)


# ── Worker refresh ─────────────────────────────────────────────────────────────

class _RefreshWorker(QThread):
    data_ready = Signal(dict)

    def __init__(self, interval: int = 8) -> None:
        super().__init__()
        self._interval = interval
        self._running  = True

    def run(self) -> None:
        while self._running:
            try:
                payload = {
                    "vault": _load_vault(),
                    "stats": _load_stats(),
                    "runs":  _load_runs(),
                }
                self.data_ready.emit(payload)
            except Exception:
                pass
            for _ in range(self._interval * 10):
                if not self._running:
                    break
                self.msleep(100)

    def stop(self) -> None:
        self._running = False
        self.quit()

    def closeEvent(self, event) -> None:
        self.stop()
        self.wait(1000)
        super().closeEvent(event)


# ── Vue principale ─────────────────────────────────────────────────────────────

class CerberusView(QWidget):
    """Dashboard Cerberus — vault + runs + métriques évolutives."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(DARK)
        self._worker: _RefreshWorker | None = None
        self._build()
        QTimer.singleShot(300, self._start_worker)

    # ── Build UI ───────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root_lo = QVBoxLayout(self)
        root_lo.setContentsMargins(8, 8, 8, 8)
        root_lo.setSpacing(8)

        # Titre
        title = QLabel("🧬  Cerberus — Vault génomique & Runs évolutifs")
        title.setStyleSheet("font-size:14px; font-weight:600; color:#c2c0b6;")
        root_lo.addWidget(title)

        # ── Metric cards ──────────────────────────────────────────────────────
        cards_row = QHBoxLayout()
        self._c_modules  = _MetricCard("Modules vault",   "—",    "#2ECC71")
        self._c_ge90     = _MetricCard("Score ≥ 90",      "—",    "#1B7F3C")
        self._c_rate     = _MetricCard("Taux succès",      "—",    "#3498DB")
        self._c_ep_total = _MetricCard("Épisodes mémoire", "—",    "#9B59B6")
        for c in [self._c_modules, self._c_ge90, self._c_rate, self._c_ep_total]:
            cards_row.addWidget(c)
        root_lo.addLayout(cards_row)

        # ── Splitter vault / runs ─────────────────────────────────────────────
        splitter = QSplitter()
        splitter.setHandleWidth(3)
        splitter.setStyleSheet("QSplitter::handle { background:#1a1a2a; }")

        # Gauche : vault table
        left = QWidget()
        left_lo = QVBoxLayout(left)
        left_lo.setContentsMargins(0,0,0,0)
        lbl_vault = QLabel("📊  Vault — scores par module")
        lbl_vault.setStyleSheet("font-size:11px; color:#666; padding:2px 0;")
        left_lo.addWidget(lbl_vault)
        self._vault_table = _VaultTable()
        left_lo.addWidget(self._vault_table)
        splitter.addWidget(left)

        # Droite : runs table
        right = QWidget()
        right_lo = QVBoxLayout(right)
        right_lo.setContentsMargins(0,0,0,0)
        lbl_runs = QLabel("⚡  Runs Cerberus actifs")
        lbl_runs.setStyleSheet("font-size:11px; color:#666; padding:2px 0;")
        right_lo.addWidget(lbl_runs)
        self._runs_table = _RunsTable()
        right_lo.addWidget(self._runs_table)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root_lo.addWidget(splitter)

        # Status bar
        self._status = QLabel("En attente de données...")
        self._status.setStyleSheet("color:#444; font-size:10px;")
        root_lo.addWidget(self._status)

    # ── Worker ─────────────────────────────────────────────────────────────────

    def _start_worker(self) -> None:
        self._worker = _RefreshWorker(interval=8)
        self._worker.data_ready.connect(self._on_data)
        self._worker.start()

    def _on_data(self, payload: dict) -> None:
        vault = payload.get("vault", [])
        stats = payload.get("stats", {})
        runs  = payload.get("runs",  [])

        # Cards
        ge90  = sum(1 for m in vault if m["score"] >= 90)
        pct   = int(100 * ge90 / max(1, len(vault)))
        self._c_modules.set(str(len(vault)),
                            _score_color(90 if len(vault) > 0 else 0))
        self._c_ge90.set(f"{ge90}/{len(vault)}",
                         "#2ECC71" if pct >= 90 else "#F39C12")
        self._c_rate.set(f"{stats.get('rate', 0)}%",
                         "#2ECC71" if stats.get("rate", 0) >= 70 else "#E74C3C")
        self._c_ep_total.set(str(stats.get("total", 0)), "#9B59B6")

        # Tables
        self._vault_table.refresh(vault)
        self._runs_table.refresh(runs)

        ts = __import__("datetime").datetime.now().strftime("%H:%M:%S")
        self._status.setText(
            f"Dernière mise à jour : {ts}  |  "
            f"{len(vault)} modules  |  {len(runs)} runs  |  "
            f"Épisodes OK:{stats.get('ok',0)} KO:{stats.get('ko',0)}"
        )

    def closeEvent(self, event) -> None:
        if self._worker:
            self._worker.stop()
            self._worker.wait(1500)
        super().closeEvent(event)
