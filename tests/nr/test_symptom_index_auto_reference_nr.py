"""NR — l'index des symptomes ne doit pas s'indexer LUI-MEME.

Mesure du 2026-09-20 sur `sandbox/enquetes_index.json` (188 sessions,
4 499 jetons distincts, 1 786 pieges). Les QUATRE jetons les plus frequents de
l'index sont l'index et son garde :

    226  forge_symptom_index
    203  forge_symptom_index.py
    200  hook_recon_first
    197  recon_first

826 occurrences pour un vocabulaire qui ne designe AUCUN symptome metier. La
consequence est mesurable : toute session qui travaille SUR le garde (il y en a
beaucoup, c'est un outil tres edite) devient un faux voisin de toute autre. Le
2026-09-20, `hook_recon_first` a refuse quatre appels sur `task_id`,
`relative_to`, `load_state` et `debt_hours` en citant chaque fois un piege SANS
RAPPORT -- deux fois le MEME, sur le meme appel -- pendant qu'il ne disait rien
au moment ou une duplication reelle allait etre creee.

La regle existe deja dans ce depot et elle est appliquee ailleurs : « un
instrument ne lit jamais son propre vocabulaire -- sa source, ses commentaires,
la doctrine qui le documente ». Ce NR la porte ici.

CE QUI N'EST PAS TESTE ICI, et c'est dit : le rattachement piege -> jetons se
fait par une FENETRE DE TEXTE autour de l'aveu (`_jetons(voisinage)`), donc par
PROXIMITE et non par causalite. C'est une cause distincte, non corrigee, qui
merite sa propre mesure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

fsi = pytest.importorskip("forge_symptom_index")


# Le vocabulaire de l'instrument lui-meme : son module, son fichier, son garde.
AUTO_REFERENTS = ("forge_symptom_index", "forge_symptom_index.py",
                  "hook_recon_first", "recon_first")


def test_le_vocabulaire_de_l_instrument_est_du_bruit():
    """Sans cela, toute session qui EDITE le garde devient voisine de tout."""
    manquants = [j for j in AUTO_REFERENTS if j not in fsi.BRUIT]
    assert not manquants, (
        f"{len(manquants)}/{len(AUTO_REFERENTS)} auto-referent(s) absent(s) de BRUIT : "
        f"{manquants}. Mesure du 2026-09-20 : ces jetons totalisent 826 occurrences "
        f"dans l'index et ne designent aucun symptome metier."
    )


def test_l_extraction_ecarte_reellement_ces_jetons():
    """BRUIT declare ne suffit pas : c'est `_jetons` qui doit MORDRE.

    Un durcissement non appele est une panne en attente (lecon du 2026-09-18).
    """
    txt = ("le hook_recon_first a bloque, voir forge_symptom_index.py "
           "et le verrou tree_lock du module forge_mcp_registry")
    rendus = fsi._jetons(txt)
    fuites = [j for j in AUTO_REFERENTS if j in rendus]
    assert not fuites, f"jetons auto-referents encore extraits : {fuites}"


def test_un_vrai_symptome_metier_reste_indexe():
    """Le pendant, sans lequel on « reparerait » l'index en le rendant muet.

    Ecarter le vocabulaire de l'instrument ne doit rien retirer d'autre.
    """
    txt = ("le verrou tree_lock a bloque forge_mcp_registry avec une "
           "PermissionError sur le port :8766")
    rendus = fsi._jetons(txt)
    attendus = ["tree_lock", "forge_mcp_registry"]
    perdus = [j for j in attendus if j not in rendus]
    assert not perdus, (
        f"jetons metier perdus : {perdus}. Un index qu'on rend muet pour supprimer "
        f"ses faux positifs fabrique des faux negatifs, qui sont INVISIBLES."
    )
