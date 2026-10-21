# -*- coding: utf-8 -*-
"""NR (lora_signal_usage_cause_2026-10-02, palier 1 AGY 19/10) : `ask` note sa recherche et marque ce qu'il cite.

`_get_rag_context` journalise la recherche (noter, source `ask`) et depose {rid, morceaux} dans un ContextVar -- meme
tache asyncio, donc aucune fuite entre deux `ask` concurrents ; apres la reponse du fournisseur, `_citer_reponse`
appelle marquer_cite pour chaque morceau que l'extracteur deterministe retrouve. Interrupteur NOKIDO_RAG_SIGNAL
(coupe par le conftest des NR, rallume ici avec des doublures). Rien ne leve : le signal ne casse jamais une reponse.
"""
import asyncio

from nokido_agent.app import forge_agent_proxy as P
from nokido_agent.app import forge_rag_usage_signal as S

DOCS = [{"id": "c1", "source": "docs/RULES_SHARED.md", "score": 0.9,
         "content": "Un agregat ne range jamais UNKNOWN BLOCKED ou STALE du cote sain on classe par liste blanche"},
        {"id": "c2", "source": "memory:feedback_hub", "score": 0.5, "content": "Le hub redemarre par le tray"}]


class _Rag:
    async def search(self, query, k=3, reorder_mid=True):
        return [dict(d) for d in DOCS]


def _doublures(monkeypatch):
    notes, cites = [], []
    monkeypatch.setenv("NOKIDO_RAG_SIGNAL", "1")
    import nokido_agent.app.forge_app_context as ctx
    monkeypatch.setattr(ctx, "get_rag", lambda: _Rag())
    import nokido_agent.app.forge_epistemic_retrieve as er
    monkeypatch.setattr(er, "qualifier_resultats", lambda r: {"retenus": r})
    monkeypatch.setattr(S, "noter", lambda q, ids, scores=None, source="", mode="": notes.append((ids, source))
                        or {"ok": True, "id": "rid42"})
    monkeypatch.setattr(S, "marquer_cite", lambda rid, cid, par="": cites.append((rid, cid, par)) or {"ok": True})
    return notes, cites


def test_la_recherche_est_notee_et_la_citation_marquee(monkeypatch):
    notes, cites = _doublures(monkeypatch)

    async def tour():
        ctx = await P._get_rag_context("doctrine du sain", k=3)
        assert "RULES_SHARED" in ctx
        P._citer_reponse("on ne range jamais UNKNOWN BLOCKED ou STALE du cote sain", "groq")
    asyncio.run(tour())
    assert notes == [(["c1", "c2"], "ask")]
    assert cites == [("rid42", "c1", "ask:groq")]


def test_interrupteur_coupe_rien_n_est_ecrit(monkeypatch):
    notes, cites = _doublures(monkeypatch)
    monkeypatch.setenv("NOKIDO_RAG_SIGNAL", "0")

    async def tour():
        await P._get_rag_context("x", k=3)
        P._citer_reponse("on ne range jamais UNKNOWN BLOCKED ou STALE du cote sain", "groq")
    asyncio.run(tour())
    assert notes == [] and cites == []


def test_sans_recherche_servie_la_citation_ne_fait_rien_et_ne_leve_pas(monkeypatch):
    _, cites = _doublures(monkeypatch)
    asyncio.run(asyncio.sleep(0))
    P._citer_reponse("texte quelconque", "groq")  # aucun contexte depose dans CETTE tache
    assert cites == []
