"""TDD — `nokido_ensure_service` exige un ring TRUSTED.

MESURE DU 2026-09-13, par effet sur le dispatch reel :

    nokido_ensure_service @ ring 4, service invalide -> {'error': 'invalides'}

Le refus vient du CONTROLE DE FORMAT du handler, pas d'un garde de ring : le
gate a donc laisse passer un client UNTRUSTED jusqu'au handler, qui lance
`forge_ensure_service.py` sous LaForgeTrusted (start/stop/restart de services :
hub, docker, searxng, ollama...). Le tool est ABSENT du barème RBAC
(`permissive_default`) et route AVANT le gate central `_get_ring_needed` ; il
n'a aucun garde de ring interne. `corrigibility` le marque mutant, ce qui
applique le kill-switch/ASL mais n'est PAS un plafond de ring.

Une declaration morte disait le contraire : le barème EN BASE porte
`nokido_ensure_service` a min_ring 4 — mais cette valeur ne s'applique jamais,
le tool etant route avant le gate qui la lit. Declare permissif jamais
applique : le motif de la session.

CHOIX DU PLANCHER : ring <= 2 (TRUSTED). L'autoregulation documentee — le
client DECLARE son besoin (`nokido_ensure_service{docker|searxng...}`) — est
faite par des surfaces de ring 1 (DEV, ce client) ou 2 (TRUSTED) ; les organes
internes tournent dans le hub, hors dispatch. Ring 3 (COLLAB) et 4 (UNTRUSTED)
n'ont pas a piloter des services via un executeur trusted. Le SEUIL EXACT est
un arbitrage owner (le barème mort disait 4) ; ce qui n'est pas negociable,
c'est que l'infra mutante ne soit plus atteignable a UNTRUSTED.

N'EXECUTE RIEN : service au format invalide dans tous les cas — le pass au
ring 1/2 s'arrete au controle de format, jamais au spawn.
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

TOOL = "nokido_" + "ensure_" + "service"
ARGS = {"service": "nom invalide!!", "desired_state": "running"}  # format KO -> pas de spawn


async def _run(ring):
    reg = REG.get_registry()
    return await reg.dispatch(name=TOOL, args=dict(ARGS), agent="NR_TEST", ring=ring)


@pytest.mark.parametrize("ring", [3, 4])
@pytest.mark.asyncio
async def test_un_ring_non_trusted_ne_pilote_pas_les_services(ring):
    """LE DEFAUT : ring 3-4 atteignait un executeur TRUSTED."""
    res = str(await _run(ring))
    assert "invalides" not in res and "requis" not in res, (
        "ring %d atteint le handler ensure_service (format teste) : l'infra "
        "mutante via executeur trusted est atteignable a ce ring. %r"
        % (ring, res[:200]))
    assert "ring" in res.lower(), (
        "ring %d refuse sans motif de ring : le garde n'est pas un plafond de "
        "ring. %r" % (ring, res[:200]))


@pytest.mark.parametrize("ring", [0, 1, 2])
@pytest.mark.asyncio
async def test_controle_positif_l_autoregulation_trusted_passe_le_gate(ring):
    """Sans lui, un plancher trop haut couperait l'autoregulation documentee.

    Ring 0-2 doit FRANCHIR le plancher et s'arreter au controle de FORMAT
    (service invalide) — donc atteindre le handler sans etre refuse au ring.
    """
    res = str(await _run(ring))
    assert "invalides" in res or "requis" in res, (
        "ring %d n'atteint plus le handler ensure_service : le plancher coupe "
        "l'autoregulation legitime (le client declare son besoin a ring 1-2). "
        "%r" % (ring, res[:200]))
