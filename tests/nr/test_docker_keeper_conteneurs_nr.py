#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""NR — quels conteneurs le keeper Docker a-t-il le droit de relacher ?

POURQUOI CE TEST EXISTE. La regulation Docker a REGRESSE plusieurs fois sur ce
point precis, et toujours de la meme facon : la liste des conteneurs « a nous »
etait ENUMEREE dans une regex figee (`searxng|crawl4ai`). Mesure 2026-08-19 :
`exegol-laforge` — le conteneur le plus cite du depot, et l'un des plus lourds —
n'etait JAMAIS relache, pas plus que `nokido-qdrant` ou `laforge-runner`. Docker
pouvait donc tourner avec des conteneurs vivants sans aucun demandeur, ce que la
relache existe justement pour empecher.

Une enumeration ne suit pas un systeme vivant : chaque conteneur ajoute ensuite
echappe en silence, sans que rien ne le signale. Ce test fige donc les DEUX
directions, parce que l'erreur peut se faire dans les deux sens :
  * ce qui est A NOUS doit etre relachable — sinon la relache ne relache rien ;
  * ce qui ne l'est PAS doit etre epargne — on ne coupe pas le conteneur de
    l'owner sous ses doigts.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import forge_docker_keeper as K  # noqa: E402


@pytest.mark.parametrize("nom", [
    "searxng-laforge",     # historique, avec suffixe
    "exegol-laforge",      # le RATE de 2026-08-19 : le plus cite du depot
    "crawl4ai-laforge",
    "nokido-qdrant",       # convention prefixee
    "laforge-runner",
    "searxng",             # historique nu
    "crawl4ai",
])
def test_nos_conteneurs_sont_relachables(nom):
    assert K._OWN_CONTAINERS.search(nom), (
        f"{nom!r} appartient a Nokido : sans lui, la relache le laisse tourner "
        "sans demandeur — exactement le defaut qu'elle corrige"
    )


@pytest.mark.parametrize("nom", [
    "postgres", "redis", "portainer", "grafana", "ollama-webui",
    "searxng-de-lowner-a-lui",   # ⚠️ l'ancienne regex `^searxng` mordait dessus
    "mon-searxng-perso",
])
def test_les_conteneurs_tiers_sont_epargnes(nom):
    assert not K._OWN_CONTAINERS.search(nom), (
        f"{nom!r} n'est PAS a nous : le couper reviendrait a retirer un outil "
        "des mains de son proprietaire"
    )


def test_la_couverture_se_derive_et_ne_s_enumere_pas():
    """Un conteneur Nokido INCONNU AUJOURD'HUI doit deja etre couvert.

    C'est le coeur de la regression : une enumeration ne peut pas couvrir ce qui
    n'existe pas encore. La convention de nom, si.
    """
    for futur in ("nokido-truc-qui-nexiste-pas-encore",
                  "laforge-service-invente-demain",
                  "un-organe-nokido"):
        assert K._OWN_CONTAINERS.search(futur), (
            f"{futur!r} porte la marque Nokido et doit etre couvert SANS qu'on "
            "ait eu a l'ajouter a une liste"
        )
