"""
forge_desktop/views/rag_view.py — Onglet RAG avec entropie et ingestion manuelle
==================================================================================
Deux RAG :
  1. RAG Nokido (embeddings.db) — base de connaissance du projet
  2. RAG Externe (rag_external.db) — base dédiée à un projet tiers

Fonctionnalités :
  - Visualisation entropie Shannon par domaine (graphique barres)
  - Ingestion manuelle : drag&drop fichiers / URL / texte brut
  - Recherche sémantique temps réel (NPU DML)
  - Export knowledge vers nouveau projet (distillation)
"""
from __future__ import annotations
import json
import sqlite3
import math
import os
import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QTabWidget, QPushButton, QLineEdit,
    QTextEdit, QPlainTextEdit, QProgressBar,
    QGroupBox, QFileDialog, QComboBox,
    QListWidget, QListWidgetItem, QScrollArea,
    QFrame, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QMimeData
from PySide6.QtGui import QColor, QFont, QDragEnterEvent, QDropEvent

ROOT = Path(__file__).resolve().parent.parent.parent
APP  = ROOT / "app"

DARK = ("background:#0a0a0a; color:#c2c0b6;"
        " font-family:'Segoe UI'; font-size:12px;"
        " border:1px solid #333; border-radius:4px;")

DOMAIN_COLORS = {
    "code":       "#4caf50",
    "forge_core": "#2196f3",
    "systeme":    "#ff9800",
    "securite":   "#f44336",
    "reseau":     "#9c27b0",
    "general":    "#888",
    "rag":        "#00bcd4",
    "ia":         "#e91e63",
}


# ── Worker recherche RAG ──────────────────────────────────────────────────────

class RAGSearchWorker(QThread):
    results_ready = Signal(list)

    def __init__(self, query: str, db_path: str, top_k: int = 8, parent=None):
        super().__init__(parent)
        self._query   = query
        self._db_path = db_path
        self._top_k   = top_k

    def run(self):
        import sys
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        try:
            from forge_npu_embedder import NPUEmbedder
            emb  = NPUEmbedder()
            hits = emb.search_db(self._query, top_k=self._top_k,
                                  db_path=self._db_path)
            if not hits:
                self.results_ready.emit([])
                return
            conn = sqlite3.connect(self._db_path, timeout=5)
            results = []
            for h in hits:
                fp    = h["file_path"]
                score = h["score"]
                fname = Path(fp).name
                row   = conn.execute(
                    "SELECT text, source, domain FROM rag_chunks "
                    "WHERE source LIKE ? LIMIT 1",
                    ("%" + fname + "%",)
                ).fetchone()
                results.append({
                    "score":  round(score, 4),
                    "source": row[1] if row else fp,
                    "domain": row[2] if row else "?",
                    "text":   row[0][:400] if row else "(vide)",
                })
            conn.close()
            self.results_ready.emit(results)
        except Exception as e:
            self.results_ready.emit([{"error": str(e)[:100]}])


# ── Widget ingestion drag&drop ────────────────────────────────────────────────

class DropZone(QFrame):
    """Zone de dépôt fichier / URL."""
    files_dropped = Signal(list)   # liste de chemins
    url_dropped   = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(80)
        self.setStyleSheet(
            "QFrame { border:2px dashed #555; border-radius:8px;"
            " background:#111; color:#666; }"
            "QFrame:hover { border-color:#888; }"
        )
        layout = QVBoxLayout(self)
        lbl = QLabel("📂  Dépose des fichiers ici\n(PDF, TXT, MD, DOCX, PY, JSON, CSV)")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color:#666; font-size:12px; border:none;")
        layout.addWidget(lbl)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()
            self.setStyleSheet(
                "QFrame { border:2px dashed #4caf50; border-radius:8px;"
                " background:#0a1a0a; }")

    def dragLeaveEvent(self, e):
        self.setStyleSheet(
            "QFrame { border:2px dashed #555; border-radius:8px;"
            " background:#111; }")

    def dropEvent(self, e: QDropEvent):
        self.setStyleSheet(
            "QFrame { border:2px dashed #555; border-radius:8px;"
            " background:#111; }")
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls()
                     if u.isLocalFile()]
            urls  = [u.toString() for u in e.mimeData().urls()
                     if not u.isLocalFile()]
            if paths:
                self.files_dropped.emit(paths)
            for url in urls:
                self.url_dropped.emit(url)
        elif e.mimeData().hasText():
            text = e.mimeData().text().strip()
            if text.startswith("http"):
                self.url_dropped.emit(text)


# ── Widget entropie ───────────────────────────────────────────────────────────

class EntropyWidget(QWidget):
    """Visualisation entropie Shannon + barres de distribution."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self._entropy_lbl = QLabel("Entropie : --")
        self._entropy_lbl.setStyleSheet("font-size:13px; font-weight:600; color:#c2c0b6;")
        self._total_lbl   = QLabel("0 chunks")
        self._total_lbl.setStyleSheet("font-size:11px; color:#888;")
        header.addWidget(self._entropy_lbl)
        header.addStretch()
        header.addWidget(self._total_lbl)
        layout.addLayout(header)

        # Scroll area pour les barres
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(220)
        self._bars_widget = QWidget()
        self._bars_layout = QVBoxLayout(self._bars_widget)
        self._bars_layout.setSpacing(3)
        scroll.setWidget(self._bars_widget)
        layout.addWidget(scroll)

    def update_stats(self, domains: list, total: int):
        """
        domains : [(domain_name, count), ...]
        Calcule l'entropie de Shannon et affiche les barres.
        """
        # Vider les barres
        while self._bars_layout.count():
            item = self._bars_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not domains or total == 0:
            return

        # Entropie Shannon
        H = -sum((c/total) * math.log2(c/total) for _, c in domains if c > 0)
        H_max = math.log2(len(domains)) if len(domains) > 1 else 1
        H_norm = H / H_max if H_max > 0 else 0

        self._entropy_lbl.setText(
            f"Entropie : {H:.3f} bits  ({H_norm*100:.0f}% max)"
        )
        self._total_lbl.setText(f"{total:,} chunks / {len(domains)} domaines")

        max_c = max(c for _, c in domains) if domains else 1
        for domain, count in domains:
            row = QHBoxLayout()
            # Label domaine
            lbl = QLabel(domain)
            lbl.setFixedWidth(90)
            lbl.setStyleSheet("font-size:10px; color:#888;")
            # Barre
            bar = QProgressBar()
            bar.setRange(0, max_c)
            bar.setValue(count)
            bar.setFixedHeight(14)
            col = DOMAIN_COLORS.get(domain, "#555")
            bar.setStyleSheet(
                f"QProgressBar {{ border:none; background:#1a1a1a; border-radius:3px; }}"
                f"QProgressBar::chunk {{ background:{col}; border-radius:3px; }}"
            )
            # Count
            cnt = QLabel(str(count))
            cnt.setFixedWidth(50)
            cnt.setStyleSheet("font-size:10px; color:#666;")
            cnt.setAlignment(Qt.AlignRight)

            row.addWidget(lbl)
            row.addWidget(bar)
            row.addWidget(cnt)
            wrapper = QWidget()
            wrapper.setLayout(row)
            self._bars_layout.addWidget(wrapper)

        self._bars_layout.addStretch()


# ── Panel RAG (réutilisé pour Nokido + Externe) ─────────────────────────────

class RAGPanel(QWidget):
    """
    Panel générique pour un RAG.
    Contient : statistiques + entropie + recherche + ingestion.
    """
    ingest_requested = Signal(str, str)   # path_or_url, db_path

    def __init__(self, name: str, db_path: str, parent=None):
        super().__init__(parent)
        self._name    = name
        self._db_path = db_path
        self._search_worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8,8,8,8)
        layout.setSpacing(6)

        # Entropie
        entropy_group = QGroupBox("Distribution & Entropie")
        entropy_group.setStyleSheet(
            "QGroupBox { border:1px solid #333; border-radius:6px;"
            " margin-top:8px; color:#666; padding-top:4px; }"
        )
        eg_layout = QVBoxLayout(entropy_group)
        self._entropy = EntropyWidget()
        eg_layout.addWidget(self._entropy)
        refresh_btn = QPushButton("↺  Actualiser")
        refresh_btn.setStyleSheet(
            "background:#1a1a1a; border:1px solid #444; border-radius:4px;"
            " padding:3px 10px; color:#888; font-size:11px;"
        )
        refresh_btn.clicked.connect(self._load_stats)
        eg_layout.addWidget(refresh_btn)
        layout.addWidget(entropy_group)

        # Recherche
        search_group = QGroupBox("Recherche sémantique (NPU DML)")
        search_group.setStyleSheet(
            "QGroupBox { border:1px solid #333; border-radius:6px;"
            " margin-top:8px; color:#666; padding-top:4px; }"
        )
        sg_layout = QVBoxLayout(search_group)
        search_row = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Requête sémantique...")
        self._search_input.setStyleSheet(
            "background:#111; border:1px solid #555; border-radius:4px;"
            " padding:4px 8px; color:#c2c0b6;"
        )
        self._search_input.returnPressed.connect(self._do_search)
        self._topk = QComboBox()
        self._topk.addItems(["5","8","12","20"])
        self._topk.setStyleSheet("background:#111; color:#c2c0b6; border:1px solid #444;")
        search_btn = QPushButton("Chercher")
        search_btn.setStyleSheet(
            "background:#1a1a3a; border:1px solid #2196f3; color:#2196f3;"
            " border-radius:4px; padding:4px 12px;"
        )
        search_btn.clicked.connect(self._do_search)
        search_row.addWidget(self._search_input)
        search_row.addWidget(self._topk)
        search_row.addWidget(search_btn)
        sg_layout.addLayout(search_row)

        self._results = QPlainTextEdit()
        self._results.setReadOnly(True)
        self._results.setMaximumHeight(180)
        self._results.setStyleSheet(DARK)
        sg_layout.addWidget(self._results)
        layout.addWidget(search_group)

        # Ingestion
        ingest_group = QGroupBox("Ingestion manuelle (Ring 2 — TRUSTED)")
        ingest_group.setStyleSheet(
            "QGroupBox { border:1px solid #2a5a2a; border-radius:6px;"
            " margin-top:8px; color:#4caf50; padding-top:4px; }"
        )
        ig_layout = QVBoxLayout(ingest_group)

        self._drop_zone = DropZone()
        self._drop_zone.files_dropped.connect(self._on_files_dropped)
        self._drop_zone.url_dropped.connect(self._on_url_dropped)
        ig_layout.addWidget(self._drop_zone)

        # Bouton parcourir
        browse_row = QHBoxLayout()
        browse_btn = QPushButton("📂  Parcourir...")
        browse_btn.clicked.connect(self._browse_file)
        browse_btn.setStyleSheet(
            "background:#1a2a1a; border:1px solid #4caf50; color:#4caf50;"
            " border-radius:4px; padding:4px 12px;"
        )
        # URL
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://... ou chemin fichier")
        self._url_input.setStyleSheet(
            "background:#111; border:1px solid #555; border-radius:4px;"
            " padding:4px 8px; color:#c2c0b6;"
        )
        url_btn = QPushButton("⚡ Ingérer")
        url_btn.clicked.connect(self._ingest_url)
        url_btn.setStyleSheet(
            "background:#1a2a1a; border:1px solid #4caf50; color:#4caf50;"
            " border-radius:4px; padding:4px 12px;"
        )
        browse_row.addWidget(browse_btn)
        browse_row.addWidget(self._url_input)
        browse_row.addWidget(url_btn)
        ig_layout.addLayout(browse_row)

        # Texte brut
        txt_row = QHBoxLayout()
        self._raw_text = QTextEdit()
        self._raw_text.setPlaceholderText(
            "Coller du texte brut ici pour l'ingérer directement..."
        )
        self._raw_text.setMaximumHeight(80)
        self._raw_text.setStyleSheet(DARK)
        raw_domain = QComboBox()
        raw_domain.addItems(
            ["general","code","forge_core","systeme","securite","ia","reseau"]
        )
        raw_domain.setStyleSheet("background:#111; color:#c2c0b6; border:1px solid #444;")
        raw_btn = QPushButton("Ingérer texte")
        raw_btn.clicked.connect(lambda: self._ingest_raw_text(raw_domain.currentText()))
        raw_btn.setStyleSheet(
            "background:#1a1a2a; border:1px solid #2196f3; color:#2196f3;"
            " border-radius:4px; padding:4px 10px;"
        )
        txt_row.addWidget(self._raw_text)
        txt_row.addWidget(raw_domain)
        txt_row.addWidget(raw_btn)
        ig_layout.addLayout(txt_row)

        # Log ingestion
        self._ingest_log = QPlainTextEdit()
        self._ingest_log.setReadOnly(True)
        self._ingest_log.setMaximumHeight(70)
        self._ingest_log.setStyleSheet(DARK + "font-size:10px;")
        ig_layout.addWidget(self._ingest_log)
        layout.addWidget(ingest_group)

        # Lazy load stats — différé pour ne pas bloquer l'init
        from PySide6.QtCore import QTimer
        QTimer.singleShot(200, self._load_stats)

    def _load_stats(self):
        try:
            conn = sqlite3.connect(self._db_path, timeout=5)
            total   = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
            domains = conn.execute(
                "SELECT domain, COUNT(*) FROM rag_chunks "
                "GROUP BY domain ORDER BY COUNT(*) DESC"
            ).fetchall()
            conn.close()
            self._entropy.update_stats(domains, total)
        except Exception as e:
            self._ingest_log.appendPlainText("Stats ERR: " + str(e)[:60])

    def _do_search(self):
        q = self._search_input.text().strip()
        if not q:
            return
        top_k = int(self._topk.currentText())
        self._results.setPlainText("Recherche en cours...")
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.terminate()
        self._search_worker = RAGSearchWorker(q, self._db_path, top_k)
        self._search_worker.results_ready.connect(self._on_results)
        self._search_worker.start()

    def _on_results(self, results: list):
        if not results:
            self._results.setPlainText("Aucun résultat.")
            return
        if "error" in results[0]:
            self._results.setPlainText("ERR: " + results[0]["error"])
            return
        lines = []
        for i, r in enumerate(results, 1):
            pct = int(r["score"] * 100)
            lines.append(
                f"#{i} [{pct}%] {r['source']} [{r['domain']}]\n"
                + r["text"][:200] + "\n"
            )
        self._results.setPlainText("\n".join(lines))

    def _on_files_dropped(self, paths: list):
        for path in paths:
            self._do_ingest(path)

    def _on_url_dropped(self, url: str):
        self._do_ingest(url)

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Sélectionner un fichier",
            str(ROOT),
            "Tous (*.*) ;; PDF (*.pdf) ;; Texte (*.txt *.md) ;; Code (*.py)",
        )
        if path:
            self._do_ingest(path)

    def _ingest_url(self):
        url = self._url_input.text().strip()
        if url:
            self._do_ingest(url)

    def _do_ingest(self, path_or_url: str):
        self._ingest_log.appendPlainText("Ingestion : " + path_or_url[:60])
        self.ingest_requested.emit(path_or_url, self._db_path)

    def _ingest_raw_text(self, domain: str):
        """Ingestion directe de texte brut dans la DB."""
        text = self._raw_text.toPlainText().strip()
        if len(text) < 20:
            self._ingest_log.appendPlainText("Texte trop court (< 20 chars)")
            return
        import sys
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))
        try:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT OR IGNORE INTO rag_chunks(source,domain,text) VALUES(?,?,?)",
                ("manual_input", domain, text[:2000])
            )
            conn.commit()
            conn.close()
            self._ingest_log.appendPlainText(
                "✅ " + str(len(text)) + " chars ingérés → domaine=" + domain
            )
            self._raw_text.clear()
            QTimer.singleShot(1000, self._load_stats)
        except Exception as e:
            self._ingest_log.appendPlainText("ERR: " + str(e)[:80])

    def log_ingest(self, msg: str):
        self._ingest_log.appendPlainText(msg)
        self._load_stats()

    def closeEvent(self, event):
        """Arrêt propre des workers QThread."""
        if hasattr(self, '_search_worker') and self._search_worker is not None:
            if hasattr(self._search_worker, 'stop'):
                self._search_worker.stop()
            if hasattr(self._search_worker, 'wait'):
                self._search_worker.wait(1000)
            if hasattr(self._search_worker, 'terminate'):
                self._search_worker.terminate()
        super().closeEvent(event)


# ── Vue principale RAG ────────────────────────────────────────────────────────

class RAGView(QWidget):
    """
    Onglet RAG avec deux bases :
    - RAG Nokido (base principale)
    - RAG Externe (projet tiers)
    + Distillation de connaissance
    """
    ingest_requested = Signal(str, str)   # path_or_url, db_path

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6,6,6,6)

        title = QLabel("📚  RAG — Bases de connaissance")
        title.setStyleSheet("font-size:14px; font-weight:600; color:#c2c0b6;")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        # Tab 1 : RAG Nokido
        nokido_db = str(ROOT / "RAG" / "embeddings.db")
        self._rag_nokido = RAGPanel("Nokido", nokido_db)
        self._rag_nokido.ingest_requested.connect(self.ingest_requested)
        tabs.addTab(self._rag_nokido, "⚒  Nokido")

        # Tab 2 : RAG Externe
        ext_db = str(ROOT / "RAG" / "rag_external.db")
        self._ensure_external_db(ext_db)
        self._rag_external = RAGPanel("Projet Externe", ext_db)
        self._rag_external.ingest_requested.connect(self.ingest_requested)
        tabs.addTab(self._rag_external, "🌐  Projet Externe")

        # Tab 3 : Distillation
        self._distill_panel = DistillationPanel()
        tabs.addTab(self._distill_panel, "🧬  Distillation")

        layout.addWidget(tabs)

    def _ensure_external_db(self, db_path: str):
        """Crée le schéma du RAG externe si nécessaire."""
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    source    TEXT NOT NULL,
                    domain    TEXT NOT NULL DEFAULT 'general',
                    text      TEXT NOT NULL,
                    meta      TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    id        INTEGER PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    vector    BLOB
                )
            """)
            conn.commit()
            conn.close()
        except Exception:
            pass

    def log_ingest(self, msg: str, db_path: str):
        if "external" in db_path:
            self._rag_external.log_ingest(msg)
        else:
            self._rag_nokido.log_ingest(msg)


# ── Panel Distillation ────────────────────────────────────────────────────────

class DistillationPanel(QWidget):
    """
    Distille la connaissance Nokido vers un nouveau projet.
    Extrait : system_rules + patterns architecturaux + best practices.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8,8,8,8)

        info = QLabel(
            "🧬  Distillation — Extraire la connaissance LaForge\n"
            "Transfère les system_rules, patterns architecturaux et best practices\n"
            "vers un nouveau projet sous forme de RAG portable."
        )
        info.setStyleSheet("color:#888; font-size:11px; padding:8px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Config distillation
        cfg_group = QGroupBox("Configuration")
        cfg_group.setStyleSheet(
            "QGroupBox { border:1px solid #333; border-radius:6px;"
            " margin-top:8px; color:#666; padding-top:4px; }"
        )
        cfg = QVBoxLayout(cfg_group)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Projet cible :"))
        self._project_name = QLineEdit()
        self._project_name.setPlaceholderText("mon-nouveau-projet")
        self._project_name.setStyleSheet(
            "background:#111; border:1px solid #555; border-radius:4px;"
            " padding:4px; color:#c2c0b6;"
        )
        row1.addWidget(self._project_name)
        cfg.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Exporter vers :"))
        self._export_path = QLineEdit()
        self._export_path.setPlaceholderText("C:/projets/nouveau-projet/rag/")
        self._export_path.setStyleSheet(
            "background:#111; border:1px solid #555; border-radius:4px;"
            " padding:4px; color:#c2c0b6;"
        )
        browse_exp = QPushButton("...")
        browse_exp.setFixedWidth(32)
        browse_exp.clicked.connect(self._browse_export)
        row2.addWidget(self._export_path)
        row2.addWidget(browse_exp)
        cfg.addLayout(row2)

        layout.addWidget(cfg_group)

        # Sélection contenu
        content_group = QGroupBox("Contenu à distiller")
        content_group.setStyleSheet(
            "QGroupBox { border:1px solid #333; border-radius:6px;"
            " margin-top:8px; color:#666; padding-top:4px; }"
        )
        cl = QVBoxLayout(content_group)
        for label, key in [
            ("✅ system_rules (logique, lois, patterns)", "rules"),
            ("✅ Patterns architecturaux (forge_core)", "arch"),
            ("✅ Best practices (anti-lenteur, sécurité)", "practices"),
            ("⬜ Code complet (tous les modules)", "full_code"),
        ]:
            from PySide6.QtWidgets import QCheckBox
            cb = QCheckBox(label)
            cb.setChecked("⬜" not in label)
            cb.setStyleSheet("color:#c2c0b6; font-size:11px;")
            cb.setObjectName("distill_" + key)
            cl.addWidget(cb)
        layout.addWidget(content_group)

        # Bouton distiller
        distill_btn = QPushButton("🧬  Distiller vers le projet cible")
        distill_btn.setFixedHeight(36)
        distill_btn.setStyleSheet(
            "background:#1a0a3a; border:2px solid #9c27b0; color:#9c27b0;"
            " font-size:13px; font-weight:600; border-radius:6px;"
        )
        distill_btn.clicked.connect(self._do_distill)
        layout.addWidget(distill_btn)

        # Log
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(DARK + "font-size:11px;")
        layout.addWidget(self._log)

    def _browse_export(self):
        path = QFileDialog.getExistingDirectory(self, "Dossier export", str(ROOT))
        if path:
            self._export_path.setText(path)

    def _do_distill(self):
        project = self._project_name.text().strip()
        export  = self._export_path.text().strip()
        if not project:
            self._log.appendPlainText("❌ Nom de projet requis")
            return

        self._log.appendPlainText("🧬 Distillation démarrée → " + project)

        import sys
        if str(APP) not in sys.path:
            sys.path.insert(0, str(APP))

        DETACHED_PROCESS = 0x00000008
        distill_script = ROOT / "app" / "forge_knowledge_distiller.py"
        if distill_script.exists():
            subprocess.Popen(
                [sys.executable, str(distill_script),
                 "--project", project,
                 "--output",  export or str(ROOT / "distilled"),
                 "--include", "rules,arch,practices"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=DETACHED_PROCESS,
            )
            self._log.appendPlainText(
                "⚡ Distillation lancée en arrière-plan (DETACHED)\n"
                "Résultat dans : " + (export or str(ROOT / "distilled"))
            )
        else:
            # Distillation inline légère
            self._distill_inline(project, export)

    def _distill_inline(self, project: str, output_dir: str):
        """Distillation inline — extrait system_rules + exports JSON."""
        import sqlite3 as _sq
        db = ROOT / "RAG" / "embeddings.db"
        out_dir = Path(output_dir) if output_dir else ROOT / "distilled"
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            conn = _sq.connect(str(db), timeout=5)
            # system_rules
            rules = conn.execute(
                "SELECT tag, ring, title, content FROM system_rules ORDER BY ring, id"
            ).fetchall()
            # Chunks forge_core
            chunks = conn.execute(
                "SELECT source, domain, text FROM rag_chunks "
                "WHERE domain IN ('forge_core','code','ia') LIMIT 500"
            ).fetchall()
            conn.close()

            export = {
                "project":   project,
                "source":    "Nokido v17",
                "system_rules": [
                    {"tag": r[0], "ring": r[1], "title": r[2], "content": r[3]}
                    for r in rules
                ],
                "knowledge_chunks": len(chunks),
                "architecture": {
                    "mmap":      "live_bridge.map 256KB — zéro réseau",
                    "watchdog":  "DETACHED process — ctypes.windll.kernel32",
                    "swarm":     "IDLE→THINKING→STREAMING→SYNCING_RAG",
                    "security":  "SSH blocklist + _Config singleton + inputs validés",
                    "no_block":  "DETACHED_PROCESS + DEVNULL — jamais de boucle bloquante",
                }
            }

            out_file = out_dir / (project + "_knowledge.json")
            out_file.write_text(
                json.dumps(export, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )

            # RAG externe DB
            ext_db = out_dir / (project + "_rag.db")
            conn2  = _sq.connect(str(ext_db))
            conn2.execute("""CREATE TABLE IF NOT EXISTS rag_chunks
                (id INTEGER PRIMARY KEY, source TEXT, domain TEXT, text TEXT)""")
            conn2.executemany(
                "INSERT INTO rag_chunks(source,domain,text) VALUES(?,?,?)",
                [(c[0], c[1], c[2][:600]) for c in chunks]
            )
            conn2.commit()
            conn2.close()

            self._log.appendPlainText(
                f"✅ Distillé :\n"
                f"  {len(rules)} system_rules\n"
                f"  {len(chunks)} knowledge chunks\n"
                f"  → {out_file}\n"
                f"  → {ext_db}"
            )
        except Exception as e:
            self._log.appendPlainText("❌ " + str(e)[:120])