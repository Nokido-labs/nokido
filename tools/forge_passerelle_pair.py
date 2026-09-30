"""forge_passerelle_pair.py - habilitations des PAIRS cloud (claude.ai, ChatGPT) du connecteur.

POURQUOI UN MODULE, ET PAS UNE CONSTANTE DANS LE PONT GITHUB. L'autorite OAuth
(`forge_bridge_oauth`) charge UNE passerelle par processus et lui emprunte
`forger_capacite`, `_lire_capacite`, `AUDIENCE`, `SCOPE` et `DEPOTS_AUTORISES`. Le pont GitHub
porte les valeurs d'une lecture de depot. Les pairs ont une autre audience, une autre portee,
une autre ressource -- et tournent dans un autre processus, donc avec une autre clef de
signature (`NOKIDO_BRIDGE_CAPABILITY_KEY` posee par leur propre lanceur).

CE QUI N'EST PAS RECOPIE. Le sceau, l'expiration, la revocation et le rejeu viennent de
`forge_github_bridge.lire_capacite`, parametree precisement pour qu'une autre passerelle n'ait
pas a les reimplementer (« la plus permissive des deux finit toujours par faire loi »).

Une habilitation de pair est refusee par le pont GitHub, et inversement : l'audience differe.
NR : tests/nr/test_oauth_par_passerelle_nr.py.
"""
from __future__ import annotations

__FORGE_COLOR__ = "membrane/passerelle-pair : habilitations des pairs cloud, mecanique du pont"

import importlib.util
import pathlib

_CHEMIN_GITHUB = pathlib.Path(__file__).resolve().parent / "forge_github_bridge.py"


def _charger_mecanique():
    """Le pont GitHub, charge PAR SON CHEMIN sous un nom propre (jamais un homonyme importe)."""
    spec = importlib.util.spec_from_file_location("forge_github_bridge_pour_pair", _CHEMIN_GITHUB)
    if spec is None or spec.loader is None:
        raise SystemExit("mecanique d'habilitation illisible : %s" % _CHEMIN_GITHUB)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MECANIQUE = _charger_mecanique()

AUDIENCE = "nokido-pair"
SCOPE = "pair:collaborer"
RESSOURCE = "nokido:pair"
# Nom impose par `forge_bridge_oauth.depot_unique` : ici une RESSOURCE, pas un depot GitHub.
DEPOTS_AUTORISES = frozenset({RESSOURCE})

forger_capacite = _MECANIQUE.forger_capacite
revoquees = _MECANIQUE.revoquees


def _lire_capacite(jeton) -> tuple:
    """(charge, None) ou (None, motif) -- la verification du pont, avec les valeurs des pairs."""
    return _MECANIQUE.lire_capacite(jeton, audience=AUDIENCE, portees=(SCOPE,),
                                    ressources=DEPOTS_AUTORISES)
