#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tests/test_forge_post_commit_breaker.py — circuit breaker POST_COMMIT.

Le 2026-08-16, un commit de 451 fichiers a fait POSTer POST_COMMIT ~2255 fois
vers le hub /mcp, chaque appel refuse (GATE DENY) mais NON DETECTE (le body
n'etait pas lu). Le hub a sature et est mort (os._exit du watchdog).

Deux gardes, tous deux en logique pure (aucun hub, aucun reseau, aucune DB) :
  - un gros commit ne doit JAMAIS marteler le hub : au-dela d'un seuil, on ecrit
    directement en DB (chemin qui ne touche pas l'event loop du hub) ;
  - un DENY doit etre DETECTE dans la reponse, et K DENY consecutifs coupent le
    hub pour le reste du run (le ring ne change pas en cours de route).
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from forge_post_commit import (  # noqa: E402
    MAX_FILES_HUB,
    should_use_hub,
    reponse_refusee,
)


def test_petit_commit_passe_par_le_hub():
    assert should_use_hub(1) is True
    assert should_use_hub(10) is True


def test_commit_au_seuil_passe_encore():
    assert should_use_hub(MAX_FILES_HUB) is True


def test_gros_commit_ne_martele_pas_le_hub():
    """451 fichiers (l'incident) : le hub ne doit pas etre sollicite."""
    assert should_use_hub(MAX_FILES_HUB + 1) is False
    assert should_use_hub(451) is False


def test_deny_detecte_dans_le_corps_http_200():
    """Le hub repond 200 avec un corps d'erreur : c'est le piege d'origine."""
    assert reponse_refusee(b'{"error": "GATE DENY tool=rag ring 4 <= requis 3"}')
    assert reponse_refusee('{"result": {"error": "insufficient ring"}}'.encode())
    assert reponse_refusee(b'{"jsonrpc":"2.0","error":{"message":"DENY"}}')


def test_succes_non_refuse():
    assert reponse_refusee(b'{"result": {"ok": true, "indexed": 1}}') is False
    assert reponse_refusee(b'{"jsonrpc":"2.0","id":1,"result":"stored"}') is False


def test_corps_illisible_pas_pris_pour_un_deny():
    """Un corps vide ou non-JSON n'est pas un refus : ne pas couper a tort."""
    assert reponse_refusee(b"") is False
    assert reponse_refusee(b"\x00\x01binaire") is False
