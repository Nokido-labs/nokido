"""NR — tout outil NATIF doit etre DECLARE, jamais admis par defaut.

INVARIANT : la surface `handle_<nom>` du registre et la table
`forge_mcp_rbac._TOOL_REQUIRED_RING` ne divergent pas. Un handler qui nait
sans declaration retombe dans le defaut permissif du garde d'autorisation.

MESURE DU 2026-09-12 : 81 handlers, 71 declares, **14 hors table** — dont
`governed_edit` (ecriture), `agy_run` (execution) et `agy_config` (ecriture).
Ils n'etaient pas « refuses par defaut » mais AUTORISES
(`tool_unmapped_permissive_default`) ; seul le plafond par defaut de
`_get_ring_needed` (2) les rattrapait. Une defense en profondeur n'est pas une
declaration : elle tient tant que la couche qui rattrape ne bouge pas.

C'est un CLIQUET, pas un audit : il ne dit rien de la JUSTESSE des plafonds
declares — seulement qu'aucun outil natif n'echappe a la declaration. Le
plafond juste est une question d'effet, et elle se tranche ailleurs.

CE QUE CE NR NE DEMONTRE PAS :
  - il ne couvre pas les noms ROUTES (proxies `netcfg_*`/`docker_*`, outils
    forges `dyn_*`, module redteam) : ils n'ont pas de handler natif et sont
    gouvernes par leur route. Les exiger ici couperait ces routes — le
    controle negatif ci-dessous l'interdit explicitement.
  - il n'atteste rien du hub VIVANT : le registre est importe dans le
    processus de test.
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
RBAC = pytest.importorskip("nokido_agent.app.forge_mcp_rbac")

RINGS_LEGAUX = (-1, 0, 1, 2, 3, 4)


def _handlers_natifs() -> set:
    reg = REG.get_registry()
    return {n[len("handle_"):] for n in dir(reg)
            if n.startswith("handle_") and callable(getattr(reg, n, None))}


def test_aucun_handler_natif_n_echappe_a_la_declaration():
    manquants = sorted(_handlers_natifs() - set(RBAC._TOOL_REQUIRED_RING))
    assert not manquants, (
        "%d handler(s) natif(s) hors de _TOOL_REQUIRED_RING : %s\n"
        "Un outil non declare est ADMIS par le defaut permissif du garde "
        "d'autorisation, pas refuse. Le declarer au plafond qui correspond a "
        "son EFFET (pas a son nom) avant de le livrer."
        % (len(manquants), manquants))


def test_les_plafonds_declares_sont_des_rings_legaux():
    """Un plafond hors de l'echelle ne veut rien dire — et peut tout ouvrir.

    Meme famille que la sentinelle `99` mesuree le meme jour : dans un
    comparateur `ring <= plafond`, une valeur hors echelle ne se lit pas.
    """
    hors = {t: r for t, r in RBAC._TOOL_REQUIRED_RING.items()
            if r not in RINGS_LEGAUX}
    assert not hors, (
        "plafond(s) hors de l'echelle des rings %s : %s" % (RINGS_LEGAUX, hors))


def test_controle_negatif_les_noms_routes_restent_hors_table():
    """Sans lui, on « completerait » la table avec des noms routes.

    Ce serait une fausse rigueur : ces noms sont produits dynamiquement
    (`dyn_<nom>` depend des outils forges existants), la liste ne pourrait
    jamais etre complete, et le garde se ferait desarmer pour bruit.
    """
    reg = REG.get_registry()
    routes = [t for t in RBAC._TOOL_REQUIRED_RING
              if t.startswith(("dyn_", "netcfg_", "exegol_", "ctf_"))]
    assert not routes, (
        "des noms ROUTES ont ete ajoutes a la table des outils natifs : %s. "
        "Leur garde est leur route, et leur liste n'est pas enumerable."
        % routes)
    # et le pendant : ces prefixes n'ont effectivement pas de handler natif
    natifs = _handlers_natifs()
    assert not [n for n in natifs if n.startswith(("dyn_", "netcfg_"))], (
        "un handler natif porte desormais un prefixe de route : la "
        "distinction natif/route sur laquelle repose le garde ne tient plus")
