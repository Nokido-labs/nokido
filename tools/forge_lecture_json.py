# -*- coding: utf-8 -*-
"""Lecture d'un JSON en TROIS etats — LU / ABSENT / ILLISIBLE.

__FORGE_COLOR__ = "qualite/build : lecture de fichier a trois etats, partagee par les passeurs"

POURQUOI CE MODULE EXISTE (2026-09-09). Les deux passeurs d'inscription --
`forge_vitalite_inscrire` et `forge_generation_inscrire` -- portaient la MEME
fonction `_lire`, recopiee de l'un a l'autre : 52 noeuds identiques, que le cliquet
de clones a vus des le premier push (« CLIQUET ROMPU — tools/forge_generation_
inscrire.py | tools/forge_vitalite_inscrire.py »). Le garde avait raison, et le
remede n'etait pas de regeler son socle : suivre un patron ne veut pas dire le
RECOPIER. On corrige le diagnostic, on ne desarme jamais le garde.

L'INVARIANT PORTE ICI. Un fichier ABSENT et un fichier ILLISIBLE ne sont pas le meme
etat, et aucun des deux ne vaut « vide ». Un lecteur qui rend `{}` pour les deux
fabrique des faux negatifs indetectables : c'est la premiere ligne de la constitution
semantique du corps (`UNKNOWN` != `NO`). Consequence directe chez les appelants : on
n'ecrase jamais un fichier qu'on n'a pas su lire, parce qu'on ne sait pas ce qu'on
detruirait.
"""

from __future__ import annotations

import json
from pathlib import Path

LU = "LU"
ABSENT = "ABSENT"


def lire(chemin) -> tuple:
    """Rend (donnees, etat).

    etat vaut `LU`, `ABSENT`, ou `ILLISIBLE (<TypeErreur>)` -- le TYPE est dans
    l'etat parce qu'un echec qui ne se nomme pas doit etre re-instruit a chaque fois.
    """
    p = Path(chemin)
    if not p.exists():
        return {}, ABSENT
    try:
        return json.loads(p.read_text(encoding="utf-8")), LU
    except (OSError, ValueError) as e:
        return {}, "ILLISIBLE (%s)" % type(e).__name__
