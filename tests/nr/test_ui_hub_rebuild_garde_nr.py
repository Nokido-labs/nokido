# -*- coding: utf-8 -*-
"""NR — le garde de recompilation du hub refuse une sortie INCOHERENTE, pas seulement petite.

Ce module a ete ecrit le 2026-09-18 pour recompiler `hub-compiled.js` depuis ses sources,
parce que rien ne declenchait la compilation et qu'un correctif de design pouvait etre
ecrit, relu, commite, et rester invisible a l'ecran.

Le meme jour, il a CAUSE une regression. Ses deux controles -- reperes presents, taille
au moins 60 % de la precedente -- regardent la QUANTITE et la PRESENCE, jamais la
COHERENCE. La recompilation a donc produit un artefact volumineux, portant tous ses
reperes, dans lequel les six vues du hub etaient appelees par `window.ViewX` alors que
rien n'affecte ces proprietes : `React.createElement(undefined)` leve, les six vues
cassent, et aucun controle ne le voyait.

D'ou `_liaisons_window_rompues`, et d'ou ce fichier : un outil qui REGENERE un artefact
que personne ne sait relire a la main doit prouver que sa sortie se TIENT.

MORSURE PRINCIPALE : `test_un_composant_lu_sans_etre_pose_est_signale`.
MORSURE SYMETRIQUE : `test_aucun_nom_tronque` -- le garde a cite `HubIc`, `HubSideba` et
`HubTopba` a sa premiere execution, des noms qui n'existent pas, parce qu'un lookahead
place apres un quantificateur gourmand fait reculer le moteur d'un caractere jusqu'a
reussir. Un garde qui crie a faux se fait desarmer, et emporte les vrais avec lui.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

REB = pytest.importorskip("forge_ui_hub_rebuild")


def test_un_composant_lu_sans_etre_pose_est_signale():
    """MORSURE — c'est exactement la regression du 2026-09-18."""
    artefact = 'React.createElement(window.ViewAccueil, {a: 1});'
    # `voisins=False` : on eprouve le garde sur l'entree DONNEE. Sans ce drapeau, les
    # fichiers reels du disque blanchissent le temoin et le test ne mesure plus rien.
    assert REB._liaisons_window_rompues(artefact, voisins=False) == ["ViewAccueil"]


def test_un_composant_pose_dans_le_meme_artefact_ne_l_est_pas():
    artefact = 'window.ViewAccueil = f; React.createElement(window.ViewAccueil, null);'
    assert REB._liaisons_window_rompues(artefact, voisins=False) == []


def test_aucun_nom_tronque():
    """MORSURE SYMETRIQUE — le garde citait `HubIc` pour `HubIco`, un nom inexistant.

    Le faux positif n'est pas un detail : il a fait REFUSER un build correct, donc
    restaurer un artefact casse. Un garde trop bavard protege moins qu'il ne gene.
    """
    artefact = 'window.HubIco = a; window.HubSidebar = b; window.HubTopbar = c;'
    rompues = REB._liaisons_window_rompues(artefact)
    assert rompues == [], "faux positifs : %s" % rompues
    for tronque in ("HubIc", "HubSideba", "HubTopba"):
        assert tronque not in rompues


def test_object_assign_compte_comme_une_pose():
    """MORSURE LA PLUS IMPORTANTE DE CE FICHIER — elle vient d'un defaut REEL du garde.

    Le 2026-09-18, ce garde ne cherchait que `window.X =`. Le bundle expose ses vues par
    `Object.assign(window, { ViewAccueil, ... })`, une affectation valide que ce motif ne
    voit pas. Le garde a donc declare six liaisons rompues sur un artefact SAIN ; la
    "correction" qui a suivi a retire `window.` des appels, et comme chaque module vit
    dans son IIFE, les six vues du hub sont passees hors de portee et l'interface levait
    au premier rendu. Le garde n'a pas rate un defaut : il en a FABRIQUE un.
    """
    artefact = ('Object.assign(window, { ViewAccueil, ViewCap });'
                ' React.createElement(window.ViewAccueil, null);'
                ' React.createElement(window.ViewCap, null);')
    assert REB._liaisons_window_rompues(artefact, voisins=False) == [], (
        "Object.assign n'est pas reconnu comme une pose : le garde accuse un artefact sain"
    )


def test_object_assign_ne_blanchit_pas_ce_qu_il_ne_pose_pas():
    """Contre-epreuve : elargir la reconnaissance ne doit pas tout absoudre."""
    artefact = ('Object.assign(window, { ViewAccueil });'
                ' React.createElement(window.ViewFederation, null);')
    assert REB._liaisons_window_rompues(artefact, voisins=False) == ["ViewFederation"]


def test_les_proprietes_natives_ne_sont_pas_signalees():
    """`window.location` et consorts ne sont pas des composants : les citer ferait
    crier le garde a chaque build, donc le ferait desarmer."""
    artefact = 'window.location.href; window.addEventListener("x", f); window.matchMedia(q);'
    assert REB._liaisons_window_rompues(artefact) == []


def test_un_artefact_sans_lecture_window_ne_declenche_rien():
    """Sonde de la sonde : sur un artefact muet, le garde doit se taire, pas inventer."""
    assert REB._liaisons_window_rompues("const a = 1;") == []
    assert REB._liaisons_window_rompues("") == []


def test_le_garde_est_BRANCHE_dans_la_recompilation():  # noqa: D401
    """Une fonction juste que personne n'appelle est une dette, pas une securite.

    C'est la lecon du depot sur les gardes branches sur un signal sans emetteur, prise
    par l'autre bout : ici le signal existe, il faut que le consommateur l'ecoute.
    """
    import inspect
    src = inspect.getsource(REB.recompiler)
    assert "_liaisons_window_rompues" in src, (
        "le garde existe mais la recompilation ne l'interroge pas : une sortie "
        "incoherente passerait exactement comme le 2026-09-18"
    )
    assert "RESTAURE" in src, "un refus qui ne restaure pas laisse l'artefact casse en place"


def test_l_accent_grave_en_commentaire_est_refuse_avant_le_build(tmp_path):
    """MORSURE — paye DEUX fois le 2026-09-18, la seconde en ayant ecrit la note soi-meme.

    Le JSX du builder vit dans un litteral gabarit : un accent grave dans un commentaire
    referme la chaine, et node meurt en SyntaxError a une ligne SANS RAPPORT avec la
    faute. Le garde nomme la ligne fautive, ce que node ne fait pas.
    """
    mauvais = tmp_path / "build-hub.js"
    mauvais.write_text("const a = 1;\n  // voir `editMode` pour le detail\n",
                       encoding="utf-8")
    faute = REB._accent_grave_en_commentaire(mauvais)
    assert faute, "un accent grave en commentaire passe inapercu"
    assert "L2" in faute, "le garde ne nomme pas la ligne fautive : %s" % faute


def test_le_garde_ne_crie_pas_sur_un_builder_SAIN(tmp_path):
    """Contre-epreuve : un accent grave dans du CODE est legitime (c'est le gabarit)."""
    bon = tmp_path / "build-hub.js"
    bon.write_text("const T = `du <JSX ici>`;\n  // un commentaire sans accent grave\n",
                   encoding="utf-8")
    assert REB._accent_grave_en_commentaire(bon) == "", (
        "le garde accuse un builder correct : il se ferait desarmer"
    )


def test_le_garde_d_accent_grave_est_branche_avant_le_build():
    """Un controle qui s'execute APRES le build ne sert a rien : le mal est fait."""
    import inspect

    src = inspect.getsource(REB.recompiler)
    i_garde = src.find("_accent_grave_en_commentaire")
    i_node = src.find("subprocess.run")
    assert i_garde >= 0, "le garde n'est pas appele"
    assert i_node < 0 or i_garde < i_node, (
        "le garde s'execute apres le lancement de node : il ne previent plus rien"
    )


def test_le_refus_nomme_ce_qui_est_rompu():
    """Un refus qui ne dit pas QUOI oblige a re-enqueter a chaque fois."""
    import inspect
    src = inspect.getsource(REB.recompiler)
    assert "composants lus sur window" in src, (
        "le message de refus ne nomme pas les liaisons rompues"
    )
