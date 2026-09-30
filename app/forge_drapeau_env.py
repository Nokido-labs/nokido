"""Lire un drapeau booleen d'environnement — une seule fois pour le corps.

__FORGE_COLOR__ = "regulation/expression-genique"

CINQ modules faisaient exactement ce geste, chacun avec sa copie :
`forge_authz_shadow`, `forge_intention_gate`, `forge_proposal_applier`,
`forge_ensure_service`, `forge_openai_proxy`. Le cliquet de duplication l'a
signale le 2026-09-02 sur le couple authz_shadow / intention_gate, et il avait
raison : ce n'etait pas une ressemblance de surface, c'etait le meme calcul.

Ce que la primitive rend UNIFORME, et qui divergeait deja d'une copie a
l'autre :

  * le vocabulaire du vrai — `1`, `true`, `on`, `yes` ;
  * la normalisation — `strip()` puis `lower()` ;
  * et surtout le comportement quand la variable est ABSENTE. Les copies
    encodaient leur defaut dans le second argument de `os.environ.get`, si
    bien qu'une variable posee mais VIDE (`SET X=`) ne se distinguait pas
    d'une variable absente. Ici, une valeur vide vaut « non declaree », donc
    le defaut du module s'applique — et `declare()` permet de savoir lequel
    des deux cas on a, parce qu'un drapeau qu'on croit pose et qui ne l'est
    pas est exactement le genre de garde qui dort sans le dire.

Ce module ne connait aucun drapeau : ce sont les modules qui declarent le
LEUR, avec leur defaut. Centraliser la lecture ne veut pas dire centraliser
la politique.
"""

from __future__ import annotations

import os
from typing import Optional

__all__ = ["VRAI", "FAUX", "actif", "declare", "etat"]

VRAI = frozenset({"1", "true", "on", "yes", "oui"})
FAUX = frozenset({"0", "false", "off", "no", "non"})


def declare(nom: str) -> bool:
    """Le drapeau est-il POSE (present et non vide) ?

    Sert au diagnostic : « le garde est inactif » et « le garde n'a jamais ete
    configure » n'appellent pas le meme remede.
    """
    brut = os.environ.get(nom)
    return brut is not None and bool(brut.strip())


def actif(nom: str, defaut: bool = False) -> bool:
    """Valeur du drapeau, `defaut` s'il n'est pas declare.

    Une valeur declaree mais NON RECONNUE ne vaut pas « faux » : elle vaut le
    defaut du module. Traiter `LAFORGE_X=maybe` comme un `off` ferait passer
    une faute de frappe pour une desactivation volontaire, et la difference ne
    se verrait nulle part.
    """
    brut = os.environ.get(nom)
    if brut is None:
        return defaut
    valeur = brut.strip().lower()
    if not valeur:
        return defaut
    if valeur in VRAI:
        return True
    if valeur in FAUX:
        return False
    return defaut


def etat(nom: str, defaut: bool = False) -> str:
    """Trois etats lisibles : ACTIF / INACTIF / NON_DECLARE.

    `NON_DECLARE` n'est pas `INACTIF` : le premier dit que personne n'a
    tranche, le second qu'on a tranche contre.
    """
    if not declare(nom):
        return "NON_DECLARE"
    return "ACTIF" if actif(nom, defaut) else "INACTIF"
