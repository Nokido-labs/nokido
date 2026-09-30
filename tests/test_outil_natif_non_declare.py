"""TDD — un outil NATIF non declare ne doit pas etre admis par defaut.

MESURE DU 2026-09-12. Au site d'appel du dispatch :

    _rbac_ok, _rbac_reason = check_tool_capability(name, agent, ring)

`permissive_unknown` vaut `True` par defaut, donc un nom absent de
`_TOOL_REQUIRED_RING` rend `(True, "tool_unmapped_permissive_default")` :
le garde d'AUTORISATION laisse passer ce qu'il ne connait pas. Seul
`_get_ring_needed` (defaut 2) le rattrapait ensuite — defense en profondeur,
pas declaration. 14 handlers sur 81 etaient dans ce cas (declares depuis).

POURQUOI LE DEFAUT EST DIFFICILE A VOIR : les deux couches refusent le meme
appel au ring 4, avec des MOTIFS differents. Ce test lit donc le motif, pas
seulement le refus — sans quoi il serait vert avant comme apres et ne
prouverait rien.

CE QUE CE FICHIER PROTEGE AUTANT QUE CE QU'IL EXIGE : la table RBAC gouverne
les outils NATIFS (`handle_<nom>`). Les noms ROUTES — proxies `netcfg_*`,
`docker_*`, outils forges `dyn_*`, module redteam — n'y figurent pas et n'ont
pas a y figurer : ils sont gouvernes par leur route. Fermer le defaut
permissif sans cette distinction les couperait tous. Le controle negatif
ci-dessous existe pour ca.
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
RBAC = pytest.importorskip("nokido_agent.app.forge_mcp_rbac")

FAUX_NATIF = "__nr_faux_natif__"
MARQUEUR = "__NR_HANDLER_EXECUTE__"


@pytest.fixture
def faux_handler(monkeypatch):
    """Ajoute un handler NATIF que la table RBAC ne connait pas."""
    assert FAUX_NATIF not in RBAC._TOOL_REQUIRED_RING

    async def _h(args, agent, ring):
        return MARQUEUR

    reg = REG.get_registry()
    monkeypatch.setattr(reg, "handle_" + FAUX_NATIF, _h, raising=False)
    return reg


@pytest.mark.asyncio
async def test_un_natif_non_declare_est_refuse_par_le_garde_d_autorisation(
        faux_handler):
    """LE DEFAUT : le refus doit venir du MAPPING, pas du plafond en aval."""
    res = await faux_handler.dispatch(name=FAUX_NATIF, args={},
                                      agent="NR_TEST", ring=4)
    txt = str(res)
    assert MARQUEUR not in txt, (
        "un handler natif NON DECLARE a ete EXECUTE : %r" % txt[:200])
    assert "rbac" in txt.lower() or "mapping" in txt.lower(), (
        "le refus ne vient pas du garde d'autorisation mais d'une couche aval "
        "(%r). Un outil natif inconnu doit etre refuse parce qu'il n'est pas "
        "DECLARE, pas parce qu'un plafond par defaut le rattrape." % txt[:200])


@pytest.mark.asyncio
async def test_controle_negatif_un_nom_route_n_est_pas_coupe(monkeypatch):
    """Les noms ROUTES n'ont pas de handler natif et ne sont pas dans la table.

    Ils ne doivent PAS etre refuses par le mapping, sinon fermer le defaut
    permissif coupe les proxies netcfg/docker et les outils forges `dyn_*`.
    """
    reg = REG.get_registry()
    for nom in ("dyn_outil_forge_quelconque", "netcfg_quelconque"):
        assert not hasattr(reg, "handle_" + nom), (
            "%s a un handler natif : le controle ne teste plus un nom route" % nom)
        res = str(await reg.dispatch(name=nom, args={}, agent="NR_TEST", ring=2))
        assert "not in RBAC mapping" not in res, (
            "le nom ROUTE %s est refuse par le mapping RBAC : les proxies et "
            "les outils forges seraient coupes. Reponse: %r" % (nom, res[:200]))


@pytest.mark.asyncio
async def test_controle_positif_un_natif_declare_passe_le_garde():
    """Sans lui, un correctif qui refuserait tout passerait le premier test."""
    reg = REG.get_registry()
    assert "introspect" in RBAC._TOOL_REQUIRED_RING, "fixture obsolete"
    res = str(await reg.dispatch(name="introspect", args={}, agent="NR_TEST",
                                 ring=2))
    assert "not in RBAC mapping" not in res, (
        "un outil natif DECLARE est refuse par le mapping : %r" % res[:200])
