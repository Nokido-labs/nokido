"""forge_security_lab_adapter.py — frontière bornée cœur ⟷ capacités offensives.

Doctrine (plan séparation offensif/défensif, 2026-08-22 ; modèle PentestGPT) : le
cœur n'appelle JAMAIS l'offensif en direct. Il passe par cet adapter, qui applique
un contrat de BORNAGE : capacité OFF par défaut (fail-closed), activée seulement par
autorisation explicite dans un cadre autorisé. Lab absent OU non autorisé = capacité
indisponible proprement, jamais une exception qui casse le cœur.

Autorisation (l'une suffit) :
  - env `NOKIDO_SECURITY_LAB` ∈ {1, true, yes}
  - fichier sentinel `sandbox/security_lab.enabled` présent

Le sous-système offensif est EXTRAIT (dépôt séparé nokido-redteam, 2026-08-22).
L'adapter le localise via `lab_path()` (env `NOKIDO_SECURITY_LAB_PATH`, fichier
`sandbox/security_lab.path`, ou défauts) et l'importe dynamiquement SI autorisé —
c'est le RACCORDEMENT installeur→lab (`configure_lab_path()` = hook installeur).
Lab absent/non configuré = capacité indisponible proprement. Les appelants
(handlers MCP) restent stables.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent
_ROOT = _APP.parent
_SENTINEL = _ROOT / "sandbox" / "security_lab.enabled"

# Emplacement du lab offensif (dépôt séparé nokido-redteam). Résolu par priorité :
#   1. env NOKIDO_SECURITY_LAB_PATH
#   2. fichier de config sandbox/security_lab.path (écrit par l'installeur/owner)
#   3. défauts connus (clone frère nokido-redteam, ou sous-dossier security_lab/)
# C'est le RACCORDEMENT : le cœur ne connaît pas le lab, il connaît ce point d'entrée.
_LAB_PATH_ENV = "NOKIDO_SECURITY_LAB_PATH"
_LAB_PATH_FILE = _ROOT / "sandbox" / "security_lab.path"
_LAB_DEFAULTS = (
    _ROOT.parent / "nokido-redteam" / "app",   # clone frère du dépôt
    _ROOT.parent / "nokido-redteam",
    _ROOT / "security_lab",                     # sous-dossier installé
)

__all__ = ["lab_authorized", "lab_path", "configure_lab_path", "run_ctf_solver",
           "get_ctf_browser_supervisor_gated", "disabled_message",
           "get_ctf_keywords", "get_ctf_system_prompt"]


def lab_authorized() -> bool:
    """Le lab offensif est-il explicitement autorisé ? Défaut : NON (fail-closed)."""
    if os.environ.get("NOKIDO_SECURITY_LAB", "").strip().lower() in ("1", "true", "yes"):
        return True
    try:
        return _SENTINEL.exists()
    except Exception:
        return False


def disabled_message(capability: str) -> str:
    return ("SECURITY_LAB_DISABLED: capacité offensive '%s' désactivée par défaut "
            "(fail-closed). L'activer dans un cadre autorisé : NOKIDO_SECURITY_LAB=1 "
            "ou créer sandbox/security_lab.enabled." % capability)


def _ensure_app_path() -> None:
    if str(_APP) not in sys.path:
        sys.path.insert(0, str(_APP))


def lab_path() -> Path | None:
    """Chemin du lab offensif (nokido-redteam) si configuré ET présent, sinon None.
    Priorité : env NOKIDO_SECURITY_LAB_PATH, puis sandbox/security_lab.path, puis défauts."""
    candidates: list[Path] = []
    env = os.environ.get(_LAB_PATH_ENV, "").strip()
    if env:
        candidates.append(Path(env))
    try:
        if _LAB_PATH_FILE.exists():
            txt = _LAB_PATH_FILE.read_text(encoding="utf-8").strip()
            if txt:
                candidates.append(Path(txt))
    except Exception:
        pass
    candidates.extend(_LAB_DEFAULTS)
    for cand in candidates:
        try:
            if cand.exists():
                return cand
        except Exception:
            continue
    return None


def configure_lab_path(path: str | Path) -> Path:
    """Persiste l'emplacement du lab — HOOK INSTALLEUR : appelé après clone de
    nokido-redteam. Écrit sandbox/security_lab.path. N'AUTORISE PAS le lab
    (fail-closed maintenu : activation = NOKIDO_SECURITY_LAB / sentinel séparés)."""
    p = Path(path).resolve()
    _LAB_PATH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LAB_PATH_FILE.write_text(str(p), encoding="utf-8")
    return p


def _ensure_lab_path() -> bool:
    """Ajoute le lab au sys.path s'il est localisable. True si un lab est branché."""
    lp = lab_path()
    if lp and str(lp) not in sys.path:
        sys.path.insert(0, str(lp))
    return lp is not None


async def run_ctf_solver(**kwargs):
    """Délègue à la boucle CTF SI autorisé, sinon message fail-closed (str)."""
    if not lab_authorized():
        return disabled_message("ctf_solver")
    _ensure_app_path()
    _ensure_lab_path()
    _m = importlib.import_module("forge_ctf_solver")  # lab optionnel (nokido-redteam)
    return await _m.solve_ctf(**kwargs)


def get_ctf_browser_supervisor_gated():
    """Superviseur navigateur CTF SI autorisé, sinon None (le handler rend fail-closed)."""
    if not lab_authorized():
        return None
    _ensure_app_path()
    _ensure_lab_path()
    _m = importlib.import_module("forge_ctf_browser_supervisor")  # lab optionnel
    return _m.get_ctf_browser_supervisor()


def get_ctf_keywords() -> frozenset:
    """Mots-clés CTF SI lab autorisé, sinon frozenset() vide (aucune détection offensive)."""
    if not lab_authorized():
        return frozenset()
    _ensure_app_path()
    _ensure_lab_path()
    try:
        return importlib.import_module("forge_ctf_prompts").CTF_KEYWORDS  # lab optionnel
    except Exception:
        return frozenset()


def get_ctf_system_prompt() -> str:
    """System prompt offensif CTF SI lab autorisé, sinon "" (prompt neutre)."""
    if not lab_authorized():
        return ""
    _ensure_app_path()
    _ensure_lab_path()
    try:
        return importlib.import_module("forge_ctf_prompts").CTF_SYSTEM_PROMPT  # lab optionnel
    except Exception:
        return ""
