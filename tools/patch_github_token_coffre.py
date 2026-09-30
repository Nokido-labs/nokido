# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "immunitaire/secrets-au-coffre"
PATCH : `run action=github` lit son jeton dans le COFFRE, plus dans l'environnement.

`forge_mcp_registry.py` L4064 faisait `os.environ.get("GITHUB_TOKEN", "")`. La
doctrine impose `forge_secrets.get_secret()` — coffre DPAPI machine, puis WCM, puis
Nokido.env, puis (en dernier, avec un WARNING) l'environnement.

Ce n'est pas une coquetterie de style. Mesure du 2026-09-03 : sur un compte de
service, l'environnement est la couche la MOINS fiable du poste. Trois variables
d'environnement persistantes portaient des jetons revoques, dont une (`FORGE_BRIDGE_TOKEN`
cote Claude Desktop) a tenu le pont stdio en 401 pendant des heures alors que le
coffre ET le fichier de config portaient la bonne valeur. Lire un secret dans
`os.environ` en premier, c'est faire confiance a la couche qu'on ne rote jamais.

`forge_secrets` retombe DE TOUTE FACON sur `os.environ` en dernier recours : ce patch
ne retire aucune capacite, il remet l'ordre de priorite a l'endroit et fait passer la
lecture par la couche qui journalise.

Harnais REUTILISE : `forge_patch_muted_paths.appliquer()` (idempotence, ancre unique,
compile(), sauvegarde horodatee, relecture).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nokido_agent.tools.forge_patch_muted_paths import campagne  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "app" / "forge_mcp_registry.py"
SENTINELLE = "[github] jeton lu hors coffre"

BLOCS = [
    (r'''            token = __import__("os").environ.get("GITHUB_TOKEN", "")''',
     r'''            # Coffre d'abord (DPAPI -> WCM -> Nokido.env -> env). L'environnement
            # reste joignable en dernier recours, mais il n'est plus la PREMIERE
            # source : c'est la couche qu'aucune rotation ne met a jour.
            token = ""
            try:
                import sys as _sy

                _app = str(Path(__file__).resolve().parent)
                if _app not in _sy.path:
                    _sy.path.insert(0, _app)
                from forge_secrets import get_secret as _gs_gh

                token = (_gs_gh("GITHUB_TOKEN") or "").strip()
            except Exception as _e_gh:  # noqa: BLE001
                import logging as _lg

                _lg.getLogger("Nokido.Registry").warning(
                    "[github] jeton lu hors coffre (%s) : repli sur l'environnement, "
                    "couche qu'aucune rotation ne met a jour", type(_e_gh).__name__)
            if not token:
                token = __import__("os").environ.get("GITHUB_TOKEN", "")'''),
]


def main(argv=None) -> int:
    return campagne(CIBLE, SENTINELLE, BLOCS, suffixe="github-coffre",
                    note_finale="Le hub doit etre REDEMARRE pour charger ce code.",
                    argv=argv)


if __name__ == "__main__":
    sys.exit(main())
