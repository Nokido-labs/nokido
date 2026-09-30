"""
tools/forge_cross_fs.py — Skill cross_platform_fs
=================================================
Permet de déplacer/copier des fichiers entre l'hôte Windows et les environnements isolés (Docker, WSL).
Sécurise les chemins pour éviter les corruptions.

Usage via Hub:
  hub run action=python code="from forge_cross_fs import move_to_docker; move_to_docker('source.txt', 'container:/dest/')"
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _run_shell(cmd: str) -> str:
    """Exécute une commande shell et retourne stdout."""
    res = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", cmd], capture_output=True, text=True
    , errors="replace")
    if res.returncode != 0:
        raise Exception(f"Shell error: {res.stderr}")
    return res.stdout.strip()


def copy_to_docker(src_path: str, container_dest: str) -> str:
    """
    Copie un fichier de Windows vers un container Docker.
    Format dest: 'container_name:/path/to/dest'
    """
    src = Path(src_path).resolve()
    if not src.exists():
        return f"ERROR: source path '{src_path}' does not exist."

    cmd = f"docker cp '{src}' {container_dest}"
    try:
        _run_shell(cmd)
        return f"SUCCESS: copied {src.name} to {container_dest}"
    except Exception as e:
        return f"ERROR: {e}"


def copy_from_docker(container_src: str, dest_path: str) -> str:
    """
    Copie un fichier d'un container Docker vers Windows.
    Format src: 'container_name:/path/to/src'
    """
    dest = Path(dest_path).resolve()
    cmd = f"docker cp {container_src} '{dest}'"
    try:
        _run_shell(cmd)
        return f"SUCCESS: copied {container_src} to {dest}"
    except Exception as e:
        return f"ERROR: {e}"


def copy_to_wsl(src_path: str, wsl_dest: str, distro: str = "Debian") -> str:
    """
    Copie un fichier de Windows vers WSL.
    wsl_dest: chemin absolu dans Linux (ex: /home/nokido/...)
    """
    src = Path(src_path).resolve()
    if not src.exists():
        return f"ERROR: source path '{src_path}' does not exist."

    # Utilisation du chemin réseau \\wsl$\distro\path
    wsl_base = Path(f"\\\\wsl$\\{distro}")
    target = wsl_base / wsl_dest.lstrip("/")

    try:
        if not target.parent.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        return f"SUCCESS: copied {src.name} to {distro}:{wsl_dest}"
    except Exception as e:
        return f"ERROR: {e}"


if __name__ == "__main__":
    # Test minimal si lancé en direct
    print("Cross-platform FS skill loaded.")
