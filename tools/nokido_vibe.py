"""nokido_vibe -- lanceur owner de Mistral Vibe authentifie au hub MCP sous VIBE_CLI (decision owner 2026-10-16).

Usage (PowerShell, depuis la racine du depot Nokido) :
    & "$env:USERPROFILE\\miniforge3\\python.exe" tools\\nokido_vibe.py [arguments de vibe]

Le jeton FORGE_TOKEN_VIBE_CLI est lu au coffre a CHAQUE lancement et pose dans l'environnement du SEUL processus vibe :
rien n'est ecrit sur disque ni dans l'environnement permanent, et une rotation est prise au lancement suivant (le piege
Codex -- un processus deja vivant qui garde l'ancien jeton -- ne se pose pas). La config utilisateur (~/.vibe/config.toml)
porte le serveur MCP du hub avec `api_key_env` ; la poser une fois par `tools/forge_provision_clients.py --vibe`.
L'executeur de taches, lui, parle sous VIBE_HEADLESS (jeton injecte par le harness) : deux identites, deux journaux.
"""
from __future__ import annotations

__FORGE_COLOR__ = "interface/lanceur_client : lanceur owner de Mistral Vibe authentifie au hub MCP sous VIBE_CLI"

import os
import subprocess
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parent.parent
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from nokido_agent.app.forge_cli_harness import agent_bin, jeton_mcp  # noqa: E402

JETON = "FORGE_TOKEN_VIBE_CLI"


def environnement(base=None) -> dict:
    """L'environnement du processus vibe : celui du lanceur, plus le jeton VIBE_CLI lu au coffre (s'il existe)."""
    env = dict(os.environ if base is None else base)
    env.update(jeton_mcp("vibe_cli"))
    return env


def commande(argv) -> list:
    return [agent_bin("vibe")] + list(argv)


def main(argv=None) -> int:
    env = environnement()
    if JETON not in env:
        print("[nokido_vibe] jeton VIBE_CLI introuvable au coffre : Vibe demarre SANS le hub (401 attendu)",
              file=sys.stderr)
    return subprocess.call(commande(sys.argv[1:] if argv is None else argv), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
