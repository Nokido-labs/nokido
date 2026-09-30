"""
forge_desktop/views/timemachine_view.py — Time-Machine des commits
"""
from __future__ import annotations
import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QLabel, QListWidget, QListWidgetItem, QTextEdit,
    QPushButton, QGroupBox, QScrollArea, QFrame,
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QColor, QFont

ROOT = Path(__file__).resolve().parent.parent.parent
DARK = "background:#0a0a0a; color:#c2c0b6; font-family:'Cascadia Code','Consolas'; font-size:11px; border:1px solid #333; border-radius:4px;"


class GitLogWorker(QThread):
    """Charge le git log en arrière-plan — non-bloquant."""
    log_ready = Signal(list)   # [{hash, date, author, subject}]
    diff_ready = Signal(str)   # diff texte

    def __init__(self, commit_hash: str = "", parent=None):
        super().__init__(parent)
        self._hash = commit_hash

    def run(self):
        DETACHED = 0x00000008
        if not self._hash:
            # Charger le log
            try:
                r = subprocess.run(
                    ["git", "log", "--oneline", "--format=%h|%ci|%an|%s", "-40"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, cwd=str(ROOT)
                )
                commits = []
                for line in r.stdout.strip().splitlines():
                    parts = line.split("|", 3)
                    if len(parts) == 4:
                        commits.append({
                            "hash":    parts[0].strip(),
                            "date":    parts[1].strip()[:16],
                            "author":  parts[2].strip(),
                            "subject": parts[3].strip(),
                        })
                self.log_ready.emit(commits)
            except Exception:
                self.log_ready.emit([])
        else:
            # Charger le diff d'un commit
            try:
                r = subprocess.run(
                    ["git", "show", self._hash, "--stat", "--patch", "--no-color"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, cwd=str(ROOT)
                )
                self.diff_ready.emit(r.stdout[:8000])
            except Exception:
                self.diff_ready.emit("[Erreur git show]")


class TimeMachineView(QWidget):
    """
    Vue Time-Machine.
    Gauche : timeline commits. Droite : diff visuel avant/après.
    """
    restore_requested = Signal(str)   # commit hash

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("⏱  Time-Machine — Historique commits")
        title.setStyleSheet("font-size:14px; font-weight:600; color:#c2c0b6;")
        layout.addWidget(title)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(3)

        # ── Gauche : liste commits ────────────────────────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left.setFixedWidth(360)

        btn_refresh = QPushButton("↺  Rafraîchir")
        btn_refresh.clicked.connect(self._load_log)
        left_layout.addWidget(btn_refresh)

        self._commit_list = QListWidget()
        self._commit_list.setStyleSheet(
            "background:#0a0a0a; color:#c2c0b6; border:1px solid #333;"
            " border-radius:4px; font-family:'Cascadia Code'; font-size:11px;"
        )
        self._commit_list.itemClicked.connect(self._on_commit_clicked)
        left_layout.addWidget(self._commit_list)

        splitter.addWidget(left)

        # ── Droite : diff + actions ───────────────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)

        # Header commit sélectionné
        self._commit_header = QLabel("Sélectionne un commit")
        self._commit_header.setStyleSheet(
            "font-size:12px; color:#888; padding:4px;"
        )
        right_layout.addWidget(self._commit_header)

        # Diff viewer
        self._diff_view = QTextEdit()
        self._diff_view.setReadOnly(True)
        self._diff_view.setStyleSheet(DARK)
        self._diff_view.setFont(QFont("Cascadia Code", 10))
        right_layout.addWidget(self._diff_view)

        # Actions
        actions_row = QHBoxLayout()
        self._btn_apply = QPushButton("✅  Appliquer (Commit Guard)")
        self._btn_apply.setStyleSheet(
            "background:#1a3a1a; border:1px solid #4caf50; color:#4caf50;"
            " border-radius:4px; padding:4px 12px;"
        )
        self._btn_apply.setEnabled(False)
        self._btn_apply.clicked.connect(self._on_apply)

        self._btn_danger = QPushButton("⚠  ANNULER")
        self._btn_danger.setStyleSheet(
            "background:#3a1a1a; border:1px solid #f44336; color:#f44336;"
            " border-radius:4px; padding:4px 12px; font-weight:600;"
        )
        self._btn_danger.setEnabled(False)
        self._btn_danger.clicked.connect(self._on_cancel)

        actions_row.addWidget(self._btn_apply)
        actions_row.addWidget(self._btn_danger)
        actions_row.addStretch()
        right_layout.addLayout(actions_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        self._selected_hash = ""
        # Lazy load : charger le log au premier affichage, pas dans __init__
        # (évite un subprocess git bloquant au démarrage de la GUI)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, self._load_log)

    def _load_log(self):
        self._commit_list.clear()
        self._commit_list.addItem(QListWidgetItem("Chargement..."))
        self._log_worker = GitLogWorker()
        self._log_worker.log_ready.connect(self._on_log_ready)
        self._log_worker.start()

    def _on_log_ready(self, commits: list):
        self._commit_list.clear()
        for c in commits:
            item = QListWidgetItem(
                c["hash"] + "  " + c["date"] + "\n" + c["subject"][:50]
            )
            item.setData(Qt.UserRole, c["hash"])
            item.setForeground(QColor("#c2c0b6"))
            self._commit_list.addItem(item)

    def _on_commit_clicked(self, item: QListWidgetItem):
        h = item.data(Qt.UserRole)
        if not h:
            return
        self._selected_hash = h
        self._commit_header.setText("Commit : " + h)
        self._diff_view.setPlainText("Chargement diff...")
        self._btn_apply.setEnabled(False)
        self._btn_danger.setEnabled(False)

        self._diff_worker = GitLogWorker(commit_hash=h)
        self._diff_worker.diff_ready.connect(self._on_diff_ready)
        self._diff_worker.start()

    def _on_diff_ready(self, diff: str):
        self._diff_view.setPlainText(diff)
        self._colorize_diff()
        self._btn_apply.setEnabled(True)
        self._btn_danger.setEnabled(True)

    def _colorize_diff(self):
        """Colorie le diff : + en vert, - en rouge."""
        doc = self._diff_view.document()
        cursor = self._diff_view.textCursor()
        cursor.movePosition(cursor.Start)
        from PySide6.QtGui import QTextCharFormat
        fmt_add = QTextCharFormat()
        fmt_add.setForeground(QColor("#4caf50"))
        fmt_del = QTextCharFormat()
        fmt_del.setForeground(QColor("#f44336"))
        fmt_hdr = QTextCharFormat()
        fmt_hdr.setForeground(QColor("#888"))
        for block in range(doc.blockCount()):
            b = doc.findBlockByNumber(block)
            text = b.text()
            if text.startswith("+") and not text.startswith("+++"):
                c = self._diff_view.textCursor()
                c.setPosition(b.position())
                c.movePosition(c.EndOfBlock, c.KeepAnchor)
                c.setCharFormat(fmt_add)
            elif text.startswith("-") and not text.startswith("---"):
                c = self._diff_view.textCursor()
                c.setPosition(b.position())
                c.movePosition(c.EndOfBlock, c.KeepAnchor)
                c.setCharFormat(fmt_del)
            elif text.startswith("@@"):
                c = self._diff_view.textCursor()
                c.setPosition(b.position())
                c.movePosition(c.EndOfBlock, c.KeepAnchor)
                c.setCharFormat(fmt_hdr)

    def _on_apply(self):
        self._btn_apply.setText("✅  Appliqué")
        self._btn_apply.setEnabled(False)
        self.restore_requested.emit(self._selected_hash)

    def _on_cancel(self):
        self._btn_danger.setText("⚠  Annulé")
        self._btn_danger.setEnabled(False)
        self._diff_view.setPlainText("[Annulé]")
