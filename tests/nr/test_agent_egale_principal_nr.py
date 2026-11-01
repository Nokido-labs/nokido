# -*- coding: utf-8 -*-
"""NR lot 4 : `agent` = identite PROUVEE. Jeton de A + annonce B -> agent == A (B reste trace).

__FORGE_COLOR__ = "immunitaire/guard : l'attribution (journaux, inbox, verrous) n'est pas usurpable"
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_videur as v  # noqa: E402

A, B = "COPILOT", "CLAUDE"
TOK = {A: "tok-a-0123456789", B: "tok-b-0123456789"}


def _id(annonce, token, tokens=TOK):
    return v.resolve_identity(annonce, token, local=False, agent_tokens=tokens,
                              hub_token="master-x",
                              principal_agent_hdr=annonce, declared_agent_hdr=annonce)


def test_jeton_a_annonce_b_attribue_a():
    i = _id(B, TOK[A])
    assert i["agent"] == A
    assert i["principal"] == A
    assert i["principal_annonce"] == B
    assert i["declared"] == B
    assert i["ring"] != _id(B, TOK[B])["ring"]


def test_annonce_egale_au_principal_inchangee():
    i = _id(A, TOK[A])
    assert i["agent"] == A and i["via"] == "token"


def test_jeton_partage_comportement_documente_inchange():
    # deux proprietaires : pas d'invention d'identite (UNKNOWN != NO), moindre privilege.
    tokens = {"X1": "shared-0123456789", "X2": "shared-0123456789"}
    i = _id(B, "shared-0123456789", tokens)
    assert i["via"] == "shared_token"
    assert i["agent"] in ("X1", "X2")
    assert i["principal_annonce"] == B
