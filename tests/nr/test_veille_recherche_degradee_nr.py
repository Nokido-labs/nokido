# -*- coding: utf-8 -*-
"""NR (28/10) : une recherche de veille DEGRADEE (SearXNG muet, repli academique seul) doit le DIRE.

Mesure : 3 veilles sur 6 `completed_empty` sur des sujets reels (ACP, Orca, ai-dash) -- la recherche n'avait
rendu que arxiv/doi/ssrn, le tri les a refuses a juste titre, et rien dans le job ne disait que la
recherche web n'avait pas repondu. Un motif pose sur une liste NON vide n'etait lu par personne
(run_node ne lit le motif que d'une liste vide) : il doit atteindre watch_jobs.error.
"""
import asyncio
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _faux_watch_agent(searxng, academic, ensure=False):
    mod = types.ModuleType("forge_watch_agent")
    mod._ensure_searxng = lambda *a, **kw: ensure
    mod._searxng = searxng
    mod._academic_search = academic
    mod._github_search = lambda q, n=4, leve=False: academic(q, n)
    return mod


@pytest.mark.timeout(120)
def test_searxng_muet_repli_academique_porte_le_motif(monkeypatch, tmp_path):
    import forge_chain_executor as ce

    def _muet(_kw, _n):
        raise OSError("searxng down")

    def _academic(_kw, _n):
        return [{"title": "t", "url": "https://arxiv.org/abs/1", "content": "c", "engine": "arxiv_direct"}]

    for nom in ("forge_watch_agent", "nokido_agent.app.forge_watch_agent"):
        monkeypatch.setitem(sys.modules, nom, _faux_watch_agent(_muet, _academic))
    ex = ce.ChainExecutor(db_path=tmp_path / "chain.db")
    res = asyncio.run(ex._call_search({"keywords": ["any"]}))
    assert isinstance(res, list) and len(res) == 1
    assert getattr(res, "motif", None) == ce.MOTIF_SEARXNG_MUET


def test_la_degradation_est_notee_pour_le_job(tmp_path):
    import forge_chain_executor as ce
    ex = ce.ChainExecutor(db_path=tmp_path / "chain.db")
    ex._noter_degradation("wj_x", ce.MOTIF_SEARXNG_MUET)
    note = ex._motifs_arret["wj_x"]
    assert ce.MOTIF_SEARXNG_MUET in note and "degradee" in note


def test_run_node_lit_le_motif_d_une_liste_non_vide():
    src = (ROOT / "app" / "forge_chain_executor.py").read_text(encoding="utf-8")
    assert "self._noter_degradation(chain_id" in src, "le motif d'une recherche degradee n'a toujours aucun lecteur"
