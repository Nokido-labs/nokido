# -*- coding: utf-8 -*-
"""NR (owner 19/10 « docset au commit + cliquet ») : le compte de cartes de modules DERIVEES ne fait que descendre.

Mesure du 19/10 avec l'algorithme de l'organe (forge_module_cards.card_for) : 73 cartes sur 1 791 derivees -- le
post-commit mourait a l'etape SKILL.md (PermissionError) avant l'etape 4.5 depuis le 17/10 23:01 (corrige 1567769ee).
Plafond MESURE, pas zero : le post-commit est asynchrone (~2 s) et un fichier en cours d'edition derive jusqu'a son
commit ; un garde qui crie a faux se fait desarmer. Apres resorption, abaisser PLAFOND a la valeur mesuree.
`module_cards.json` vit dans sandbox/ (non versionne) : absent -> INCONNU, DIT par un skip motive, jamais un vert muet.
"""
from pathlib import Path

import pytest

from nokido_agent.tools import forge_module_cards as MC

PLAFOND = 73
ROOT = Path(MC.__file__).resolve().parents[1]


def _derivees():
    cartes = MC.load_cards() or {}
    if not cartes:
        return None
    out = []
    for c in (cartes.values() if isinstance(cartes, dict) else cartes):
        f = ROOT / str(c.get("module") or "")
        if f.is_file() and (MC.card_for(f) or {}).get("sha") != c.get("sha"):
            out.append(c.get("module"))
    return out


def test_les_cartes_derivees_ne_font_que_descendre():
    d = _derivees()
    if d is None:
        pytest.skip("INCONNU : sandbox/workspace/module_cards.json absent (artefact non versionne, worktree de CI)")
    assert len(d) <= PLAFOND, ("%d cartes derivees > plafond %d -- le post-commit ne regenere plus ? lire "
                               "sandbox/logs/post_commit.log (etape « Cartes comportementales »). Ex : %s"
                               % (len(d), PLAFOND, d[:5]))
