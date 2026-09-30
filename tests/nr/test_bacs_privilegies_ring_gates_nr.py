"""NR — tout bac PRIVILEGIE est garde par un ring, et le refus le nomme.

INVARIANT : un `sandbox` qui mene a un executeur plus privilegie que le compte
du bac par defaut doit borner QUI peut l'emprunter. Une attestation, un
drapeau ou un mode ne suffisent pas : ils disent QUE la capacite est ouverte,
jamais A QUI.

DEFAUT MESURE LE 2026-09-12 : `ps_clm` — qui ecrit le code du client dans
`.run_tmp/ps_nokido_*.ps1` puis l'execute sous `NT AUTHORITY\\Systeme` — ne
consultait AUCUN ring. Seule l'attestation DEV le gardait, et elle est
GLOBALE : une fois armee par l'owner, tout appelant atteignant le handler
obtenait SYSTEM, or `run` est plafonne a 2 par la table RBAC. Pendant ce temps
`console`, qui ne donne que la session UTILISATEUR, etait garde ring-0
default-deny. Le garde etait inverse par rapport au privilege accorde.

ARBITRAGE OWNER RESTE OUVERT, et ce NR ne le tranche pas : `console` exige
ring 0, `ps_clm` exige ring 1. La monotonie stricte « plus de privilege =>
plancher au moins aussi strict » n'est donc PAS respectee. Le plancher de
`ps_clm` a ete pose a 1 pour ne pas couper le canal documente de lecture du
profil owner depuis un client DEV. Affirmer ici la monotonie rendrait ce NR
rouge sur un choix assume — un garde qu'on doit desarmer aussitot ne garde
rien. Ce qui EST verrouille : l'existence d'un plancher, pas sa valeur.

N'EXECUTE RIEN : les trois cas sont des refus.
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

MARQUEUR = "NOKIDO_NR_CHARGE"

#: (bac, ring a tester, ce que le bac accorde) — le ring choisi est au-dessus
#: du plancher mesure, de sorte que le refus doit venir du RING.
BACS_PRIVILEGIES = (
    ("ps_clm", 2, "NT AUTHORITY\\Systeme"),
    ("console", 1, "session interactive de l'owner"),
)


async def _run(bac, ring):
    reg = REG.get_registry()
    return await reg.dispatch(
        name="run",
        args={"action": "shell", "code": "echo " + MARQUEUR, "sandbox": bac},
        agent="NR_TEST", ring=ring)


@pytest.mark.asyncio
@pytest.mark.parametrize("bac,ring,accorde", BACS_PRIVILEGIES)
async def test_un_bac_privilegie_a_un_plancher_de_ring(bac, ring, accorde):
    res = str(await _run(bac, ring))
    assert MARQUEUR not in res, (
        "bac %s : la charge a ete EXECUTEE au ring %d (accorde : %s)"
        % (bac, ring, accorde))
    assert "ring" in res.lower(), (
        "bac %s (accorde : %s) refuse au ring %d SANS nommer le ring : le "
        "refus vient d'un autre garde, donc rien ne borne QUI peut emprunter "
        "ce bac. Reponse: %r" % (bac, accorde, ring, res[:240]))


@pytest.mark.asyncio
async def test_controle_negatif_la_borne_ne_deborde_pas_sur_les_autres_bacs():
    """Sans lui, un refus global sur `run` passerait le test precedent.

    Un `sandbox` hors contrat doit etre refuse par le garde de VALIDATION, et
    ce refus ne doit pas parler de ring : sinon la borne des bacs privilegies
    a contamine toute la surface du tool.
    """
    reg = REG.get_registry()
    res = str(await reg.dispatch(
        name="run",
        args={"action": "shell", "code": "echo " + MARQUEUR,
              "sandbox": "__bac_hors_contrat_nr__"},
        agent="NR_TEST", ring=1))
    assert MARQUEUR not in res
    assert "ring" not in res.lower(), (
        "un bac hors contrat est refuse POUR MOTIF DE RING : la borne des bacs "
        "privilegies deborde sur toute la surface de `run`. Reponse: %r"
        % res[:240])
