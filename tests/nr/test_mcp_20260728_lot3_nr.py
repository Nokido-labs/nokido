# -*- coding: utf-8 -*-
"""NR lot MCP 2026-07-28 n°3 : baggage W3C decode, chemin muet journalise, SEPARATION declare/prouve.

__FORGE_COLOR__ = "immunitaire/guard : l'identite declaree ne decide jamais d'un privilege"
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_mcp_protocole as P  # noqa: E402


def test_baggage_decode_url():
    assert P._baggage("k%201=v%2C1") == {"k 1": "v,1"}


def test_baggage_espaces_et_proprietes():
    assert P._baggage("a=1 , b=2;p=1") == {"a": "1", "b": "2"}


def test_initialize_illisible_journalise_en_debug(caplog):
    class Piege(dict):
        def get(self, *_a, **_k):
            raise RuntimeError("corps piege")

    with caplog.at_level(logging.DEBUG):
        r = P.declared_depuis_initialize(Piege(method="initialize"), "DEF")
    assert r == "DEF"
    assert any(rec.exc_info for rec in caplog.records)


def test_declare_ne_sert_jamais_au_controle_d_acces():
    import forge_videur as v
    from forge_trace_context import bind_actor, get_actor

    A, B = "COPILOT", "CLAUDE"
    tokens = {A: "tok-a-0123456789", B: "tok-b-0123456789"}
    ring_a = v.resolve_identity(A, tokens[A], local=False, agent_tokens=tokens,
                                hub_token="master-x")["ring"]
    ring_b = v.resolve_identity(B, tokens[B], local=False, agent_tokens=tokens,
                                hub_token="master-x")["ring"]
    assert ring_a != ring_b
    ident = v.resolve_identity(
        B, tokens[A], local=False, agent_tokens=tokens, hub_token="master-x",
        principal_agent_hdr=B, declared_agent_hdr=B)
    assert ident["principal"] == A
    # jamais plus privilegie que A (numeriquement >=), et surtout pas le ring de B : le nom
    # annonce n'ouvre rien (plancher anti-spoof header = moindre privilege).
    assert ident["ring"] >= ring_a and ident["ring"] != ring_b
    assert ident["declared"] == B
    assert ident["principal_annonce"] == B

    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": {
        P.META_NS + "protocolVersion": "2026-07-28",
        P.META_NS + "clientInfo": {"name": B}}}}
    decl = P.declared_depuis_meta(body, A)
    assert decl == B
    assert P.declared_depuis_initialize(
        {"method": "initialize", "params": {"clientInfo": {"name": B}}}, A) == B
    with bind_actor(B, principal=ident["principal"], declared=decl, ring=ident["ring"]):
        act = get_actor()
    assert act["principal"] == A and act["ring"] == ident["ring"] and act["declared"] == B


def test_hub_ne_derive_pas_le_ring_du_declare():
    src = (ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    i = src.index("_decl26 = _declared_meta")
    bloc = src[i:i + 500]
    assert "ring=ring" in bloc and "principal=principal" in bloc
    assert "ring = " not in bloc and "ring=_decl26" not in bloc
