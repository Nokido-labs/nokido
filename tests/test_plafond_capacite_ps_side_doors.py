"""TDD — plafond de capacite des portes laterales `ps_run` / `ps_agent`.

MESURE DU 2026-09-12 (sonde `sandbox/sonde_ps_side_doors.py`, par EFFET sur le
dispatch reel) :

    ps_run   @ ring 1  -> "SECURITY: ps_run necessite ring=0"   (handler)
    ps_run   @ ring 4  -> forbidden, "insufficient ring (got 4, max 2)" (RBAC)
    ps_agent @ ring 1  -> "SECURITY: ps_agent necessite ring=0"
    ps_agent @ ring 4  -> forbidden, idem

TROIS tables se prononcent, et elles ne disent PAS la meme chose :

    registry._TOOL_MIN_RING        : ps_run/ps_agent ABSENTS -> defaut 3
    forge_mcp_rbac._TOOL_REQUIRED_RING : 2
    le handler lui-meme            : ring == 0

Le defaut de la premiere table est PERMISSIF (3) pour un outil non declare.
Ce n'est pas une faille ici parce que deux couches plus strictes le rattrapent
— mais c'est une defense en profondeur, pas une intention. Si l'une des deux
disparait, le defaut permissif redevient la decision. C'est ce que ce fichier
verrouille.

CE QUE CES TESTS NE DEMONTRENT PAS :
  - ils ne prouvent pas qu'un CLIENT ne puisse pas obtenir ring 0. Ils prennent
    le ring en parametre, comme le dispatch le recoit du videur. La question
    « qui peut obtenir ring 0 » appartient a AUTHORITY_PROVENANCE, pas ici.
  - ils n'executent RIEN. Le controle positif utilise un `code` vide, qui
    court-circuite AVANT le garde de ring : on prouve que le handler est
    atteignable sans lui faire lancer de PowerShell.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for _p in (str(RACINE.parent), str(RACINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REG = pytest.importorskip("nokido_agent.app.forge_mcp_registry")

PORTES = (
    ("ps_run", {"code": "echo NOKIDO_PROBE"}),
    ("ps_agent", {"agent_type": "probe", "task": "echo NOKIDO_PROBE"}),
)


async def _appel(tool, args, ring):
    reg = REG.get_registry()
    return await reg.dispatch(name=tool, args=dict(args), agent="NR_TEST",
                              ring=ring)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,args", PORTES)
async def test_ring_dev_ne_franchit_pas_la_porte_laterale(tool, args):
    """ring 1 (DEV) n'est pas ring 0 : aucune elevation implicite."""
    res = str(await _appel(tool, args, ring=1))
    assert "ring=0" in res or "forbidden" in res.lower(), (
        "%s exécuté ou laissé passer au ring 1 : %r" % (tool, res[:200]))
    assert "NOKIDO_PROBE" not in res, (
        "%s a EXECUTE la charge au ring 1 — la porte laterale est ouverte" % tool)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,args", PORTES)
async def test_ring_untrusted_est_refuse_avant_le_handler(tool, args):
    """ring 4 doit tomber sur le garde d'autorisation, pas sur le handler."""
    res = await _appel(tool, args, ring=4)
    assert isinstance(res, dict) and res.get("error") == "forbidden", (
        "%s au ring 4 n'est pas refuse par le garde d'autorisation : %r"
        % (tool, res))
    assert "NOKIDO_PROBE" not in str(res)


@pytest.mark.asyncio
async def test_controle_positif_le_handler_reste_atteignable():
    """Sans lui, un dispatch qui refuserait TOUT passerait les tests ci-dessus.

    `code` vide court-circuite dans le handler AVANT le garde de ring : la
    reponse « code vide » prouve donc que l'appel a traverse l'autorisation et
    atteint le handler — sans lancer le moindre PowerShell.
    """
    res = str(await _appel("ps_run", {"code": ""}, ring=1))
    assert "vide" in res.lower(), (
        "le handler ps_run n'est pas atteignable au ring 1 meme pour un refus "
        "de forme : le plafond refuse tout, et les tests precedents ne "
        "prouvent rien. Reponse: %r" % (res[:200],))


def test_le_defaut_permissif_de_la_table_du_registre_est_dit():
    """Le defaut de `_TOOL_MIN_RING` vaut 3 pour un outil NON declare.

    Ce test ne demande pas de le changer — il refuse qu'il devienne invisible.
    Si un jour ps_run/ps_agent y sont declares, ce test le signale : la
    decision effective aura change de couche.
    """
    reg = REG.get_registry()
    for tool, _ in PORTES:
        assert tool not in reg._TOOL_MIN_RING, (
            "%s est desormais declare dans _TOOL_MIN_RING : la couche qui "
            "decide a change, re-mesurer le plafond effectif" % tool)
