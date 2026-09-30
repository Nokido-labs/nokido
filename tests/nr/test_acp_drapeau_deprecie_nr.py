# -*- coding: utf-8 -*-
"""NR — le drapeau ACP se LIT dans l'aide du binaire, il ne se fige pas.

MESURE (2026-09-18). Le CLI `gemini` installe sur cette machine est en **0.51.0** et
son aide porte la ligne exacte :

    --experimental-acp   Starts the agent in ACP mode (deprecated, use --acp instead)

Or `forge_acp_client` et `forge_gemini_keeper` appelaient tous deux le drapeau
DEPRECIE, en dur. Rien ne cassait : `deprecated` n'est pas `removed`. C'est exactement
ce qui rend cette dette dangereuse — elle est invisible jusqu'au jour ou l'option
disparait, et ce jour-la le symptome sera « l'agent ne parle plus ACP », pas « une
option a ete retiree ». On cherchera la panne du mauvais cote, sur le protocole.

CE QUI EST VERROUILLE ICI :
  * le client prefere `--acp` ;
  * le keeper DEMANDE au binaire quel drapeau il comprend, au lieu de supposer ;
  * une aide illisible retombe sur l'ancien drapeau (il couvre les versions
    anterieures) — un repli documente, jamais un refus sur une version non lue.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_acp_client as CLI  # noqa: E402

KEEPER = RACINE / "tools" / "forge_gemini_keeper.py"
LEGACY = "--experimental" + "-acp"


def test_le_client_prefere_le_drapeau_courant():
    assert CLI.ACP_FLAG == "--acp"
    assert CLI.ACP_AGENTS["gemini"][1] == "--acp", CLI.ACP_AGENTS["gemini"]
    assert CLI.DEFAULT_CMD[1] == "--acp", CLI.DEFAULT_CMD


def test_l_ancien_drapeau_reste_CONNU_comme_repli():
    """On ne l'efface pas : il sert aux versions anterieures, et il documente l'histoire."""
    assert CLI.ACP_FLAG_LEGACY == LEGACY


@pytest.fixture(scope="module")
def keeper_src() -> str:
    if not KEEPER.exists():
        pytest.skip("forge_gemini_keeper.py absent de cet arbre")
    return KEEPER.read_text(encoding="utf-8", errors="replace")


def test_le_keeper_ne_fige_PLUS_le_drapeau_dans_son_Popen(keeper_src):
    """MORSURE — le site d'execution reel ne doit plus porter le drapeau en dur."""
    m = re.search(r"subprocess\.Popen\(\s*\n?\s*\[([^\]]*)\]", keeper_src)
    assert m, "le lancement du CLI est introuvable"
    assert LEGACY not in m.group(1), (
        "le drapeau deprecie est encore code en dur au lancement : %s" % m.group(1))
    assert "_acp_flag()" in m.group(1), (
        "le drapeau n'est pas resolu depuis l'aide du binaire : %s" % m.group(1))


def test_le_resolveur_du_keeper_existe_et_replie(keeper_src):
    """Trois etats : `--acp` si l'aide le montre, repli sinon, et jamais d'exception."""
    i = keeper_src.find("def _acp_flag")
    assert i > 0, "le resolveur de drapeau n'existe pas"
    # BORNE SUR LA FONCTION, pas sur un nombre de caracteres : une fenetre fixe
    # debordait sur la classe suivante et faisait echouer le test sur MON temoin.
    j = keeper_src.find("\nclass ", i)
    k = keeper_src.find("\ndef ", i + 10)
    fins = [x for x in (j, k) if x > 0]
    corps = keeper_src[i:min(fins)] if fins else keeper_src[i:]
    assert '"--acp" in h' in corps, "l'aide reelle n'est pas consultee"
    # On juge le DERNIER `return` de la fonction, pas la fin du texte : les deux
    # bornes precedentes ramassaient le commentaire de separation qui suit, et
    # l'echec venait de mon temoin. Ce qui compte est l'ordre des voies de sortie.
    retours = re.findall(r"return\s+\"(--[a-z-]+)\"", corps)
    assert retours, "aucune voie de sortie lisible dans le resolveur"
    assert retours[-1] == LEGACY, (
        "la derniere voie n'est pas le repli documente : %s" % retours)
    assert "--acp" in retours, "le drapeau courant n'est jamais rendu : %s" % retours
    assert "except" in corps, "une aide illisible ferait lever le resolveur"
