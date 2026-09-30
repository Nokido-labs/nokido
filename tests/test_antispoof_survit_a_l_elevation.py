"""TDD — l'elevation dev-mode ne doit pas franchir le plancher anti-spoof.

MESURE DU 2026-09-12, par appel direct a `forge_videur.resolve_identity` :

    header NON authentifie, DEV non arme            -> ring 4   via=header
    header NON authentifie, DEV ARME                -> ring 1   via=header
    header NON authentifie, DEV arme, NON local     -> ring 4   via=header
    header NON authentifie, hors allowlist, DEV arme-> ring 4   via=header

La deuxieme ligne est le defaut. `X-Agent-Name: CLAUDE` sans le moindre jeton
obtient le ring DEV des que l'owner arme dev-mode — et `via` vaut toujours
`header`, c'est-a-dire « identite jamais authentifiee ». Le verdict porte donc
en lui-meme la preuve qu'il ne devrait pas accorder ce ring.

CAUSE : l'ordre. `resolve_identity` pose le plancher anti-spoof
(`via == "header"` -> `_HEADER_FLOOR_RING`), PUIS appelle `_maybe_elevate`,
qui ne consulte que trois conditions — connexion locale, nom dans une
allowlist de quatre entrees, dev arme — et jamais la PROVENANCE de l'identite.

C'est la faute que l'auteur avait DEJA trouvee et corrigee pour la borne de
delegation : elle etait posee avant `_maybe_elevate`, et le commentaire du
module explique qu'elle a ete deplacee en DERNIERE instruction pour que la
propriete devienne structurelle « au lieu d'etre vraie par coincidence ». Le
meme raisonnement n'a pas ete reporte au plancher anti-spoof.

PORTEE REELLE, sans la surestimer : il faut une connexion LOCALE, un nom parmi
quatre, et dev-mode ARME par l'owner. Ce n'est pas exploitable a distance, et
l'armement est un geste owner. Mais c'est exactement la classe que le plancher
existe pour fermer, et un garde qu'une elevation ulterieure annule ne garde
rien.

CE QUE LE CORRECTIF PRESERVE : l'elevation reste acquise a une identite
PROUVEE (token, reverse_token, master_token, delegation). Le besoin legitime —
l'owner arme dev-mode et son client voit les tools — n'est pas touche, a
condition que ce client s'authentifie. S'authentifier est precisement ce qui
distingue l'owner d'un processus local quelconque.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for _p in (str(RACINE.parent), str(RACINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

V = pytest.importorskip("nokido_agent.app.forge_videur")

AGENT = "CLAUDE"
JETON = "jeton_derive_de_test"


@pytest.fixture
def dev_arme(monkeypatch):
    monkeypatch.setattr(V, "_DEV_IS_ARMED_OVERRIDE", lambda: (True, 999),
                        raising=False)
    yield
    monkeypatch.setattr(V, "_DEV_IS_ARMED_OVERRIDE", None, raising=False)


@pytest.fixture
def magasin_ring3(monkeypatch):
    """L'agent vaut ring 3 au magasin : l'elevation a donc un effet VISIBLE.

    Sans ca, un agent deja a ring 1 rendrait le test aveugle — on ne saurait
    pas distinguer « eleve » de « deja la ».
    """
    monkeypatch.setattr(V, "_load_store", lambda: {AGENT: 3}, raising=False)


def test_un_header_non_authentifie_ne_franchit_pas_le_plancher(dev_arme,
                                                               magasin_ring3):
    """LE DEFAUT."""
    r = V.resolve_identity(AGENT, "", local=True, agent_tokens={})
    assert r["via"] == "header", "la fixture ne produit plus une identite header"
    assert r["ring"] >= V._HEADER_FLOOR_RING, (
        "identite NON authentifiee (via=%r) elevee au ring %r alors que le "
        "plancher anti-spoof vaut %r : l'elevation dev-mode annule le garde."
        % (r["via"], r["ring"], V._HEADER_FLOOR_RING))


def test_controle_positif_une_identite_PROUVEE_est_toujours_elevee(dev_arme,
                                                                   magasin_ring3):
    """Sans lui, un correctif qui supprimerait l'elevation passerait le test
    precedent en cassant le besoin legitime de l'owner."""
    r = V.resolve_identity(AGENT, JETON, local=True,
                           agent_tokens={AGENT: JETON})
    assert r["via"] == "token", "la fixture ne produit plus une identite prouvee"
    assert r["ring"] == V._RING_DEV, (
        "identite PROUVEE non elevee malgre dev arme : ring %r. Le correctif "
        "a coupe l'usage legitime au lieu de fermer l'usurpation." % r["ring"])


def test_controle_negatif_sans_dev_rien_ne_bouge(magasin_ring3):
    """Dev non arme : ni elevation, ni effet de bord du correctif."""
    r = V.resolve_identity(AGENT, JETON, local=True,
                           agent_tokens={AGENT: JETON})
    assert r["ring"] == 3, (
        "le ring du magasin n'est plus rendu tel quel sans dev-mode : %r"
        % r["ring"])


def test_controle_negatif_un_agent_hors_allowlist_reste_intouche(dev_arme):
    r = V.resolve_identity("AGENT_QUELCONQUE_XYZ", "", local=True,
                           agent_tokens={})
    assert r["ring"] >= V._HEADER_FLOOR_RING
