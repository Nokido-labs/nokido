"""TDD — le verdict M0.1 doit porter sa propre preuve a trois roles.

`forge_effect_surface.Preuve3Roles` existe depuis le 2026-09-12 et n'est
branchee sur RIEN : un garde ecrit pour une bonne raison, dont le signal n'a
aucun emetteur. Le verdict M0.1 pouvait donc etre lu sans que rien n'indique
QUI l'a produit et QUI le certifie — alors que la reponse mesuree est : le
meme acteur, le client.

CE QUE LE VERDICT DOIT PORTER, derive et jamais declare :

    producteur   = le domaine qui peut MODIFIER les instruments de preuve
    observateur  = celui qui les EXECUTE
    verificateur = celui qui peut les CERTIFIER

PREDICAT BLOQUANT : `producteur == verificateur`. Il est PLUS PRECIS que la
regle stricte de `Preuve3Roles.auto_certifiee()` (« moins de trois acteurs
distincts »), et les deux coexistent volontairement :

  - pour une preuve d'EFFET, les trois roles doivent etre distincts : observer
    l'etat du monde et certifier la preuve sont deux actes separes ;
  - pour le verdict d'un MODELE, ce qui le vide de sens est precisement que
    l'auteur de l'instrument en soit aussi le certificateur. Un verificateur
    independant qui observe lui-meme sa mesure reste un verificateur.

Confondre les deux regles rendrait rouge une separation reelle (la fixture
ci-dessous a producteur=ROOT et verificateur=EVIDENCE : deux acteurs, mais
distincts la ou ca compte).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for _p in (str(RACINE.parent), str(RACINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TD = pytest.importorskip("nokido_agent.tools.forge_trust_domains")

CHAMPS = ("producteur", "observateur", "verificateur")


def _graphe_separe():
    """Fixture reellement separee — controle POSITIF du modele."""
    return [
        TD.Noeud("client", TD.TD_CLIENT, artefact="agent",
                 qui_peut_modifier=TD.TD_CLIENT, qui_peut_appeler=TD.TD_CLIENT,
                 qui_peut_observer=TD.TD_CLIENT, qui_peut_certifier=TD.TD_CLIENT,
                 autorites={"compte": "cpt_client", "processus": "p_client"}),
        TD.Noeud("mediateur", TD.TD_ENFORCEMENT, artefact="hors depot",
                 qui_peut_modifier=TD.TD_ROOT, qui_peut_appeler=TD.TD_CLIENT,
                 qui_peut_observer=TD.TD_EVIDENCE,
                 qui_peut_certifier=TD.TD_EVIDENCE,
                 autorites={"compte": "cpt_enf", "processus": "p_enf"}),
        TD.Noeud("verificateur", TD.TD_EVIDENCE, artefact="hors depot",
                 qui_peut_modifier=TD.TD_ROOT, qui_peut_appeler=TD.TD_ROOT,
                 qui_peut_observer=TD.TD_EVIDENCE,
                 qui_peut_certifier=TD.TD_EVIDENCE,
                 autorites={"compte": "cpt_evi", "processus": "p_evi"}),
        TD.Noeud("racine", TD.TD_ROOT, artefact="hors depot, hors portee client",
                 qui_peut_modifier=TD.TD_ROOT, qui_peut_appeler=TD.TD_ROOT,
                 qui_peut_observer=TD.TD_ROOT, qui_peut_certifier=TD.TD_ROOT,
                 autorites={"compte": "cpt_root", "processus": "p_root"}),
    ]


def test_le_verdict_porte_sa_preuve_a_trois_roles():
    r = TD.verdict_m01()
    assert "preuve" in r, (
        "le verdict M0.1 ne porte pas sa propre preuve : rien n'indique QUI "
        "l'a produit et QUI le certifie")
    p = r["preuve"]
    for champ in CHAMPS:
        assert champ in p and p[champ], "role %r absent de la preuve" % champ
    assert "producteur_est_verificateur" in p


def test_sur_le_poste_reel_l_auteur_est_aussi_le_certificateur():
    """LE FAIT MESURE : les instruments sont ecrits par ce qu'ils jugent."""
    p = TD.verdict_m01()["preuve"]
    assert p["producteur_est_verificateur"] is True, (
        "la preuve du poste reel se declare independante alors que les "
        "instruments M0/M0.1, les NR et ci_local.py sont tous modifiables par "
        "le client : %r" % (p,))
    assert p["producteur"] == TD.TD_CLIENT


def test_une_preuve_auto_certifiee_interdit_la_separation_prouvee():
    """LES DENTS. Sans ca, la preuve serait un ornement du rapport.

    On part de la fixture SEPAREE (qui atteint SEPARATION_PROUVEE) et on rend
    l'instrument de preuve modifiable par son propre domaine : le verdict doit
    retomber, meme si toutes les autres dimensions restent bonnes.
    """
    g = _graphe_separe()
    avant = TD.verdict_m01(g)["verdict"]
    assert avant == "SEPARATION_PROUVEE", (
        "la fixture separee n'atteint plus le verdict favorable (%r) : le "
        "controle positif est casse, le test suivant ne prouverait rien" % avant)

    g[2].qui_peut_modifier = TD.TD_EVIDENCE  # l'auteur devient le certificateur
    apres = TD.verdict_m01(g)
    assert apres["verdict"] != "SEPARATION_PROUVEE", (
        "une preuve auto-certifiee laisse encore passer SEPARATION_PROUVEE")
    assert apres["preuve"]["producteur_est_verificateur"] is True


def test_controle_positif_une_preuve_independante_ne_bloque_pas():
    """Symetrique : le predicat ne doit pas refuser une separation reelle."""
    r = TD.verdict_m01(_graphe_separe())
    assert r["preuve"]["producteur_est_verificateur"] is False, (
        "producteur=%r verificateur=%r juges identiques a tort"
        % (r["preuve"]["producteur"], r["preuve"]["verificateur"]))
    assert r["verdict"] == "SEPARATION_PROUVEE"
