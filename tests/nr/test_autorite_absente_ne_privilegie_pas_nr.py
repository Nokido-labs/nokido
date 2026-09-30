"""NR — une autorite absente ou illisible ne privilegie JAMAIS.

INVARIANT : la fonction qui convertit une autorite STOCKEE en ring est TOTALE
(elle ne leve pas) et, sur toute entree qu'elle ne sait pas lire, elle rend le
ring le MOINS privilegie.

POURQUOI CE NR EXISTE. `from_ring` est NULL sur toute ligne de `tasks`
anterieure au 2026-09-12, et le restera pour tout producteur qui ne le
renseigne pas. La conversion la plus naturelle en Python — `int(x or 0)` —
donne alors `0`, c'est-a-dire MASTER. Le defaut ne serait pas un oubli de
garde : il serait la forme IDIOMATIQUE de la lecture.

ANGLE DISTINCT DU TDD : `tests/test_delegation_porte_l_autorite.py` verifie
des valeurs NOMMEES et l'aller-retour reel. Ce NR balaye au contraire une
large famille d'entrees quelconques, y compris celles auxquelles on ne pense
pas en ecrivant le correctif — `True`, un flottant, un grand entier, une
chaine signee. Les deux ne se remplacent pas : l'un decrit le contrat, l'autre
cherche ou il casse.

CE QU'IL NE DEMONTRE PAS : rien sur l'ATTENUATION. Transporter l'autorite du
delegant n'est pas la lui imposer — l'enfant agit toujours avec son propre
ring. Le champ `attenuation` du claim le dit en clair, et c'est pour que
personne ne lise ce NR comme la preuve d'une contrainte.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE.parent), str(RACINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REG = pytest.importorskip("nokido_agent.app.forge_mcp_registry")

MOINS_PRIVILEGIE = 4
RINGS_LEGAUX = (-1, 0, 1, 2, 3, 4)

#: entrees ILLISIBLES ou hors echelle. Aucune ne doit produire un privilege.
ORDURES = [
    None, "", " ", "\t", "None", "null", "NULL", "nan", "abc", "-", "+",
    [], {}, (), set(), object(), 3.7, -0.5, float("nan"), float("inf"),
    -2, 5, 6, 99, -99, 10 ** 12, -(10 ** 12), "0x1", "1e3", " 1 2 ",
]


@pytest.mark.parametrize("valeur", ORDURES, ids=lambda v: repr(v)[:24])
def test_une_entree_illisible_ne_donne_jamais_de_privilege(valeur):
    try:
        r = REG.ToolRegistry._ring_delegant(valeur)
    except Exception as e:  # noqa: BLE001
        pytest.fail("la conversion n'est pas TOTALE : %r leve %s. Un lecteur "
                    "entourera l'appel d'un try/except et choisira lui-meme un "
                    "defaut — le plus permissif gagnera."
                    % (valeur, type(e).__name__))
    assert r == MOINS_PRIVILEGIE, (
        "autorite illisible %r convertie en ring %r : toute valeur qu'on ne "
        "sait pas lire doit valoir le MOINS privilegie" % (valeur, r))


@pytest.mark.parametrize("ring", RINGS_LEGAUX)
def test_controle_positif_un_ring_legal_traverse_intact(ring):
    """Sans lui, une fonction qui rendrait toujours 4 passerait tout ci-dessus
    en detruisant l'information — une securite triviale qui refuse tout."""
    assert REG.ToolRegistry._ring_delegant(ring) == ring
    assert REG.ToolRegistry._ring_delegant(str(ring)) == ring


def test_l_echelle_est_declaree_au_meme_endroit_que_la_conversion():
    """Deux echelles divergentes = la plus permissive gagne en silence.

    Mesure du meme jour : trois tables d'autorisation coexistaient avec des
    plafonds differents pour le meme outil.
    """
    assert set(REG.ToolRegistry._RINGS_LEGAUX) == set(RINGS_LEGAUX), (
        "l'echelle declaree dans le registre (%s) diverge de celle que ce NR "
        "verifie (%s)" % (REG.ToolRegistry._RINGS_LEGAUX, RINGS_LEGAUX))
    assert REG.ToolRegistry._RING_LE_MOINS_PRIVILEGIE == max(RINGS_LEGAUX)
