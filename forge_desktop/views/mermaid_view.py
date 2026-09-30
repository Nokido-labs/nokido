"""
forge_desktop/views/mermaid_view.py
=====================================
Vue Mermaid — Génération de diagrammes via Qwen2.5-Coder (llamacpp).

Fonctionnalités :
  - Champ prompt + sélecteur de type (flowchart, sequence, class, er...)
  - Génération via forge_mermaid_gen (Qwen2.5-Coder Q4_K_M)
  - Preview code Mermaid avec coloration syntaxique
  - Validation syntaxique en temps réel
  - Export .md / copie clipboard
  - Historique des 10 dernières générations (session)
  - Indicateur source : llamacpp natif vs template fallback
"""
from __future__ import annotations
import json
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QLineEdit, QTextEdit, QPlainTextEdit,
    QPushButton, QComboBox, QGroupBox, QListWidget,
    QListWidgetItem, QProgressBar, QFrame,
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

ROOT = Path(__file__).resolve().parent.parent.parent

DARK_INPUT = ("background:#0a0a0a; color:#c2c0b6;"
              " font-family:'Cascadia Code','Consolas'; font-size:12px;"
              " border:1px solid #333; border-radius:4px;")

DIAGRAM_TYPES = [
    ("flowchart",  "Flowchart (flux)"),
    ("sequence",   "Sequence (échanges)"),
    ("class",      "Class diagram"),
    ("er",         "ER diagram (BDD)"),
    ("state",      "State machine"),
    ("c4",         "C4 Component"),
    ("git",        "Git graph"),
    ("mind",       "Mindmap"),
]


# ── Coloration syntaxique Mermaid ─────────────────────────────────────────────

class MermaidHighlighter(QSyntaxHighlighter):
    """Coloration syntaxique basique pour le code Mermaid."""

    def highlightBlock(self, text: str):
        # Keywords
        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor("#2196f3"))
        kw_fmt.setFontWeight(500)
        for kw in ["flowchart", "sequenceDiagram", "classDiagram", "erDiagram",
                   "stateDiagram-v2", "gantt", "gitGraph", "mindmap", "C4Component",
                   "graph", "TD", "LR", "TB", "RL", "participant", "actor",
                   "note", "loop", "alt", "else", "end", "activate", "deactivate"]:
            import re
            for m in re.finditer(r'\b' + kw + r'\b', text):
                self.setFormat(m.start(), len(kw), kw_fmt)

        # Arrows
        arr_fmt = QTextCharFormat()
        arr_fmt.setForeground(QColor("#ff9800"))
        for pat in ["-->", "->>", "-->|", "-->>", "==>", "-.->", "---", "==>"]:
            import re
            for m in re.finditer(re.escape(pat), text):
                self.setFormat(m.start(), len(pat), arr_fmt)

        # Labels [...]  "..."
        lbl_fmt = QTextCharFormat()
        lbl_fmt.setForeground(QColor("#4caf50"))
        import re
        for m in re.finditer(r'\[.*?\]|"[^"]*"', text):
            self.setFormat(m.start(), m.end()-m.start(), lbl_fmt)

        # Comments %%
        cmt_fmt = QTextCharFormat()
        cmt_fmt.setForeground(QColor("#555"))
        cmt_fmt.setFontItalic(True)
        for m in re.finditer(r'%%.*$', text):
            self.setFormat(m.start(), len(text)-m.start(), cmt_fmt)


# ── Worker génération (non-bloquant) ──────────────────────────────────────────

class MermaidGenWorker(QThread):
    """Lance generate_mermaid dans un thread séparé."""
    result_ready = Signal(dict)

    def __init__(self, prompt: str, diagram_type: str, parent=None):
        super().__init__(parent)
        self._prompt = prompt
        self._type   = diagram_type

    def run(self):
        import sys
        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT / "app"))
        try:
            from forge_mermaid_gen import generate_mermaid
            result = generate_mermaid(self._prompt, self._type)
        except Exception as e:
            result = {
                "ok": False, "code": "", "error": str(e)[:120],
                "source": "error", "elapsed_ms": 0,
            }
        self.result_ready.emit(result)


# DEBUG_PANORAMA: PanoramaWorker injecte le 2026-04-16
class PanoramaWorker(QThread):
    """Lance build_panorama() dans un thread separe (scan AST + Qwen)."""
    result_ready = Signal(dict)

    def run(self):
        import sys, time
        print("[mermaid_view] PanoramaWorker.run() START", flush=True)
        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT / "app"))
        try:
            from forge_panorama_builder import build_panorama
            t0 = time.monotonic()
            data = build_panorama()
            elapsed = (time.monotonic() - t0) * 1000.0
            # Adapter au format attendu par _on_result
            result = {
                "ok": bool(data.get("llm_ok", False)),
                "code": data.get("mermaid_llm") or data.get("mermaid_direct", ""),
                "type": "flowchart",
                "source": f"panorama({data.get('llm_source','?')}, {data.get('nb_modules',0)}mods)",
                "elapsed_ms": elapsed,
                "error": "",
            }
            print(f"[mermaid_view] PanoramaWorker DONE {elapsed:.0f}ms ok={result['ok']}", flush=True)
        except Exception as e:
            print(f"[mermaid_view] PanoramaWorker ERROR: {e}", flush=True)
            result = {
                "ok": False, "code": "", "error": str(e)[:200],
                "source": "panorama_error", "elapsed_ms": 0,
            }
        self.result_ready.emit(result)


# ── Vue principale ────────────────────────────────────────────────────────────

class MermaidView(QWidget):
    """Vue complète génération Mermaid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: list[dict] = []
        self._worker: MermaidGenWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Titre
        title = QLabel("📊  Générateur Mermaid — Qwen2.5-Coder (llamacpp)")
        title.setStyleSheet("font-size:14px; font-weight:600; color:#c2c0b6;")
        layout.addWidget(title)

        # ── Panneau input ─────────────────────────────────────────────────────
        input_group = QGroupBox("Requête")
        input_group.setStyleSheet(
            "QGroupBox { border:1px solid #333; border-radius:6px;"
            " margin-top:8px; color:#666; padding-top:4px; }"
        )
        ig = QVBoxLayout(input_group)

        # Prompt
        self._prompt = QLineEdit()
        self._prompt.setPlaceholderText(
            "Décris le diagramme… ex: 'architecture microservices avec auth et BDD'"
        )
        self._prompt.setStyleSheet(
            "background:#111; border:1px solid #555; border-radius:4px;"
            " padding:6px 8px; color:#c2c0b6; font-size:13px;"
        )
        self._prompt.returnPressed.connect(self._generate)
        ig.addWidget(self._prompt)

        # Ligne type + bouton
        ctrl_row = QHBoxLayout()
        type_lbl = QLabel("Type :")
        type_lbl.setStyleSheet("color:#888; font-size:11px;")
        self._type_sel = QComboBox()
        for key, label in DIAGRAM_TYPES:
            self._type_sel.addItem(label, key)
        self._type_sel.setStyleSheet(
            "background:#111; color:#c2c0b6; border:1px solid #444;"
            " border-radius:4px; padding:3px 6px; font-size:11px;"
        )

        self._gen_btn = QPushButton("▶  Générer")
        self._gen_btn.setStyleSheet(
            "background:#1a2a1a; border:1px solid #4caf50; color:#4caf50;"
            " border-radius:4px; padding:5px 16px; font-size:12px; font-weight:600;"
        )
        self._gen_btn.clicked.connect(self._generate)

        # DEBUG_PANORAMA: bouton dedie panorama Nokido (scan AST 219 modules)
        self._pano_btn = QPushButton("📐 Panorama Nokido")
        self._pano_btn.setStyleSheet(
            "background:#2a1a2a; border:1px solid #b388ff; color:#b388ff;"
            " border-radius:4px; padding:5px 14px; font-size:11px; font-weight:600;"
        )
        self._pano_btn.setToolTip(
            "Scan AST de app/forge_*.py + generation Mermaid via Qwen.\n"
            "Genere le panorama actualise du code Nokido (~30s)."
        )
        self._pano_btn.clicked.connect(self._generate_panorama)

        ctrl_row.addWidget(type_lbl)
        ctrl_row.addWidget(self._type_sel)
        ctrl_row.addStretch()
        ctrl_row.addWidget(self._pano_btn)
        ctrl_row.addWidget(self._gen_btn)
        ig.addLayout(ctrl_row)
        layout.addWidget(input_group)

        # ── Progress bar ──────────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indéterminé pendant génération
        self._progress.setFixedHeight(4)
        self._progress.setVisible(False)
        self._progress.setStyleSheet(
            "QProgressBar { border:none; background:#111; border-radius:2px; }"
            "QProgressBar::chunk { background:#4caf50; border-radius:2px; }"
        )
        layout.addWidget(self._progress)

        # ── Splitter : code | historique ─────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)

        # Code Mermaid
        code_group = QGroupBox("Code Mermaid généré")
        code_group.setStyleSheet(
            "QGroupBox { border:1px solid #2a5a2a; border-radius:6px;"
            " margin-top:8px; color:#4caf50; padding-top:4px; }"
        )
        cg = QVBoxLayout(code_group)

        self._code_edit = QPlainTextEdit()
        self._code_edit.setStyleSheet(DARK_INPUT)
        self._code_edit.setFont(QFont("Cascadia Code", 11))
        self._code_edit.setPlaceholderText("Le code Mermaid apparaîtra ici…")
        self._highlighter = MermaidHighlighter(self._code_edit.document())
        cg.addWidget(self._code_edit)

        # Barre statut
        status_row = QHBoxLayout()
        self._status_lbl  = QLabel("Prêt")
        self._status_lbl.setStyleSheet("font-size:10px; color:#888;")
        self._source_lbl  = QLabel("")
        self._source_lbl.setStyleSheet("font-size:10px; color:#555;")
        self._valid_lbl   = QLabel("")
        self._valid_lbl.setStyleSheet("font-size:10px;")

        copy_btn = QPushButton("Copier")
        copy_btn.setFixedWidth(60)
        copy_btn.setStyleSheet(
            "background:#1a1a1a; border:1px solid #444; border-radius:4px;"
            " padding:2px 8px; font-size:10px; color:#888;"
        )
        copy_btn.clicked.connect(self._copy_code)

        export_btn = QPushButton("Export .md")
        export_btn.setFixedWidth(70)
        export_btn.setStyleSheet(copy_btn.styleSheet())
        export_btn.clicked.connect(self._export_md)

        status_row.addWidget(self._status_lbl)
        status_row.addWidget(self._source_lbl)
        status_row.addStretch()
        status_row.addWidget(self._valid_lbl)
        status_row.addWidget(copy_btn)
        status_row.addWidget(export_btn)
        cg.addLayout(status_row)
        splitter.addWidget(code_group)

        # Historique
        hist_group = QGroupBox("Historique (session)")
        hist_group.setStyleSheet(
            "QGroupBox { border:1px solid #333; border-radius:6px;"
            " margin-top:8px; color:#666; padding-top:4px; }"
        )
        hist_group.setFixedWidth(240)
        hg = QVBoxLayout(hist_group)

        self._hist_list = QListWidget()
        self._hist_list.setStyleSheet(
            "background:#0a0a0a; color:#888; border:none;"
            " font-size:10px; font-family:'Cascadia Code';"
        )
        self._hist_list.itemClicked.connect(self._load_from_history)
        hg.addWidget(self._hist_list)

        clear_hist = QPushButton("Vider")
        clear_hist.setStyleSheet(
            "background:#1a1a1a; border:1px solid #333; border-radius:4px;"
            " padding:2px 8px; font-size:10px; color:#666;"
        )
        clear_hist.clicked.connect(self._clear_history)
        hg.addWidget(clear_hist)
        splitter.addWidget(hist_group)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        layout.addWidget(splitter)

        # ── Exemples rapides ─────────────────────────────────────────────────
        ex_row = QHBoxLayout()
        ex_row.addWidget(QLabel("Exemples :"))
        examples = [
            ("Architecture Nokido", "flowchart"),
            ("Auth → Token → API", "sequence"),
            ("State machine swarm", "state"),
            ("BDD utilisateurs", "er"),
        ]
        for label, dtype in examples:
            btn = QPushButton(label)
            btn.setStyleSheet(
                "background:#1a1a2a; border:1px solid #2196f3; color:#2196f3;"
                " border-radius:4px; padding:3px 8px; font-size:10px;"
            )
            # Capturer les valeurs dans la closure
            btn.clicked.connect(
                lambda checked, l=label, d=dtype: self._quick_example(l, d)
            )
            ex_row.addWidget(btn)
        ex_row.addStretch()
        layout.addLayout(ex_row)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _generate(self):
        prompt = self._prompt.text().strip()
        if not prompt:
            self._status_lbl.setText("❌ Prompt vide")
            return

        dtype = self._type_sel.currentData()

        # Désactiver le bouton pendant la génération
        self._gen_btn.setEnabled(False)
        self._gen_btn.setText("⏳ Génération…")
        self._progress.setVisible(True)
        self._status_lbl.setText("Génération via Qwen2.5-Coder…")
        self._valid_lbl.setText("")

        # Lancer le worker non-bloquant
        self._worker = MermaidGenWorker(prompt, dtype)
        self._worker.result_ready.connect(self._on_result)
        self._worker.start()

    def _generate_panorama(self):
        """Lance le scan AST + generation panorama via PanoramaWorker."""
        print("[mermaid_view] _generate_panorama() CLICK", flush=True)
        self._gen_btn.setEnabled(False)
        self._pano_btn.setEnabled(False)
        self._pano_btn.setText("⏳ Scan AST…")
        self._progress.setVisible(True)
        self._status_lbl.setText("Scan AST + generation Qwen (peut prendre 30s)…")
        self._valid_lbl.setText("")
        self._prompt.setText("[Panorama Nokido — scan AST automatique]")

        self._worker = PanoramaWorker(self)
        self._worker.result_ready.connect(self._on_panorama_result)
        self._worker.start()

    def _on_panorama_result(self, result: dict):
        """Callback panorama : delegue a _on_result puis restaure le bouton."""
        self._on_result(result)
        self._pano_btn.setEnabled(True)
        self._pano_btn.setText("📐 Panorama Nokido")

    def _on_result(self, result: dict):
        self._gen_btn.setEnabled(True)
        self._gen_btn.setText("▶  Générer")
        self._progress.setVisible(False)

        if result.get("ok"):
            code = result.get("code", "")
            self._code_edit.setPlainText(code)
            elapsed = result.get("elapsed_ms", 0)
            source  = result.get("source", "?")
            self._status_lbl.setText(f"✅ Généré en {elapsed:.0f}ms")
            self._source_lbl.setText(f"source: {source}")

            # Validation
            from forge_mermaid_gen import validate_mermaid
            v = validate_mermaid(code)
            if v["ok"]:
                self._valid_lbl.setText("✅ syntaxe OK")
                self._valid_lbl.setStyleSheet("font-size:10px; color:#4caf50;")
            else:
                self._valid_lbl.setText("⚠ " + v["error"][:40])
                self._valid_lbl.setStyleSheet("font-size:10px; color:#ff9800;")

            # Ajouter à l'historique
            self._add_to_history(self._prompt.text(), result)
        else:
            err = result.get("error", "Erreur inconnue")
            self._status_lbl.setText("❌ " + err[:80])
            self._status_lbl.setStyleSheet("font-size:10px; color:#f44336;")

    def _add_to_history(self, prompt: str, result: dict):
        entry = {
            "prompt":  prompt,
            "type":    result.get("type", "?"),
            "code":    result.get("code", ""),
            "source":  result.get("source", "?"),
            "elapsed": result.get("elapsed_ms", 0),
            "ts":      time.strftime("%H:%M:%S"),
        }
        self._history.insert(0, entry)
        if len(self._history) > 10:
            self._history = self._history[:10]

        item = QListWidgetItem(
            entry["ts"] + "  " + entry["type"] + "\n" + prompt[:30]
        )
        item.setData(Qt.UserRole, len(self._history) - 1)
        self._hist_list.insertItem(0, item)

    def _load_from_history(self, item: QListWidgetItem):
        idx = item.data(Qt.UserRole)
        if 0 <= idx < len(self._history):
            entry = self._history[idx]
            self._code_edit.setPlainText(entry["code"])
            self._prompt.setText(entry["prompt"])
            self._status_lbl.setText(
                f"Historique {entry['ts']} ({entry['elapsed']:.0f}ms)"
            )

    def _clear_history(self):
        self._history.clear()
        self._hist_list.clear()

    def _copy_code(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._code_edit.toPlainText())
        self._status_lbl.setText("Copié dans le presse-papier")

    def _export_md(self):
        from PySide6.QtWidgets import QFileDialog
        code = self._code_edit.toPlainText()
        if not code.strip():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter Mermaid", str(ROOT / "docs"),
            "Markdown (*.md)"
        )
        if path:
            content = f"```mermaid\n{code}\n```\n"
            Path(path).write_text(content, encoding="utf-8")
            self._status_lbl.setText(f"Exporté : {Path(path).name}")

    def _quick_example(self, label: str, dtype: str):
        self._prompt.setText(label)
        # Sélectionner le bon type
        for i in range(self._type_sel.count()):
            if self._type_sel.itemData(i) == dtype:
                self._type_sel.setCurrentIndex(i)
                break
        self._generate()

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