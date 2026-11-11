"""forge_passerelle_hub.py - habilitations OAuth des clients MCP du HUB (:8766/mcp).

E1 du plan docs/PLAN_OAUTH_MCP_HUB_20261102.md (owner 2/11 : « le OAuth doit venir de Nokido, les clients sont
interchangeables, la version distribuable n'utilisera pas forcement Claude »).

POURQUOI UN MODULE. L'autorite OAuth unique (`forge_bridge_oauth`) charge UNE passerelle par processus
(`NOKIDO_OAUTH_PASSERELLE=forge_passerelle_hub.py`) et lui emprunte `forger_capacite`, `_lire_capacite`, `AUDIENCE`,
`SCOPE` et `DEPOTS_AUTORISES`. Le hub a son audience, sa portee et sa ressource : une habilitation du hub est refusee
par le pont GitHub et par la passerelle des pairs, et inversement.

LA RESSOURCE EST UNE URI ABSOLUE (RFC 8707 §2) : l'URL du point MCP que le client vise, celle qu'il envoie dans
`resource`. Reglable (`NOKIDO_HUB_RESSOURCE_MCP`) pour la version distribuable, jamais un nom maison.
`RESSOURCE_STRICTE` declare que l'autorite doit REFUSER une demande visant une autre ressource (`invalid_target`)
au lieu de la servir en silence ; les pairs ne l'activent pas (leur ressource est un nom, `nokido:pair`).

CE QUI N'EST PAS RECOPIE. Sceau, expiration, revocation et rejeu viennent de `forge_github_bridge.lire_capacite`,
parametree pour qu'aucune passerelle ne les reimplemente. NR : tests/nr/test_passerelle_hub_oauth_nr.py.
"""
from __future__ import annotations

__FORGE_COLOR__ = "membrane/passerelle-hub : habilitations OAuth des clients MCP du hub, mecanique du pont"

import os
import pathlib
import sys
from urllib.parse import urlsplit

if str(pathlib.Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from nokido_agent.app.forge_utils import charger_module_par_chemin  # noqa: E402

_CHEMIN_MECANIQUE = pathlib.Path(__file__).resolve().parent / "forge_github_bridge.py"
_RESSOURCE_DEFAUT = "http://127.0.0.1:8766/mcp"


def _charger_mecanique():
    """La mecanique d'habilitation, chargee PAR SON CHEMIN sous un nom propre (jamais un homonyme importe)."""
    return charger_module_par_chemin("forge_github_bridge_pour_hub", _CHEMIN_MECANIQUE)


def _ressource() -> str:
    """URI absolue du point MCP (RFC 8707 §2 : schema + autorite, sans fragment), sinon refus au chargement."""
    brut = (os.environ.get("NOKIDO_HUB_RESSOURCE_MCP") or _RESSOURCE_DEFAUT).strip()
    p = urlsplit(brut)
    if p.scheme not in ("http", "https") or not p.netloc or p.fragment:
        raise SystemExit("ressource MCP du hub refusee (URI absolue sans fragment exigee, RFC 8707) : %s" % brut)
    return brut


_MECANIQUE = _charger_mecanique()

AUDIENCE = "nokido-hub"
SCOPE = "mcp:hub"
RESSOURCE = _ressource()
# Nom impose par `forge_bridge_oauth.depot_unique` : ici une RESSOURCE (URI du point MCP), pas un depot GitHub.
DEPOTS_AUTORISES = frozenset({RESSOURCE})
RESSOURCE_STRICTE = True

forger_capacite = _MECANIQUE.forger_capacite
revoquees = _MECANIQUE.revoquees


def _lire_capacite(jeton) -> tuple:
    """(charge, None) ou (None, motif) -- la verification commune, avec les valeurs du hub."""
    return _MECANIQUE.lire_capacite(jeton, audience=AUDIENCE, portees=(SCOPE,), ressources=DEPOTS_AUTORISES)
