# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_163726_astdoccerb
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0 docs
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_version.py — Source de vérité unique pour la version Nokido
===================================================================
Zéro dépendance circulaire. Importable partout sans risque.

Principe :
  - La version canonique vit dans app/Nokido.py : __version__ = "x.y.z"
  - Ce module la lit UNE SEULE FOIS au démarrage (cache module-level)
  - Tous les accès passent par get() — jamais directement via version_manager

API publique :
  from forge_version import get, label, semver

  get()                   → "0.13.0"
  label()                 → "v0.13.0"
  semver()                → (0, 13, 0)
  get_from_manager(vm)    → version depuis VersionManager ou fallback
  display(vm=None)        → "v0.13.0" depuis manager si dispo, sinon get()

Règle d'or : n'appelez JAMAIS version_manager.current_version directement.
Utilisez display(version_manager) — il protège contre None et les exceptions.
"""


import logging
import re
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ── Constante — modifiée uniquement par version_bump.py ───────────────────────
# C'est ici que la version est lue au boot, puis cachée.
_LAFORGE_PY = Path(__file__).resolve().parent / "Nokido.py"
_VERSION_RE = re.compile(r'^__version__\s*=\s*["\'](\d+\.\d+(?:\.\d+)?)["\']', re.MULTILINE)

# Fallback si lecture impossible — doit correspondre à __version__ dans Nokido.py
_FALLBACK = "0.13.0"

# Cache module-level — chargé une seule fois
_cached: Optional[str] = None


def _read_from_file() -> str:
    """Lit __version__ depuis Nokido.py. Silencieux en cas d'erreur."""
    try:
        src = _LAFORGE_PY.read_text(encoding="utf-8", errors="replace")
        m = _VERSION_RE.search(src)
        if m:
            return m.group(1)
    except Exception as e:
        logger.debug(f"[forge_version] lecture Nokido.py: {e}")
    return _FALLBACK


def _ensure_cached() -> str:
    """ensure cached."""
    global _cached
    if _cached is None:
        # Priorité 1 : __version__ importé depuis __main__ (si Nokido est lancé)
        try:
            import sys

            main = sys.modules.get("__main__") or sys.modules.get("Nokido")
            if main:
                v = getattr(main, "__version__", None)
                if v and re.match(r"^\d+\.\d+", str(v)):
                    _cached = str(v)
                    return _cached
        except Exception:
            pass
        # Priorité 2 : lecture directe du fichier
        _cached = _read_from_file()
    return _cached


def get() -> str:
    """
    Retourne la version courante sous forme de string.
    Exemple : "0.13.0"
    Toujours protégé — retourne _FALLBACK en cas d'erreur.
    """
    try:
        return _ensure_cached()
    except Exception:
        return _FALLBACK


def label() -> str:
    """
    Retourne la version préfixée pour l'affichage.
    Exemple : "v0.13.0"
    """
    return f"v{get()}"


def semver() -> Tuple[int, int, int]:
    """
    Retourne le tuple (major, minor, patch).
    Exemple : (0, 13, 0)
    Toujours 3 composantes même si __version__ n'en a que 2.
    """
    parts = get().split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return (0, 13, 0)


def get_from_manager(vm: Optional[object], fallback: Optional[str] = None) -> str:
    """
    Lit current_version depuis un VersionManager de façon protégée.
    Si vm est None ou lève une exception → retourne get() ou fallback.

    Usage :
        ver = get_from_manager(version_manager)
        # Remplace : version_manager.current_version  ← non protégé
    """
    if vm is not None:
        try:
            v = vm.current_version  # type: ignore[attr-defined]
            if v and isinstance(v, str) and re.match(r"^\d+\.\d+", v):
                return v
        except Exception as e:
            logger.debug(f"[forge_version] current_version inaccessible: {e}")
    return fallback if fallback is not None else get()


def display(vm: Optional[object] = None) -> str:
    """
    Version pour affichage TUI — préfixée "v".
    Utilise le VersionManager si disponible, sinon fallback sur get().

    Usage (remplace toutes les occurrences inconsistantes) :
        self.sub_title = f"{display(version_manager)} · {hostname}"
        # Remplace :
        #   f"v{version_manager.current_version} · {_hn}" if _hn else ...
        #   f"v{__version__}"
        #   version_manager.current_version if version_manager else __version__
    """
    return f"v{get_from_manager(vm)}"


def invalidate_cache() -> None:
    """
    Force une relecture depuis Nokido.py au prochain appel.
    À appeler après version_bump.py ou un @apply qui modifie __version__.
    """
    global _cached
    _cached = None
    logger.debug("[forge_version] cache invalidé")


# ─────────────────────────────────────────────────────────────────────────────
# Branche git + stage (alpha/beta/stable)
# ─────────────────────────────────────────────────────────────────────────────

_STAGE_MAP = {
    "main": "stable",
    "master": "stable",
    "release": "rc",
    "dev": "dev",
    "develop": "dev",
    "alpha": "alpha",
    "beta": "beta",
    "feature": "alpha",
    "fix": "alpha",
    "hotfix": "rc",
}

_branch_cache: Optional[str] = None


def branch() -> str:
    """
    Retourne la branche git courante (ex: 'main', 'dev', 'feature/x').
    Retourne '' si git indisponible ou hors repo.
    Mis en cache pour la durée du process.
    """
    global _branch_cache
    if _branch_cache is not None:
        return _branch_cache
    try:
        import subprocess

        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(_LAFORGE_PY.parent),
            capture_output=True,
            text=True,
            timeout=2,
        errors="replace")
        _branch_cache = res.stdout.strip() if res.returncode == 0 else ""
    except Exception:
        _branch_cache = ""
    return _branch_cache


def stage() -> str:
    """
    Retourne le stage déduit de la branche : alpha | beta | rc | dev | stable.
    Consulte _STAGE_MAP sur le premier segment de la branche.
    """
    br = branch().lower()
    if not br:
        return "stable"
    first = br.split("/")[0]
    for key, val in _STAGE_MAP.items():
        if first == key or first.startswith(key):
            return val
    return "dev"


def full_label(vm: Optional[object] = None, show_branch: bool = True) -> str:
    """
    Label complet pour les titres de fenêtre et widgets TUI.
    Format : 'v0.13.3 [branch] (stage)'
    Exemples :
      v0.13.3 [main] (stable)
      v0.13.3 [dev] (alpha)
      v0.13.3          ← si branche indisponible

    Usage :
      TITLE = f"⚒ La Forge {full_label()}"
      self.sub_title = full_label(version_manager)
    """
    ver = get_from_manager(vm) if vm else get()
    br = branch() if show_branch else ""
    stg = stage() if show_branch else ""

    label_parts = [f"v{ver}"]
    if br:
        label_parts.append(f"[{br}]")
    if stg and stg != "stable":  # stable = discret, pas affiché
        label_parts.append(f"({stg})")
    return " ".join(label_parts)


# ── Compatibilité directe ──────────────────────────────────────────────────────
# Permet : from forge_version import __version__
__version__ = get()
