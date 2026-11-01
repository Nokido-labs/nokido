# -*- coding: utf-8 -*-
"""NR -- la carte A2A publie la lecture economique (forge_token_cache, 30/10) : declaree, disponible si le module
existe, VERIFIEE par un NR qui nomme forge_token_cache. Le nombre de capacites ne diminue pas."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_a2a_card as card  # noqa: E402


def test_competence_token_efficient_digests_publiee():
    par_id = {e["id"]: e for e in card.etats()}
    e = par_id["token_efficient_digests"]
    assert e[card.AVAILABLE] is True
    assert e[card.VERIFIED] is True  # test_token_cache_nr.py nomme forge_token_cache


def test_aucune_capacite_retiree():
    ids = {e["id"] for e in card.etats()}
    assert {"rfc.freshness", "token_efficient_digests"} <= ids
    assert len(ids) >= 2
