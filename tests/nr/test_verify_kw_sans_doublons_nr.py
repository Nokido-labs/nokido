# -*- coding: utf-8 -*-
"""NR -- verify_kw ne peut plus ecraser la diversite des requetes d'une veille (2026-10-13).

Veille Hamilton/AGC : keywords a produit 4 requetes (dont « Apollo Executive Waitlist priority scheduling restart
protection » et « AGC phase tables 1202 alarm priority displays ») ; le LLM de verify_kw a repondu « 1 1 1 » et
l'etape a rendu trois fois la meme requete generique -- les requetes precises perdues, UNE source ingeree.
"""
from __future__ import annotations

import asyncio

import nokido_agent.app.forge_chain_executor as CE
import nokido_agent.app.forge_watch_agent as W

KWS = ["Margaret Hamilton AGC software engineering", "Apollo Executive Waitlist priority scheduling",
       "AGC phase tables 1202 alarm", "Hamilton priority displays"]


def _verifier(monkeypatch, sortie_llm):
    monkeypatch.setattr(W, "_llm_local", lambda prompt, *a, **k: sortie_llm)
    executeur = object.__new__(CE.ChainExecutor)
    return asyncio.run(CE.ChainExecutor._call_llm_step(
        executeur, {"id": "n"}, "verify_kw", {"theme": "Hamilton AGC", "keywords": KWS}))


def test_une_sortie_en_doublons_ne_ramene_pas_tout_a_une_requete(monkeypatch):
    r = _verifier(monkeypatch, "1 1 1")
    assert len(r) == 3 and len(set(r)) == 3, r
    assert r[0] == KWS[0] and KWS[1] in r and KWS[2] in r


def test_un_choix_propre_du_llm_est_respecte(monkeypatch):
    assert _verifier(monkeypatch, "3, 1, 4") == [KWS[2], KWS[0], KWS[3]]
