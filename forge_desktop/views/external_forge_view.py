"""
forge_desktop/views/external_forge_view.py — Forge appliquée à des projets externes
====================================================================================
Applique l'intelligence Nokido (Cerberus, LibraryShifter, SourceDiscovery,
TokenOptimizer, MermaidGen, ReverseEngineer) à n'importe quel projet Python externe.

Workflow :
  1. Sélectionner un dossier projet
  2. Scanner automatiquement (libs, qualité, complexité)
  3. Choisir une action (Optimiser / Documenter / Diagrammer / Reverse / Enrichir RAG)
  4. Voir les résultats avec diff et score

Aucune modification permanente sans confirmation — tout passe par un aperçu diff.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui  import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QSplitter, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))

# ── Styles ─────────────────────────────────────────────────────────────────────
DARK  = "background:#0e1117; color:#c2c0b6; font-family:'Segoe UI'; font-size:12px;"
CARD  = "background:#141420; border:1px solid #2a2a3a; border-radius:6px; padding:6px;"
MONO  = "font-family:'Cascadia Code','Consolas'; font-size:11px;"
GREEN = "#4caf50"; ORANGE = "#ff9800"; RED = "#f44336"; BLUE = "#2196f3"

BTN = ("QPushButton {{ background:{bg}; border:1px solid {bd}; border-radius:4px;"
       " padding:5px 14px; color:{fg}; font-size:11px; }}"
       "QPushButton:hover {{ background:{hv}; }}")

def _btn(bg="#1e1e2e", bd="#444", fg="#c2c0b6", hv="#2a2a3e"):
    return BTN.format(bg=bg, bd=bd, fg=fg, hv=hv)


# ── Analyse statique d'un projet ───────────────────────────────────────────────

def _scan_project(folder: Path) -> dict:
    """Analyse statique d'un projet Python.

    Args:
        folder: Dossier racine du projet.

    Returns:
        Dict avec files, total_lines, slow_libs, complexity, top_files.
    """
    py_files = list(folder.rglob("*.py"))
    # Exclure venv / .git / __pycache__
    py_files = [f for f in py_files
                if not any(x in str(f) for x in
                           [".git", "__pycache__", "venv", ".venv", "node_modules"])]

    total_lines = 0
    slow_libs   = {}
    top_files   = []  # (path, lines, score)

    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from forge_library_shifter import LibraryShifter, LIBRARY_MAPPING
        shifter = LibraryShifter()
    except Exception:
        shifter = None

    try:
        from forge_token_optimizer import get_optimizer
        opt = get_optimizer()
    except Exception:
        opt = None

    for f in py_files[:50]:   # cap 50 fichiers pour la vitesse
        try:
            src   = f.read_text(encoding="utf-8", errors="replace")
            lines = len(src.splitlines())
            total_lines += lines

            # Libs lentes
            if shifter:
                found = shifter.scan_for_optimization(str(f))
                for lib in found:
                    slow_libs[lib] = slow_libs.get(lib, 0) + 1

            # Score de densité (rapport commentaires/code)
            code_lines    = sum(1 for l in src.splitlines()
                               if l.strip() and not l.strip().startswith("#"))
            comment_lines = sum(1 for l in src.splitlines()
                               if l.strip().startswith("#"))
            ratio = comment_lines / max(code_lines, 1)
            # Score 0-100 : 0 = pas de doc, 100 = bien documenté
            doc_score = min(100, int(ratio * 200))
            top_files.append((f, lines, doc_score))
        except Exception:
            pass

    top_files.sort(key=lambda x: -x[1])  # par taille

    return {
        "folder":      str(folder),
        "n_files":     len(py_files),
        "total_lines": total_lines,
        "slow_libs":   slow_libs,
        "top_files":   top_files[:15],
        "avg_doc":     int(sum(x[2] for x in top_files) / max(1, len(top_files))),
    }



# ── Helpers GitHub ─────────────────────────────────────────────────────────────

def _parse_github_url(url):
    import re as _re
    url = url.strip().rstrip("/").rstrip(".git")
    m = _re.match(r"^([\w.\-]+)/([\w.\-]+)$", url)
    if m:
        return m.group(1), m.group(2)
    m2 = _re.match(r"https?://github\.com/([\w.\-]+)/([\w.\-]+)", url)
    if m2:
        return m2.group(1), m2.group(2)
    return None


def _load_github_token():
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        try:
            for line in (ROOT / "Nokido.env").read_text(encoding="utf-8").splitlines():
                if line.startswith("GITHUB_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
        except Exception:
            pass
    return token


# ── Worker GitHub ──────────────────────────────────────────────────────────────

class _GitHubWorker(QThread):
    progress = Signal(str)
    done     = Signal(str, str)
    error    = Signal(str)

    def __init__(self, mode, owner, repo, dest, token):
        super().__init__()
        self._mode  = mode
        self._owner = owner
        self._repo  = repo
        self._dest  = dest
        self._token = token

    def run(self):
        try:
            if self._mode == "info":
                self.done.emit(*self._do_info())
            elif self._mode == "clone":
                self.done.emit(*self._do_clone())
            elif self._mode == "fork":
                self.done.emit(*self._do_fork())
        except Exception as e:
            self.error.emit(str(e))

    def _gh_get(self, endpoint):
        import urllib.request
        url     = "https://api.github.com/" + endpoint.lstrip("/")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "LaForge/17"}
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    def _gh_post(self, endpoint, payload):
        import urllib.request
        url     = "https://api.github.com/" + endpoint.lstrip("/")
        headers = {"Accept": "application/vnd.github+json",
                   "User-Agent": "LaForge/17",
                   "Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    def _do_info(self):
        NL = chr(10)
        self.progress.emit("Infos " + self._owner + "/" + self._repo + "...")
        repo      = self._gh_get("repos/" + self._owner + "/" + self._repo)
        langs_raw = self._gh_get("repos/" + self._owner + "/" + self._repo + "/languages")
        total_b   = sum(langs_raw.values()) or 1
        langs     = ", ".join(
            k + " " + str(v * 100 // total_b) + "%"
            for k, v in sorted(langs_raw.items(), key=lambda x: -x[1])[:5]
        )
        commits_raw = self._gh_get(
            "repos/" + self._owner + "/" + self._repo + "/commits?per_page=5"
        )
        commits_txt = NL.join(
            "  - " + c["commit"]["message"].splitlines()[0][:60]
            + " (" + c["commit"]["author"]["date"][:10] + ")"
            for c in commits_raw
        )
        readme = "(README non accessible)"
        try:
            import base64
            rd     = self._gh_get("repos/" + self._owner + "/" + self._repo + "/readme")
            readme = base64.b64decode(rd.get("content", "")).decode("utf-8", "replace")[:400]
        except Exception:
            pass
        info = NL.join([
            "Repo : " + str(repo.get("full_name", "")),
            "-" * 55,
            "Description : " + str(repo.get("description", "") or "—"),
            "Stars       : " + str(repo.get("stargazers_count", 0)),
            "Forks       : " + str(repo.get("forks_count", 0)),
            "Issues      : " + str(repo.get("open_issues_count", 0)),
            "Dernier push: " + str(repo.get("pushed_at", "?"))[:10],
            "Taille      : " + str(repo.get("size", 0)) + " KB",
            "Branche     : " + str(repo.get("default_branch", "main")),
            "Langages    : " + langs,
            "",
            "Derniers commits :",
            commits_txt,
            "",
            "README :",
            readme,
        ])
        return info, ""

    def _do_clone(self):
        NL = chr(10)
        import subprocess as _sp
        clone_url = "https://github.com/" + self._owner + "/" + self._repo + ".git"
        dest      = self._dest / self._repo
        if dest.exists():
            return "Dossier deja existant : " + str(dest), str(dest)
        self.progress.emit("Clonage " + self._repo + "...")
        r = _sp.run(
            ["git", "clone", "--depth=1", clone_url, str(dest)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120,
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[:200])
        py = [f for f in dest.rglob("*.py")
              if not any(x in str(f) for x in ["venv",".venv","__pycache__",".git"])]
        info = NL.join([
            "Clone OK : " + self._owner + "/" + self._repo,
            "-" * 50,
            "Destination  : " + str(dest),
            "Fichiers .py : " + str(len(py)),
            "",
            "Pret a analyser — clique sur Scanner ce projet.",
        ])
        return info, str(dest)

    def _do_fork(self):
        NL = chr(10)
        if not self._token:
            raise RuntimeError(
                "GITHUB_TOKEN requis pour forker. "
                "Ajoute GITHUB_TOKEN=ghp_... dans Nokido.env"
            )
        self.progress.emit("Fork de " + self._owner + "/" + self._repo + "...")
        result     = self._gh_post(
            "repos/" + self._owner + "/" + self._repo + "/forks", {}
        )
        fork_owner = result.get("owner", {}).get("login", "?")
        fork_url   = result.get("clone_url", "")
        fork_name  = result.get("name", self._repo)
        self.progress.emit("Fork cree : " + fork_owner + "/" + fork_name + " — clonage...")
        import subprocess as _sp, time as _t
        _t.sleep(3)
        dest = self._dest / fork_name
        r    = _sp.run(
            ["git", "clone", "--depth=1", fork_url, str(dest)],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[:200])
        _sp.run(
            ["git", "remote", "add", "upstream",
             "https://github.com/" + self._owner + "/" + self._repo + ".git"],
            capture_output=True, cwd=str(dest),
        )
        py = [f for f in dest.rglob("*.py")
              if not any(x in str(f) for x in ["venv",".venv","__pycache__",".git"])]
        info = NL.join([
            "Fork & Clone OK : " + fork_owner + "/" + fork_name,
            "-" * 50,
            "Upstream     : " + self._owner + "/" + self._repo,
            "Destination  : " + str(dest),
            "Fichiers .py : " + str(len(py)),
            "Remote origin: " + fork_url,
            "Remote upstream : configure",
            "",
            "Pret a forger — clique sur Scanner ce projet.",
        ])
        return info, str(dest)

# ── Workers ────────────────────────────────────────────────────────────────────

class _ScanWorker(QThread):
    """Analyse statique du projet en arrière-plan."""
    done  = Signal(dict)
    error = Signal(str)

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self._folder = folder

    def run(self) -> None:
        try:
            result = _scan_project(self._folder)
            self.done.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class _ActionWorker(QThread):
    """Exécute une action Nokido sur un fichier cible."""
    progress = Signal(str)
    done     = Signal(str, str)   # (result_text, diff_text)
    error    = Signal(str)

    def __init__(self, action: str, file_path: Path,
                 project_folder: Path, model: str) -> None:
        super().__init__()
        self._action  = action
        self._file    = file_path
        self._project = project_folder
        self._model   = model

    def run(self) -> None:
        try:
            src = self._file.read_text(encoding="utf-8", errors="replace")
            result = ""
            diff   = ""

            if self._action == "analyse":
                result, diff = self._do_analyse(src)
            elif self._action == "documenter":
                result, diff = self._do_document(src)
            elif self._action == "diagramme":
                result, diff = self._do_diagram(src)
            elif self._action == "reverse":
                result, diff = self._do_reverse(src)
            elif self._action == "optimiser":
                result, diff = self._do_optimize(src)
            elif self._action == "enrichir_rag":
                result, diff = self._do_enrich_rag(src)

            self.done.emit(result, diff)
        except Exception as e:
            self.error.emit(str(e))

    def _do_analyse(self, src: str) -> tuple[str, str]:
        """Analyse complète : complexité, libs, densité."""
        sys.path.insert(0, str(ROOT / "tools"))
        from forge_token_optimizer  import get_optimizer
        from forge_library_shifter  import LibraryShifter, LIBRARY_MAPPING

        opt     = get_optimizer()
        shifter = LibraryShifter()

        lines  = src.splitlines()
        n_fn   = src.count("def ")
        n_cls  = src.count("class ")
        n_imp  = sum(1 for l in lines if l.strip().startswith(("import ", "from ")))
        n_doc  = sum(1 for l in lines if '"""' in l or "'''" in l)
        n_comm = sum(1 for l in lines if l.strip().startswith("#"))

        # Score de qualité
        doc_ratio   = n_doc / max(n_fn + n_cls, 1)
        complexity  = len(lines) / max(n_fn, 1)
        quality     = min(100, int(50 * min(doc_ratio, 1) + 50 * min(1, 30 / max(complexity, 30))))

        # Libs lentes
        slow = shifter.scan_for_optimization(str(self._file))
        libs_info = ""
        if slow:
            libs_info = "\n🐌 Libs substituables :\n"
            for lib in slow:
                target = LIBRARY_MAPPING[lib]["target"]
                benefit = LIBRARY_MAPPING[lib]["benefit"]
                libs_info += f"  {lib} → {target} : {benefit}\n"

        # Compression potentielle
        compressed, stats = opt.optimize_prompt(src, aggressive=False)

        result = (
            f"📊 Analyse : {self._file.name}\n"
            f"{'─'*50}\n"
            f"Lignes       : {len(lines)}\n"
            f"Fonctions    : {n_fn}  |  Classes : {n_cls}\n"
            f"Imports      : {n_imp}\n"
            f"Docstrings   : {n_doc}  |  Commentaires : {n_comm}\n"
            f"Score qualité: {quality}/100\n"
            f"Complexité   : {complexity:.0f} lignes/fn\n"
            f"Compression  : {stats['reduction_pct']:.0f}% possible\n"
            f"{libs_info}"
        )
        self.progress.emit(f"Score qualité : {quality}/100")
        return result, ""

    def _do_document(self, src: str) -> tuple[str, str]:
        """Génère des docstrings via laforge-qwen ou Groq."""
        self.progress.emit("Génération docstrings en cours...")
        import os as _os
        from pathlib import Path as _P
        env_path = _P(__file__).resolve().parent.parent.parent / "Nokido.env"

        model = self._model

        # Injecter la clé si disponible
        try:
            env_txt = env_path.read_text(encoding="utf-8", errors="replace")
            for l in env_txt.splitlines():
                if l.startswith("GROQ_API_KEY="):
                    _os.environ["GROQ_API_KEY"] = l.split("=",1)[1].strip()
                elif l.startswith("OPENROUTEUR_API_KEY="):
                    _os.environ["OPENROUTER_API_KEY"] = l.split("=",1)[1].strip()
        except Exception:
            pass

        from forge_token_optimizer import get_optimizer
        opt = get_optimizer()

        # Préparer le prompt avec compression
        compressed, _ = opt.optimize_prompt(src, max_chars=6000)

        prompt = (
            f"Ajoute des docstrings Google-style à toutes les fonctions et classes "
            f"de ce fichier Python. Retourne UNIQUEMENT le code Python complet modifié, "
            f"sans explication ni markdown.\n\n"
            f"```python\n{compressed}\n```"
        )

        try:
            import litellm
            import asyncio
            async def _call():
                r = await litellm.acompletion(
                    model=model,
                    messages=[{"role":"user","content": prompt}],
                    temperature=0.1, max_tokens=3000,
                )
                return r.choices[0].message.content
            result_code = asyncio.run(_call())

            # Nettoyer le markdown
            if "```python" in result_code:
                result_code = result_code.split("```python")[1].split("```")[0].strip()

            # Générer le diff textuel
            diff = _simple_diff(src, result_code)
            return result_code, diff

        except Exception as e:
            return f"[ERREUR] {e}\n\nPrompt prêt — {len(prompt)} chars", ""

    def _do_diagram(self, src: str) -> tuple[str, str]:
        """Génère un diagramme Mermaid de l'architecture."""
        self.progress.emit("Génération diagramme Mermaid...")
        import asyncio

        try:
            from forge_mermaid_gen import generate_mermaid_async
            diagram = asyncio.run(generate_mermaid_async(src, model=self._model))
            return f"```mermaid\n{diagram}\n```", ""
        except Exception as e:
            # Fallback : générer via AST
            return _ast_to_mermaid(src, self._file.name), ""

    def _do_reverse(self, src: str) -> tuple[str, str]:
        """Reverse engineer le code opaque."""
        self.progress.emit("Analyse reverse engineering...")
        from forge_source_discovery import ForgeSourceDiscovery
        disc   = ForgeSourceDiscovery(summary_model=self._model)
        result = disc.reverse_engineer_code_sync(
            src[:5000], context=f"Fichier {self._file.name}", ingest=False
        )
        return result.get("doc", "Échec"), ""

    def _do_optimize(self, src: str) -> tuple[str, str]:
        """Optimise le code via TokenOptimizer + suggestions."""
        from forge_token_optimizer import get_optimizer
        opt = get_optimizer()
        compressed, stats = opt.optimize_prompt(src, aggressive=False)
        info = (
            f"📦 Optimisation : {self._file.name}\n"
            f"Original  : {stats['original_chars']} chars\n"
            f"Compressé : {stats['final_chars']} chars\n"
            f"Réduction : {stats['reduction_pct']}%\n\n"
            f"Code compressé (commentaires/docstrings supprimés) :\n"
            f"{'─'*50}\n{compressed}"
        )
        diff = _simple_diff(src, compressed)
        return info, diff

    def _do_enrich_rag(self, src: str) -> tuple[str, str]:
        """Enrichit le RAG Nokido avec ce fichier."""
        self.progress.emit("Ingestion dans le RAG Nokido...")
        from forge_source_discovery import ForgeSourceDiscovery
        disc = ForgeSourceDiscovery()
        ok   = disc.ingest_to_rag(
            content=src[:8000],
            url=f"file://{self._file}",
            title=self._file.name,
            query=f"code Python {self._file.stem}",
            meta={"project": str(self._project), "type": "source"},
        )
        return f"{'✅' if ok else '❌'} RAG ingestion : {self._file.name}\n({len(src)} chars)", ""


def _simple_diff(old: str, new: str) -> str:
    """Diff ligne par ligne simple (sans lib externe)."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = []
    for i, (o, n) in enumerate(zip(old_lines, new_lines)):
        if o != n:
            diff.append(f"L{i+1} - {o[:80]}")
            diff.append(f"L{i+1} + {n[:80]}")
    if len(new_lines) > len(old_lines):
        for l in new_lines[len(old_lines):]:
            diff.append(f"+ {l[:80]}")
    return "\n".join(diff[:50]) or "(aucun changement détecté)"


def _ast_to_mermaid(src: str, filename: str) -> str:
    """Génère un diagramme Mermaid basique depuis l'AST."""
    try:
        tree    = ast.parse(src)
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        fns     = [n.name for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and not n.name.startswith("_")][:10]
        lines   = [f"graph TD", f'  M["{filename}"]']
        for cls in classes[:6]:
            lines.append(f'  M --> C_{cls}["{cls}"]')
        for fn in fns[:8]:
            lines.append(f'  M --> F_{fn}("{fn}()")')
        return "\n".join(lines)
    except Exception:
        return "graph TD\n  A[Impossible de parser le fichier]"


# ── Vue principale ─────────────────────────────────────────────────────────────

class ExternalForgeView(QWidget):
    """Onglet Forge Externe — applique Nokido à n'importe quel projet Python."""

    ACTIONS = [
        ("🔍 Analyser",       "analyse",    BLUE),
        ("📝 Documenter",     "documenter", GREEN),
        ("📊 Diagramme",      "diagramme",  "#9B59B6"),
        ("🧬 Reverse",        "reverse",    ORANGE),
        ("📦 Compresser",     "optimiser",  "#1ABC9C"),
        ("📚 Ingérer RAG",    "enrichir_rag", "#E74C3C"),
    ]

    MODELS = [
        "groq/llama-3.3-70b-versatile",
        "openrouter/meta-llama/llama-3.3-70b-instruct:free",
        "ollama/qwen2.5-coder:7b",
        "ollama/laforge-qwen",
        "groq/llama-3.1-8b-instant",
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(DARK)
        self._folder: Path | None = None
        self._scan:   dict        = {}
        self._worker: QThread | None = None
        self._build()

    # ── Build UI ───────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root_lo = QVBoxLayout(self)
        root_lo.setContentsMargins(8, 8, 8, 8)
        root_lo.setSpacing(6)

        # Titre + sélection dossier
        header = QHBoxLayout()
        title  = QLabel("🔧  Forge Externe — Applique Nokido à vos projets")
        title.setStyleSheet("font-size:14px; font-weight:600; color:#c2c0b6;")
        header.addWidget(title)
        header.addStretch()

        self._folder_btn = QPushButton("📂  Ouvrir projet...")
        self._folder_btn.setStyleSheet(_btn(bg="#1a1a30", bd=BLUE, fg=BLUE, hv="#2a2a40"))
        self._folder_btn.clicked.connect(self._pick_folder)
        header.addWidget(self._folder_btn)

        self._folder_lbl = QLabel("Aucun projet sélectionné")
        self._folder_lbl.setStyleSheet("color:#555; font-size:11px;")
        header.addWidget(self._folder_lbl)
        root_lo.addLayout(header)

        # ── Barre GitHub ───────────────────────────────────────────────────────
        gh_row = QHBoxLayout()
        gh_lbl = QLabel("GitHub :")
        gh_lbl.setStyleSheet("color:#666; font-size:11px;")
        gh_row.addWidget(gh_lbl)

        self._gh_input = QLineEdit()
        self._gh_input.setPlaceholderText("owner/repo  ou  https://github.com/owner/repo")
        self._gh_input.setStyleSheet(
            "QLineEdit { background:#0d0d18; border:1px solid #333; border-radius:4px;"
            " color:#c2c0b6; padding:4px 8px; font-size:11px; min-width:300px; }"
            "QLineEdit:focus { border-color:#2196f3; }"
        )
        self._gh_input.returnPressed.connect(self._gh_info)
        gh_row.addWidget(self._gh_input)

        for _lbl, _slot, _col in [
            ("🔍 Infos",   "_gh_info",  BLUE),
            ("⬇ Cloner",  "_gh_clone", GREEN),
            ("🍴 Forker",  "_gh_fork",  ORANGE),
        ]:
            _b = QPushButton(_lbl)
            _b.setStyleSheet(_btn(bg="#141420", bd=_col + "88", fg=_col, hv="#1e1e30"))
            _b.clicked.connect(getattr(self, _slot))
            gh_row.addWidget(_b)

        self._gh_dest_lbl = QLabel("")
        self._gh_dest_lbl.setStyleSheet("color:#555; font-size:10px;")
        gh_row.addStretch()
        gh_row.addWidget(self._gh_dest_lbl)
        root_lo.addLayout(gh_row)

        # Splitter principal
        splitter = QSplitter()
        splitter.setHandleWidth(3)
        splitter.setStyleSheet("QSplitter::handle { background:#1a1a2a; }")

        # ── Colonne gauche : fichiers + infos scan ─────────────────────────────
        left = QWidget()
        left_lo = QVBoxLayout(left)
        left_lo.setContentsMargins(0,0,4,0)
        left_lo.setSpacing(4)

        # Stats scan
        stats_grp = QGroupBox("📊 Analyse projet")
        stats_grp.setStyleSheet("QGroupBox { border:1px solid #2a2a3a; border-radius:6px;"
                                " margin-top:6px; color:#666; padding-top:4px; }")
        stats_lo = QVBoxLayout(stats_grp)
        stats_lo.setSpacing(2)
        self._stats_lbl = QLabel("—")
        self._stats_lbl.setStyleSheet("color:#888; font-size:11px;")
        self._stats_lbl.setWordWrap(True)
        stats_lo.addWidget(self._stats_lbl)

        self._libs_lbl = QLabel("Libs substituables : —")
        self._libs_lbl.setStyleSheet(f"color:{ORANGE}; font-size:11px;")
        self._libs_lbl.setWordWrap(True)
        stats_lo.addWidget(self._libs_lbl)

        self._score_bar = QProgressBar()
        self._score_bar.setRange(0, 100)
        self._score_bar.setValue(0)
        self._score_bar.setFixedHeight(8)
        self._score_bar.setStyleSheet(
            "QProgressBar { border:1px solid #222; background:#111; border-radius:3px; }"
            "QProgressBar::chunk { background:#2196f3; border-radius:2px; }"
        )
        stats_lo.addWidget(self._score_bar)
        left_lo.addWidget(stats_grp)

        # Liste fichiers
        lbl_files = QLabel("📄 Fichiers (cliquer pour sélectionner)")
        lbl_files.setStyleSheet("color:#666; font-size:10px;")
        left_lo.addWidget(lbl_files)

        self._file_list = QListWidget()
        self._file_list.setStyleSheet(
            "QListWidget { background:#0a0a0a; color:#c2c0b6; border:1px solid #222;"
            f" border-radius:4px; {MONO} font-size:11px; }}"
            "QListWidget::item:selected { background:#1e1e30; }"
        )
        self._file_list.itemClicked.connect(self._on_file_selected)
        left_lo.addWidget(self._file_list)

        splitter.addWidget(left)

        # ── Colonne droite : actions + résultats ───────────────────────────────
        right = QWidget()
        right_lo = QVBoxLayout(right)
        right_lo.setContentsMargins(4,0,0,0)
        right_lo.setSpacing(6)

        # Barre d'actions
        actions_grp = QGroupBox("⚡ Actions Nokido")
        actions_grp.setStyleSheet("QGroupBox { border:1px solid #2a2a3a; border-radius:6px;"
                                  " margin-top:6px; color:#666; padding-top:4px; }")
        act_lo = QHBoxLayout(actions_grp)
        act_lo.setSpacing(6)

        self._action_btns = {}
        for label, key, color in self.ACTIONS:
            btn = QPushButton(label)
            btn.setStyleSheet(_btn(bg="#141420", bd=color+"88", fg=color, hv="#1e1e30"))
            btn.setEnabled(False)
            btn.clicked.connect(lambda checked, k=key: self._run_action(k))
            self._action_btns[key] = btn
            act_lo.addWidget(btn)

        act_lo.addStretch()

        # Modèle
        self._model_combo = QComboBox()
        self._model_combo.addItems(self.MODELS)
        self._model_combo.setStyleSheet(
            "QComboBox { background:#141420; border:1px solid #333; border-radius:4px;"
            " color:#888; padding:3px 8px; font-size:10px; }"
        )
        self._model_combo.setFixedWidth(220)
        act_lo.addWidget(QLabel("Modèle :"))
        act_lo.addWidget(self._model_combo)

        right_lo.addWidget(actions_grp)

        # Fichier sélectionné + progress
        self._selected_lbl = QLabel("Aucun fichier sélectionné")
        self._selected_lbl.setStyleSheet("color:#555; font-size:11px;")
        right_lo.addWidget(self._selected_lbl)

        self._progress = QLabel("")
        self._progress.setStyleSheet(f"color:{BLUE}; font-size:11px;")
        right_lo.addWidget(self._progress)

        # Résultats (tabs)
        self._result_tabs = QTabWidget()
        self._result_tabs.setStyleSheet(
            "QTabWidget::pane { border:1px solid #222; }"
            "QTabBar::tab { background:#141420; color:#666; padding:4px 12px;"
            " border:1px solid #333; border-bottom:none; border-radius:3px 3px 0 0; }"
            "QTabBar::tab:selected { background:#0e1117; color:#c2c0b6; }"
        )

        # Tab Résultat
        self._result_view = QPlainTextEdit()
        self._result_view.setReadOnly(True)
        self._result_view.setStyleSheet(
            f"background:#0a0a0a; color:#c2c0b6; border:none; {MONO}"
        )
        self._result_tabs.addTab(self._result_view, "📄 Résultat")

        # Tab Diff
        self._diff_view = QTextEdit()
        self._diff_view.setReadOnly(True)
        self._diff_view.setStyleSheet(
            f"background:#080810; color:#888; border:none; {MONO} font-size:10px;"
        )
        self._result_tabs.addTab(self._diff_view, "🔀 Diff")

        # Tab Source
        self._source_view = QPlainTextEdit()
        self._source_view.setReadOnly(True)
        self._source_view.setStyleSheet(
            f"background:#050508; color:#666; border:none; {MONO} font-size:10px;"
        )
        self._result_tabs.addTab(self._source_view, "📜 Source")

        right_lo.addWidget(self._result_tabs)

        # Bouton appliquer
        apply_row = QHBoxLayout()
        self._apply_btn = QPushButton("💾  Appliquer les modifications")
        self._apply_btn.setStyleSheet(_btn(bg="#0a2a0a", bd=GREEN, fg=GREEN, hv="#0e3a0e"))
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._apply_result)
        apply_row.addWidget(self._apply_btn)
        apply_row.addStretch()
        self._save_lbl = QLabel("")
        self._save_lbl.setStyleSheet(f"color:{GREEN}; font-size:11px;")
        apply_row.addWidget(self._save_lbl)
        right_lo.addLayout(apply_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root_lo.addWidget(splitter)

        # État interne
        self._selected_file: Path | None = None
        self._last_result:   str          = ""

    # ── Sélection dossier ──────────────────────────────────────────────────────

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choisir un projet Python", str(Path.home()),
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return
        self._folder = Path(folder)
        self._folder_lbl.setText(str(self._folder))
        self._folder_lbl.setStyleSheet(f"color:{BLUE}; font-size:11px;")
        self._stats_lbl.setText("⏳ Analyse en cours...")
        self._file_list.clear()
        self._launch_scan()

    def _launch_scan(self) -> None:
        if not self._folder:
            return
        self._scan_worker = _ScanWorker(self._folder)
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.error.connect(lambda e: self._stats_lbl.setText(f"❌ {e[:80]}"))
        self._scan_worker.start()

    def _on_scan_done(self, data: dict) -> None:
        self._scan = data
        n     = data["n_files"]
        lines = data["total_lines"]
        score = data["avg_doc"]
        slow  = data["slow_libs"]

        self._stats_lbl.setText(
            f"{n} fichiers  |  {lines:,} lignes  |  "
            f"Score doc moy : {score}/100"
        )
        self._score_bar.setValue(score)
        self._score_bar.setStyleSheet(
            f"QProgressBar {{ border:1px solid #222; background:#111; border-radius:3px; }}"
            f"QProgressBar::chunk {{ background:"
            f"{'#4caf50' if score>70 else '#ff9800' if score>40 else '#f44336'};"
            f" border-radius:2px; }}"
        )

        if slow:
            libs_txt = "  ".join(f"{lib}→{t}" for lib, t in
                                  [("json","msgspec"),("requests","httpx"),("sqlite3","duckdb")]
                                  if lib in slow)
            self._libs_lbl.setText(f"⚠️  Libs substituables : {libs_txt}")
        else:
            self._libs_lbl.setText("✅ Aucune lib lente détectée")
            self._libs_lbl.setStyleSheet(f"color:{GREEN}; font-size:11px;")

        # Remplir la liste
        self._file_list.clear()
        for f, lines, doc_score in data["top_files"]:
            rel  = str(f.relative_to(self._folder)) if self._folder else f.name
            item = QListWidgetItem(f"  {rel}  ({lines}L  doc:{doc_score}%)")
            item.setData(Qt.ItemDataRole.UserRole, str(f))
            color = QColor(GREEN if doc_score > 70
                           else ORANGE if doc_score > 40
                           else RED)
            item.setForeground(color)
            self._file_list.addItem(item)

        # Activer les boutons
        for btn in self._action_btns.values():
            btn.setEnabled(True)

    # ── Sélection fichier ──────────────────────────────────────────────────────

    def _on_file_selected(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        self._selected_file = Path(path)
        self._selected_lbl.setText(f"📄 {self._selected_file.name}")
        self._selected_lbl.setStyleSheet(f"color:{BLUE}; font-size:11px;")
        # Afficher le source
        try:
            src = self._selected_file.read_text(encoding="utf-8", errors="replace")
            self._source_view.setPlainText(src)
            self._result_tabs.setCurrentIndex(2)  # Tab Source
        except Exception:
            pass

    # ── Actions ────────────────────────────────────────────────────────────────

    def _run_action(self, action: str) -> None:
        if not self._folder:
            return
        target = self._selected_file or (
            Path(self._scan["top_files"][0][0])
            if self._scan.get("top_files") else None
        )
        if not target:
            self._progress.setText("⚠️  Sélectionner un fichier d'abord")
            return

        model = self._model_combo.currentText()
        self._progress.setText(f"⏳  {action} en cours sur {target.name}...")
        self._result_view.setPlainText("Traitement...")
        self._apply_btn.setEnabled(False)
        self._save_lbl.setText("")

        # Désactiver les boutons pendant le traitement
        for btn in self._action_btns.values():
            btn.setEnabled(False)

        self._worker = _ActionWorker(action, target, self._folder, model)
        self._worker.progress.connect(lambda m: self._progress.setText(f"⏳ {m}"))
        self._worker.done.connect(self._on_action_done)
        self._worker.error.connect(self._on_action_error)
        self._worker.start()

    def _on_action_done(self, result: str, diff: str) -> None:
        self._result_view.setPlainText(result)
        self._last_result = result
        self._progress.setText("✅ Terminé")

        if diff:
            self._diff_view.setPlainText(diff)
            self._result_tabs.setCurrentIndex(1)  # Tab Diff
            self._apply_btn.setEnabled(True)
        else:
            self._result_tabs.setCurrentIndex(0)  # Tab Résultat

        for btn in self._action_btns.values():
            btn.setEnabled(True)

    def _on_action_error(self, err: str) -> None:
        self._result_view.setPlainText(f"❌ Erreur :\n{err}")
        self._progress.setText(f"❌ {err[:60]}")
        for btn in self._action_btns.values():
            btn.setEnabled(True)

    def _apply_result(self) -> None:
        """Sauvegarde le résultat dans le fichier cible."""
        if not self._selected_file or not self._last_result:
            return
        try:
            # Backup
            bk = self._selected_file.with_suffix(".py.bak")
            bk.write_bytes(self._selected_file.read_bytes())
            # Écrire
            self._selected_file.write_text(self._last_result, encoding="utf-8")
            self._save_lbl.setText(f"✅ Sauvegardé  (backup : {bk.name})")
            self._apply_btn.setEnabled(False)
        except Exception as e:
            self._save_lbl.setText(f"❌ {e}")

    # ── Actions GitHub ────────────────────────────────────────────────────────

    def _gh_run(self, mode: str) -> None:
        url = self._gh_input.text().strip()
        if not url:
            self._progress.setText("Entrer une URL ou owner/repo GitHub")
            return
        parsed = _parse_github_url(url)
        if not parsed:
            self._progress.setText("URL invalide — ex: microsoft/vscode")
            return
        owner, repo = parsed
        token = _load_github_token()
        dest  = self._folder or Path.home() / "Nokido_projects"
        dest.mkdir(parents=True, exist_ok=True)

        self._progress.setText("GitHub " + mode + " : " + owner + "/" + repo + "...")
        self._result_view.setPlainText("Connexion GitHub...")
        for btn in self._action_btns.values():
            btn.setEnabled(False)

        self._gh_worker = _GitHubWorker(mode, owner, repo, dest, token)
        self._gh_worker.progress.connect(lambda m: self._progress.setText(m))
        self._gh_worker.done.connect(self._on_gh_done)
        self._gh_worker.error.connect(self._on_gh_error)
        self._gh_worker.start()

    def _gh_info(self)  -> None: self._gh_run("info")
    def _gh_clone(self) -> None: self._gh_run("clone")
    def _gh_fork(self)  -> None: self._gh_run("fork")

    def _on_gh_done(self, info: str, local_path: str) -> None:
        self._result_view.setPlainText(info)
        self._result_tabs.setCurrentIndex(0)
        self._progress.setText("✅ Terminé")
        for btn in self._action_btns.values():
            btn.setEnabled(bool(self._folder))
        if local_path:
            self._gh_dest_lbl.setText("→ " + local_path)
            self._folder = Path(local_path)
            self._folder_lbl.setText(local_path)
            self._folder_lbl.setStyleSheet("color:#2196f3; font-size:11px;")
            self._progress.setText("✅ Prêt — lancer le scan ci-dessus")
            self._launch_scan()

    def _on_gh_error(self, err: str) -> None:
        self._result_view.setPlainText("❌ Erreur GitHub :" + err)
        self._progress.setText("❌ " + err[:60])
        for btn in self._action_btns.values():
            btn.setEnabled(bool(self._folder))

    def closeEvent(self, event) -> None:
        for attr in ["_scan_worker", "_worker"]:
            w = getattr(self, attr, None)
            if w and w.isRunning():
                w.terminate()
                w.wait(500)
        super().closeEvent(event)