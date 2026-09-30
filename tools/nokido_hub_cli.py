#!/usr/bin/env python3
"""nokido_hub_cli.py — point d'entree CONSOLE du hub, synchrone et mince.

POURQUOI CE MODULE EXISTE. Mesure du 2026-09-10, dans un venv neuf hors checkout :

    $ nokido-hub --help
    <coroutine object main at 0x...>
    RuntimeWarning: coroutine 'main' was never awaited
    rc = 1

`nokido_hub.main` est un `async def`. Un `console_script` fait
`sys.exit(cible())` : appeler une coroutine rend un OBJET, jamais un code de
retour. L'entry point etait DECLARE, s'INSTALLAIT parfaitement, et n'a JAMAIS
fonctionne — personne ne l'avait execute depuis une installation.

CE MODULE NE TOUCHE PAS AU HUB. `nokido_hub.py` est un CRITICAL_FILE de 5 800
lignes ; le corriger pour un probleme de packaging serait un risque sans rapport
avec le benefice. La couche console est mince, separee, et testable seule.

`--help` ET `--version` REPONDENT SANS IMPORTER LE HUB. Son import initialise des
registres et journalise (« registre agent_identities.json ILLISIBLE ») : demander
de l'aide ne doit rien demarrer ni rien salir. L'import n'a lieu que si l'on
demarre vraiment.
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

__FORGE_COLOR__ = "SNC/cerveau : point d entree console du hub MCP"

import sys

_AIDE = """nokido-hub — serveur MCP de Nokido (hub souverain).

Usage :
  nokido-hub              demarre le hub
  nokido-hub --help       affiche cette aide
  nokido-hub --version    affiche la version de la distribution

Le hub ecoute par defaut sur le port configure par l'environnement Nokido.
Demarrer un second hub sur un port deja pris echoue : verifier le port avant.
"""


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("nokido-agent")
    except Exception:            # noqa: BLE001 - une version illisible n'est pas une panne
        try:
            import nokido_agent
            return getattr(nokido_agent, "__version__", "inconnue")
        except Exception:        # noqa: BLE001
            return "inconnue"


def main(argv: list[str] | None = None) -> int:
    """Point d'entree SYNCHRONE. Rend un code de retour, jamais une coroutine."""
    args = list(sys.argv[1:] if argv is None else argv)

    if "--help" in args or "-h" in args:
        print(_AIDE)
        return 0
    if "--version" in args or "-V" in args:
        print(_version())
        return 0

    # Import TARDIF : il initialise des registres et journalise. Rien de tout
    # cela ne doit se produire pour une simple demande d'aide.
    import asyncio

    from nokido_agent.tools import nokido_hub

    return asyncio.run(nokido_hub.main()) or 0


if __name__ == "__main__":
    raise SystemExit(main())
