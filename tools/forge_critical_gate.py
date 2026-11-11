"""Garde CRITICAL_FILE au COMMIT (module leger, stdlib seule).

Mesure du 7/11 : le garde ne vivait que dans `governed_edit`. Un delegue a passe outre un refus avec `Edit` natif
et son commit est passe. Ce module rend le garde executoire la ou le travail devient un commit (executeur,
pre-commit), SANS seconde liste : la liste est `CRITICAL_FILES` de `app/forge_mcp_security.py`, relue par chemin
(le registre, lui, est trop gros pour etre importe par un hook).

Derogation : colonne `allow_critical` de `tasks`, posee a l'assignation (ring <= 1 seul), relue en base. Jamais la
prose de l'agent.
"""
from __future__ import annotations

__FORGE_COLOR__ = "Immunitaire (firewall/garde)/gate critique au commit"

import importlib.util
import sqlite3
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SECURITE = _ROOT / "app" / "forge_mcp_security.py"


def liste_critique() -> frozenset:
    """La liste UNIQUE : `CRITICAL_FILES` du module de securite. Illisible -> frozenset() (le garde ne casse
    jamais un commit)."""
    try:
        spec = importlib.util.spec_from_file_location("_forge_mcp_security_critique", str(_SECURITE))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return frozenset(mod.CRITICAL_FILES)
    except Exception:  # noqa: BLE001
        return frozenset()


def fichiers_critiques(chemins) -> list:
    """Sous-ensemble de `chemins` (relatifs au depot) qui est critique : egalite ou suffixe a frontiere de
    dossier (`x/app/forge_rbac.py` oui, `monapp/forge_rbac.py` non)."""
    crit = {c.replace("\\", "/") for c in liste_critique()}
    out = []
    for p in chemins or ():
        n = str(p).replace("\\", "/")
        if n.startswith("./"):
            n = n[2:]
        if any(n == c or n.endswith("/" + c) for c in crit):
            out.append(str(p))
    return out


def derogation_en_base(task_id, db_path) -> bool:
    """True si la tache porte `allow_critical=1` ET a ete assignee par un ring <= 1 (`from_ring`). Colonne,
    ligne ou base absente/illisible -> False (fail-closed)."""
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % Path(db_path).as_posix(), uri=True, timeout=10)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
            if "allow_critical" not in cols or "from_ring" not in cols:
                return False
            row = conn.execute("SELECT allow_critical, from_ring FROM tasks WHERE id=?", (str(task_id),)).fetchone()
        finally:
            conn.close()
        if not row or str(row[0]).strip().lower() not in ("1", "true"):
            return False
        return row[1] is not None and int(row[1]) <= 1
    except Exception:  # noqa: BLE001
        return False


def refus(critiques) -> str:
    return ("[CRITICAL_FILE REFUSE] fichier(s) critique(s) sans derogation : %s -- travail CONSERVE dans le "
            "worktree, non committe. Derogation = champ allow_critical de `task assign` (ring <= 1)."
            % ", ".join(critiques[:8]))
