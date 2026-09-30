# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_boot
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)
"""
forge_boot.py — Boot léger et MCP-safe (v16.5)
===============================================
RÈGLE ABSOLUE : aucun import lourd ici.
  ✅ forge_settings, forge_task_bus, forge_timecode, forge_dispatch
  ❌ forge_rag_engine, forge_orchestrator, torch, transformers, onnx

Les modules lourds sont initialisés dans on_mount() de DevOpsApp,
PAS ici. Ce fichier doit s'importer en < 100ms.

Usage :
  from forge_boot import run_boot, BootResult
  boot = run_boot()          # léger, safe
  inject_boot_globals(boot)  # expose dans __main__
"""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

# ── Chemins Nokido ────────────────────────────────────────────────────────
_ROOT_P = __import__("pathlib").Path(__file__).resolve().parent.parent
_ROOT_DIR = _ROOT_P
_APP_DIR = _ROOT_P / "app"
_DATA_DIR = _ROOT_P / "data"
_LOGS_DIR = _ROOT_P / "logs"
_DATA_DIR.mkdir(exist_ok=True)
_LOGS_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# BootResult
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class BootResult:
    ok: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    flags: Dict[str, bool] = field(default_factory=dict)
    singletons: Dict[str, Any] = field(default_factory=dict)
    settings: Any = None

    def __str__(self) -> object:
        """Str."""
        lines = [f"BootResult({'OK' if self.ok else 'FAIL'})"]
        for k, v in self.flags.items():
            lines.append(f"  {'✅' if v else '❌'} {k}")
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings:
            lines.append(f"  WARN:  {w}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Boot léger
# ─────────────────────────────────────────────────────────────────────────────


def run_boot() -> BootResult:
    """
    Boot minimal :
      1. Ajoute app/ au sys.path
      2. Charge forge_settings + .env
      3. Crée settings
      4. Vérifie DB
      5. Importe les modules LÉGERS seulement
    Tout le reste (RAG, orchestrateur, SSH) se fait dans on_mount().
    """
    r = BootResult()

    # ── 1. sys.path ──────────────────────────────────────────────────────────
    app_dir = Path(__file__).resolve().parent
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))

    # ── 2. forge_settings + .env ─────────────────────────────────────────────
    try:
        from nokido_agent.app.forge_settings import (
            _load_env_file,
            create_settings,
        )

        _load_env_file()
        r.settings = create_settings()
        r.singletons["settings"] = r.settings
        r.flags["settings"] = True
    except Exception as e:
        r.ok = False
        r.errors.append(f"settings: {e}")
        r.flags["settings"] = False
        return r  # Fatal

    # ── 3. DB SQLite (lecture seule) ─────────────────────────────────────────
    try:
        import sqlite3
        from nokido_agent.app.forge_settings import _ROOT_DIR as _rd

        db = _rd / "RAG" / "embeddings.db"
        if db.exists():
            con = sqlite3.connect(str(db))
            con.execute("PRAGMA journal_mode=WAL")
            con.close()
            r.flags["db"] = True
        else:
            r.flags["db"] = False
            r.warnings.append("embeddings.db absent")
    except Exception as e:
        r.flags["db"] = False
        r.warnings.append(f"db: {e}")

    # ── 4. Modules légers seulement ──────────────────────────────────────────
    LIGHT_MODULES = [
        "forge_dispatch",
        "forge_handlers",
        "forge_task_bus",
        "forge_timecode",
        "forge_settings",
    ]
    for mod in LIGHT_MODULES:
        try:
            __import__(mod)
            r.flags[f"mod_{mod}"] = True
        except Exception as e:
            r.flags[f"mod_{mod}"] = False
            r.warnings.append(f"{mod}: {e}")

    # ── 5. SSH Manager (léger — pas asyncssh) ────────────────────────────────
    try:
        from nokido_agent.app.forge_ssh import SSHManager

        r.singletons["ssh_manager"] = SSHManager()
        r.flags["ssh_manager"] = True
    except Exception as e:
        r.flags["ssh_manager"] = False
        r.warnings.append(f"ssh_manager: {e}")

    logger.info(f"[boot] {len(r.errors)} err / {len(r.warnings)} warn")
    return r


# ─────────────────────────────────────────────────────────────────────────────
# Injection globals
# ─────────────────────────────────────────────────────────────────────────────


def inject_boot_globals(boot: BootResult, module_name: str = "__main__") -> None:
    """Expose les singletons dans sys.modules[module_name] pour _g()."""
    mod = sys.modules.get(module_name)
    if mod is None:
        return
    for name, obj in boot.singletons.items():
        setattr(mod, name, obj)
    for name, val in boot.flags.items():
        setattr(mod, name, val)
    if boot.settings:
        mod.settings = boot.settings


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_boot())
