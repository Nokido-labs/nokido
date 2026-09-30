"""NR — le plancher anti-spoof est TERMINAL pour une identite non prouvee.

INVARIANT : quelle que soit l'etape qui s'execute APRES lui, une identite dont
la provenance n'est pas PROUVEE ne descend jamais sous `_HEADER_FLOOR_RING`.

Ce NR ne verifie pas UNE etape : il verifie la propriete de SORTIE de
`resolve_identity` sur une matrice. C'est voulu — le defaut mesure n'etait pas
dans le plancher ni dans l'elevation pris separement, il etait dans leur
ORDRE. Un test qui n'interroge qu'une fonction ne peut pas voir ca.

DEFAUT MESURE LE 2026-09-12 :

    X-Agent-Name: CLAUDE, AUCUN jeton, connexion locale, dev-mode arme
    -> ring 1, et `via` valant toujours `header`

Le plancher etait pose (ring 4), puis `_maybe_elevate` le franchissait : il
consultait la connexion, le nom et l'armement, jamais la PROVENANCE. Le
verdict portait donc lui-meme la preuve qu'il ne devait pas accorder ce ring.

C'est la faute que ce module avait DEJA corrigee pour la borne de delegation,
en la deplacant en derniere instruction « pour que la propriete devienne
structurelle au lieu d'etre vraie par coincidence ». Le raisonnement n'avait
pas ete reporte au plancher anti-spoof — d'ou ce NR, qui juge la SORTIE et
non une etape, de sorte qu'une prochaine etape ajoutee apres coup le fasse
rougir.

PORTEE, sans la surestimer : il fallait une connexion LOCALE, un nom parmi
quatre, et dev-mode ARME par l'owner. Pas exploitable a distance. Mais un
garde qu'une etape ulterieure annule ne garde rien.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE.parent), str(RACINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

V = pytest.importorskip("nokido_agent.app.forge_videur")


@pytest.fixture
def dev(monkeypatch):
    def _poser(arme):
        monkeypatch.setattr(V, "_DEV_IS_ARMED_OVERRIDE",
                            (lambda: (arme, 999)), raising=False)
    yield _poser
    monkeypatch.setattr(V, "_DEV_IS_ARMED_OVERRIDE", None, raising=False)


@pytest.fixture
def magasin_privilegie(monkeypatch):
    """Tous les agents testes sont PRIVILEGIES au magasin.

    Sans ca, un agent deja a 4 passerait le test sans rien prouver : c'est
    justement quand le magasin accorde un ring bas que le plancher doit tenir.
    """
    monkeypatch.setattr(
        V, "_load_store",
        lambda: {a: 0 for a in V._OWNER_AGENTS} | {"AGENT_TIERS": 1},
        raising=False)


@pytest.mark.parametrize("agent", sorted(V._OWNER_AGENTS) + ["AGENT_TIERS"])
@pytest.mark.parametrize("local", [True, False])
@pytest.mark.parametrize("arme", [True, False])
def test_sans_preuve_d_identite_le_plancher_tient(dev, magasin_privilegie,
                                                  agent, local, arme):
    dev(arme)
    r = V.resolve_identity(agent, "", local=local, agent_tokens={})
    assert r["ring"] >= V._HEADER_FLOOR_RING, (
        "agent=%s local=%s dev=%s : ring %r sous le plancher %r avec "
        "via=%r. Une etape posterieure au plancher le franchit."
        % (agent, local, arme, r["ring"], V._HEADER_FLOOR_RING, r["via"]))


@pytest.mark.parametrize("agent", sorted(V._OWNER_AGENTS))
def test_controle_positif_une_identite_prouvee_garde_son_ring(dev,
                                                              magasin_privilegie,
                                                              agent):
    """Sans lui, un plancher applique a TOUT le monde passerait ci-dessus en
    detruisant l'authentification — une securite triviale qui refuse tout."""
    dev(False)
    r = V.resolve_identity(agent, "T", local=True, agent_tokens={agent: "T"})
    assert r["via"] == "token"
    assert r["ring"] == 0, (
        "une identite PROUVEE n'obtient plus le ring de son magasin : %r"
        % r["ring"])


def test_l_omission_de_la_provenance_ne_privilegie_pas():
    """Fail-closed sur l'oubli : un appelant qui ne transmet pas `via`.

    Le defaut du parametre doit valoir NON PROUVE. S'il valait « prouve », la
    prochaine refactorisation qui oublie de passer la provenance rouvrirait le
    trou en silence.
    """
    assert V._maybe_elevate("CLAUDE", 4, True) == 4, (
        "l'elevation s'applique quand la provenance est OMISE : le defaut du "
        "parametre privilegie au lieu de refuser")
    assert V._identite_prouvee("header") is False
    assert V._identite_prouvee("") is False
    assert V._identite_prouvee(None) is False
    assert V._identite_prouvee("token") is True
    assert V._identite_prouvee("delegated:PASSERELLE") is True
