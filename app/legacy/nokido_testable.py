"""
nokido_testable.py — Shim d'import robuste pour les tests Nokido
===================================================================
Extrait les classes métier de Nokido.py en se basant sur des
MARQUEURS TEXTUELS — jamais sur des numéros de lignes.

Résiste aux ajouts/suppressions de code dans Nokido.py tant que
les signatures de classes ne changent pas.

Usage :
    import nokido_testable as lf
    eng = lf.AgenticEngine(...)
    vm  = lf.VersionManager(...)
"""

import sys, os, asyncio, json, shutil, re, uuid, logging, hashlib, math
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable, Tuple, Set
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Stubs pour les modules optionnels absents en test ────────────────────────
class _Stub:
    def __getattr__(self, n):
        return _Stub()

    def __call__(self, *a, **kw):
        return _Stub()

    def __iter__(self):
        return iter([])

    def __bool__(self):
        return False


for _m in [
    "aiohttp",
    "asyncssh",
    "textual",
    "textual.app",
    "textual.widgets",
    "textual.containers",
    "textual.widget",
    "textual.reactive",
    "textual.binding",
    "textual.screen",
    "textual.events",
    "rich",
    "rich.text",
    "rich.panel",
    "rich.markup",
    "rich.table",
    "numpy",
    "faiss",
    "pyte",
    "pdfplumber",
    "fitz",
    "pypdf",
    "rank_bm25",
    "forge_agents",
    "forge_code",
    "forge_runtime",
    "forge_network",
    "predictif",
    "modeplanner",
    "scapyshark",
    "pydantic_settings",
    "prefect",
]:
    sys.modules.setdefault(_m, _Stub())  # type: ignore

# ── Localisation de Nokido.py ────────────────────────────────────────────────
_src_file = Path(__file__).resolve().parent / "Nokido.py"
if not _src_file.exists():
    raise FileNotFoundError(
        f"Nokido.py introuvable dans {_src_file.parent}\n"
        "Placez nokido_testable.py dans le même dossier que Nokido.py."
    )

_src_text = _src_file.read_text(encoding="utf-8")
_lines = _src_text.split("\n")


# ── Extraction par marqueur textuel ──────────────────────────────────────────
def _find_line(marker: str) -> int:
    """Retourne l'index de ligne (0-based) du premier marqueur trouvé."""
    idx = _src_text.find(marker)
    if idx == -1:
        raise RuntimeError(
            f"Marqueur introuvable dans Nokido.py : {marker!r}\nLa structure du fichier a peut-être changé."
        )
    return _src_text[:idx].count("\n")


def _next_toplevel(from_line: int) -> int:
    """
    Trouve la prochaine ligne top-level après from_line.
    Top-level = ligne non indentée qui commence par 'class ', 'def ',
    '# ===', ou un identifiant suivi de ' = ' ou '('.
    """
    for i in range(from_line + 1, len(_lines)):
        l = _lines[i]
        if not l:
            continue
        if l[0].isspace():
            continue  # indenté → corps de classe/fonction
        # Fin sur marqueur de section, nouvelle classe, ou variable globale connue
        if (
            l.startswith("class ")
            or l.startswith("# ===")
            or l.startswith("version_manager")
            or l.startswith("save_orchestrator")
        ):
            return i
    return len(_lines)


def _extract(start_marker: str, end_marker: str = None) -> str:
    """
    Extrait le bloc de code entre start_marker et end_marker (exclus).
    Si end_marker est None, utilise la prochaine définition top-level.
    """
    start = _find_line(start_marker)
    end = _find_line(end_marker) if end_marker else _next_toplevel(start)
    return "\n".join(_lines[start:end])


# ── Namespace partagé ─────────────────────────────────────────────────────────
_ns: Dict[str, Any] = {
    "__file__": str(_src_file),
    "__name__": "nokido_testable",
    # stdlib
    "asyncio": asyncio,
    "json": json,
    "shutil": shutil,
    "re": re,
    "uuid": uuid,
    "logging": logging,
    "hashlib": hashlib,
    "math": math,
    "os": os,
    "sys": sys,
    "OrderedDict": OrderedDict,
    "datetime": datetime,
    "timedelta": timedelta,
    "Optional": Optional,
    "List": List,
    "Dict": Dict,
    "Any": Any,
    "Callable": Callable,
    "Tuple": Tuple,
    "Set": Set,
    "Enum": Enum,
    "dataclass": dataclass,
    "field": field,
    "Path": Path,
    "logger": logger,
    "_ast_module": __import__("ast"),
    # stubs classes tierces utilisées dans AgenticEngine
    "ConcurrentTaskRunner": type("ConcurrentTaskRunner", (), {"__init__": lambda self, **kw: None}),
    # settings stub
    "settings": type(
        "Settings",
        (),
        {
            "ollama_model": "test-model",
            "ollama_model_default": "test-model",
            "max_concurrent_tasks": 2,
            "rag_dir": Path("/tmp/rag_test"),
            "use_rag": False,
            "ollama_url": "http://localhost:11434",
            "ollama_tags_url": "http://localhost:11434/api/tags",
            "ssh_host": "127.0.0.1",
            "ssh_port": 22,
            "ssh_user": "test",
            "private_key_path": "",
            "slack_webhook_url": "",
            "auto_switch_agent": False,
        },
    )(),
    # feature flags
    "HAS_FAISS": False,
    "HAS_BM25": False,
    "HAS_LOOPS": False,
    "HAS_SCORING": False,
    "HAS_WEB_SEARCH": False,
    "HAS_ONNX": False,
    "HAS_SNIF": False,
    "HAS_PREFECT": False,
    "HAS_SANDBOX": False,
    "HAS_DANGER_GUARD": False,
    "HAS_IDS": False,
    "HAS_PREDICTIF": False,
    "HAS_ROUTAGE": False,
    # stub RAGEngine (pour SKILL_DOMAINS)
    "RAGEngine": type(
        "RAGEngine",
        (),
        {
            "_DOMAIN_MARKERS": {
                "reseau": ["ssh", "tcp", "udp", "vlan", "routeur"],
                "securite": ["firewall", "iptables", "ssl", "cert"],
                "code": ["python", "def ", "class ", "import"],
                "docker": ["docker", "container", "image", "compose"],
                "git": ["git", "commit", "branch", "merge"],
                "general": [],
            }
        },
    ),
}


def _exec(code: str):
    exec(compile(code, str(_src_file), "exec"), _ns)


# ── Extraction et exécution dans l'ordre des dépendances ─────────────────────

# 1. Constantes MEMORY_LAYERS + ENTROPY_THRESHOLDS
_exec(_extract("MEMORY_LAYERS = {", "SKILL_DOMAINS"))

# 2. SKILL_DOMAINS (dépend de RAGEngine._DOMAIN_MARKERS)
_ns["SKILL_DOMAINS"] = list(_ns["RAGEngine"]._DOMAIN_MARKERS.keys()) + ["general"]

# 3. SkillEntry dataclass
# CodeSurgeon + helpers AST (SurgeryResult, _NodeLocator, _NodeReplacer)
_exec(_extract("@dataclass\nclass SurgeryResult:", "class ForgeSaveOrchestrator:"))

_exec(_extract("@dataclass\nclass SkillEntry:", "class AgenticEngine:"))

# 4. AgenticEngine
_exec(_extract("class AgenticEngine:", "class ForgeSaveOrchestrator:"))

# 5. ForgeSaveOrchestrator
_exec(_extract("class ForgeSaveOrchestrator:", "class VersionManager:"))

# 6. VersionManager
_exec(_extract("class VersionManager:", "version_manager    = VersionManager()"))

# ── Exports publics ───────────────────────────────────────────────────────────
MEMORY_LAYERS = _ns["MEMORY_LAYERS"]
ENTROPY_THRESHOLDS = _ns["ENTROPY_THRESHOLDS"]
SKILL_DOMAINS = _ns["SKILL_DOMAINS"]
SkillEntry = _ns["SkillEntry"]
AgenticEngine = _ns["AgenticEngine"]
ForgeSaveOrchestrator = _ns["ForgeSaveOrchestrator"]
VersionManager = _ns["VersionManager"]
CodeSurgeon = _ns["CodeSurgeon"]
SurgeryResult = _ns["SurgeryResult"]

# ── Vérification au chargement ────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Nokido : {_src_file}")
    print(f"  SkillEntry            ligne {_find_line('@dataclass') + 1}")
    print(f"  AgenticEngine         ligne {_find_line('class AgenticEngine:') + 1}")
    print(f"  ForgeSaveOrchestrator ligne {_find_line('class ForgeSaveOrchestrator:') + 1}")
    print(f"  VersionManager        ligne {_find_line('class VersionManager:') + 1}")
    print(f"  MEMORY_LAYERS         {list(MEMORY_LAYERS.keys())}")
    print("✅ Shim OK")
