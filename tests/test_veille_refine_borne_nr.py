"""NR : la borne du refine ne doit pas ecarter en silence ni classer sur le seul score offline."""
import asyncio
import logging

from nokido_agent.app import forge_chain_executor as fce
from nokido_agent.app import forge_watch_agent as fwa


def _ex():
    ex = fce.ChainExecutor.__new__(fce.ChainExecutor)
    ex.ctx = []
    ex.update_context = lambda cid, upd: ex.ctx.append(upd)
    return ex


def test_refine_examine_au_dela_de_8_et_dit_les_ecartes(monkeypatch, caplog):
    theme = "agent memory retrieval benchmark"
    res = [{"title": "agent memory retrieval benchmark %d" % i, "url": "https://example.org/%d" % i,
            "content": "agent memory retrieval benchmark " * 10} for i in range(12)]
    monkeypatch.setattr(fwa, "_llm_local", lambda p, *a, **k: "10:10")
    ex = _ex()
    node = {"chain_id": "c1", "agent_role": "RefineAgent"}
    with caplog.at_level(logging.WARNING):
        out = asyncio.run(ex._call_llm_step(node, "refine", {"theme": theme, "search_results": res}))
    assert len(out) == 5
    assert "https://example.org/9" in [r["url"] for r in out]
    ec = [u for u in ex.ctx if "refine_ecartes" in u]
    assert ec and len(ec[0]["refine_ecartes"]) == len(res) - 5
    assert "NON ingeres" in caplog.text
