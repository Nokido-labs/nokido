"""nokido_codex -- lanceur owner de Codex, jeton client au coffre seul (decision owner 2026-10-25).

Usage (depuis la racine du depot Nokido) :
    & "$env:USERPROFILE\\miniforge3\\python.exe" tools\\nokido_codex.py [arguments de codex]

FORGE_TOKEN_CODEX est lu au coffre a CHAQUE lancement et pose dans l'environnement du SEUL processus enfant `codex`
(variable lue par bearer_token_env_var de la config Codex). Rien sur disque, rien dans HKCU, jamais le jeton maitre.
Coffre vide : sortie non nulle, codex n'est pas lance. Meme primitive que nokido_vibe (forge_secrets.get_secret).
"""
from __future__ import annotations

__FORGE_COLOR__ = "interface/lanceur_client : lanceur owner de Codex, jeton FORGE_TOKEN_CODEX lu au coffre seul"

import os
import subprocess
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parent.parent
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

JETON = "FORGE_TOKEN_CODEX"


def _coffre_defaut(nom: str) -> str:
    # Pas de `except` ici : un coffre ILLISIBLE n'est pas un jeton ABSENT (UNKNOWN != NO), `main` le dit.
    from nokido_agent.app.forge_secrets import get_secret
    return get_secret(nom) or ""


def _binaire() -> str:
    try:
        from nokido_agent.app.forge_cli_harness import agent_bin
        return agent_bin("codex")
    except Exception:  # noqa: BLE001
        return "codex"


def main(argv=None, coffre=None, appel=None) -> int:
    try:
        valeur = (coffre or _coffre_defaut)(JETON)
    except Exception as e:  # noqa: BLE001 -- dit, code distinct, jamais confondu avec « absent »
        print("[nokido_codex] coffre ILLISIBLE pour %s (%s) : Codex non lance" % (JETON, type(e).__name__),
              file=sys.stderr)
        return 3
    if not valeur:
        print("[nokido_codex] %s introuvable au coffre : Codex non lance (aucun repli sur le jeton maitre)" % JETON,
              file=sys.stderr)
        return 2
    env = dict(os.environ)
    env.pop("FORGE_MCP_TOKEN", None)  # jamais le jeton maitre dans l'enfant
    env[JETON] = valeur
    cmd = [_binaire()] + list(sys.argv[1:] if argv is None else argv)
    return (appel or subprocess.call)(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
