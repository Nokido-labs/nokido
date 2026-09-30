"""Fournit des E/S fichier tolérantes : écriture atomique via .tmp puis rename, lecture
avec retry sur PermissionError, et filtrage de chemins par motifs d'exclusion.

Entrées publiques : atomic_write, safe_read, should_ignore, scan_with_delay (rglob
précédé d'une pause de 500 ms), apply_storage_policy (surcharge STORAGE_POLICY).
Utilisé par forge_context.py, forge_agent_authority.py, hardware/idle_watchdog.py
(atomic_write) et forge_hub_client.py (safe_read).
Effets de bord : atomic_write crée <dest>.tmp et supprime la destination avant le
rename ; les retries dorment (time.sleep) ; les erreurs sont affichées par print.
"""
from __future__ import annotations

import time, fnmatch
from pathlib import Path


"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:
#FORGE:[score:80|agent:unknown|temp:0.30|risk:0.00|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:85|agent:ruff-format+fix|temp:0.00|risk:0.10|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)


# Config par defaut (surchargeabe via State ID)
STORAGE_POLICY: dict[str, any] = {
    "history_write_mode": "ATOMIC_MOVE",
    "embedding_scan_delay_ms": 500,
    "ignore_patterns": [
        "*.tmp",
        "history.json",
        "shadow_mutation/*",
        "failed_mutation/*",
        "AppData/*",
        "*/History/*",
        "WindowsApps/*",
        ".cache/*",
        "sandbox/*",
        "__pycache__/*",
    ],
    "retry_on_permission_error": True,
    "max_retries": 3,
    "retry_delay_ms": 200,
}


def should_ignore(path: str) -> bool:
    """
    Vrifie si un chemin doit tre ignor selon les patterns de la politique de stockage.

    Args:
        path (str): Chemin vrifier (absolu ou relatif).

    Returns:
        bool: True si le chemin correspond un pattern d'ignorance, False sinon.
    """
    p = Path(path)
    name = p.name
    rel_path = p.as_posix()
    return any(
        fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_path, pattern)
        for pattern in STORAGE_POLICY["ignore_patterns"]
    )


def atomic_write(dest: Path, content: str, encoding: str = "utf-8") -> bool:
    """
    Ecriture atomique via fichier temporaire + rename.
    Evite les corruptions si le process est coupe pendant l'ecriture.

    Args:
        dest (Path): Chemin du fichier destination.
        content (str): Contenu a ecrire.
        encoding (str, optional): Encodage du fichier. Par defaut "utf-8".

    Returns:
        bool: True si l'ecriture a réussi, False sinon.
    """
    dest = Path(dest)
    retries = STORAGE_POLICY["max_retries"]
    delay = STORAGE_POLICY["retry_delay_ms"] / 1000

    for attempt in range(retries):
        try:
            tmp = dest.parent / (dest.name + ".tmp")
            tmp.write_text(content, encoding=encoding)
            # ATOMIC_MOVE : rename atomique sur Windows
            if dest.exists():
                dest.unlink()
            tmp.rename(dest)
            return True
        except PermissionError:
            if not STORAGE_POLICY["retry_on_permission_error"]:
                return False
            time.sleep(delay * (attempt + 1))
        except Exception as e:
            print(f"[IO] atomic_write {dest.name}: {e}")
            return False
    return False


def safe_read(path: Path, encoding: str = "utf-8") -> str | None:
    """
    Lecture avec retry sur PermissionError.

    Args:
        path (Path): Chemin du fichier a lire.
        encoding (str, optional): Encodage du fichier. Par defaut "utf-8".

    Returns:
        str | None: Contenu du fichier ou None si une erreur s'est produite.
    """
    path = Path(path)
    retries = STORAGE_POLICY["max_retries"]
    delay = STORAGE_POLICY["retry_delay_ms"] / 1000
    for attempt in range(retries):
        try:
            return path.read_text(encoding=encoding, errors="ignore")
        except PermissionError:
            time.sleep(delay * (attempt + 1))
        except Exception:
            return None
    return None


def scan_with_delay(directory: Path, pattern: str = "*.py") -> list[Path]:
    """
    Scan de repertoire avec delai pour eviter les conflits avec l'embedding scanner (500ms par defaut).

    Args:
        directory (Path): Chemin du repertoire a scanner.
        pattern (str, optional): Pattern de fichier a rechercher. Par defaut "*.py".

    Returns:
        list[Path]: Liste des chemins correspondant au pattern.
    """
    time.sleep(STORAGE_POLICY["embedding_scan_delay_ms"] / 1000)
    return [f for f in Path(directory).rglob(pattern) if not should_ignore(str(f))]


def apply_storage_policy(policy: dict) -> None:
    """
    Met a jour la politique I/O depuis un State ID.

    Args:
        policy (dict): Politique de stockage a appliquer.
    """
    rules = policy.get("rules", {})
    for k, v in rules.items():
        if k in STORAGE_POLICY:
            STORAGE_POLICY[k] = v
            print(f"[IO] {k} = {v}")
