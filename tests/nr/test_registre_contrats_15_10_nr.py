# -*- coding: utf-8 -*-
"""NR -- contrats du registre MCP retouches le 15/10 (derogation owner `allow_critical`).

Chemin REEL : les handlers de `ToolRegistry` appeles avec un `self` minimal (seuls les attributs
qu'ils lisent), dependances externes doublees.
  1. loop_orchestrate applique `max_steps` AVANT execution et dit prevu / execute / ecartees
     (audit ChatGPT, diff d'AGY) ;
  2. web_search : une recherche qui n'a pas pu se faire dit « RECHERCHE NON FAITE », jamais
     « aucun resultat » ;
  3. rag index : le resultat entre aussi dans rag_fts (lexical), et une coupe a 4000 se DIT ;
  4. plus aucune mention de gpt4o_github dans le registre.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_goap as goap  # noqa: E402
from nokido_agent.app import forge_mcp_registry as reg  # noqa: E402
from nokido_agent.app import forge_web_fallback as wf  # noqa: E402

TR = reg.ToolRegistry


def _plan(n_par_sous_but):
    return goap.PlanTree(goal="g", subgoals=[
        goap.SubGoal(name="s%d" % i, actions=[{"method": "read_file", "i": j} for j in range(n)])
        for i, n in enumerate(n_par_sous_but)])


def test_plafonner_plan_coupe_et_compte():
    p = _plan([3, 2, 4])
    assert goap.plafonner_plan(p, 4) == {"prevu": 9, "garde": 4, "ecartees": 5}
    assert [len(sg.actions) for sg in p.subgoals] == [3, 1]
    p0 = _plan([2])
    assert goap.plafonner_plan(p0, "illisible") == {"prevu": 2, "garde": 0, "ecartees": 2} and p0.subgoals == []


def test_loop_orchestrate_applique_max_steps(tmp_path, monkeypatch):
    lances = []

    class _Planif:
        @staticmethod
        async def plan(goal, ring_max=None):
            return _plan([3, 3])

    async def _lancer(plan, dispatch_fn=None):
        n = sum(len(sg.actions) for sg in plan.subgoals)
        lances.append(n)
        return types.SimpleNamespace(ok=True, steps=[types.SimpleNamespace(intent="x")] * n)

    monkeypatch.setattr(reg, "GoalPlanner", _Planif)
    monkeypatch.setattr(reg, "execute_plan", _lancer)
    soi = types.SimpleNamespace(db_path=tmp_path / "e.db")
    c = sqlite3.connect(str(soi.db_path))
    c.execute("CREATE TABLE autonomous_loop_state (pattern TEXT PRIMARY KEY, enabled INT, last_run REAL, last_status TEXT)")
    c.commit()
    c.close()
    r = json.loads(asyncio.run(TR.handle_loop_orchestrate(soi, {"pattern": "p", "max_steps": 2}, "CLAUDE", 1)))
    assert lances == [2] and (r["prevu"], r["execute"], r["ecartees"]) == (6, 2, 4), r


def test_web_search_non_faite_n_est_pas_vide(monkeypatch):
    async def _diag(q, max_results=5):
        return {"results": [], "erreurs": ["searxng: ConnectionRefusedError"], "source": None}

    monkeypatch.setattr(wf, "web_search_diag", _diag)
    soi = types.SimpleNamespace(root=RACINE)
    out = asyncio.run(TR.handle_web_search(soi, {"query": "x"}, "CLAUDE", 1))
    assert "RECHERCHE NON FAITE" in out and "ConnectionRefusedError" in out and "Aucun resultat" not in out


def test_rag_index_entre_en_lexical_et_dit_la_coupe(tmp_path):
    db = tmp_path / "rag.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, text TEXT, domain TEXT, author TEXT, ingested_at TEXT)")
    c.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source, domain)")
    c.commit()
    c.close()
    soi = types.SimpleNamespace(db_path=db, state_mgr=types.SimpleNamespace(add_notification=lambda *a, **k: None))
    out = asyncio.run(TR.handle_index_result(soi, {"task_id": "t1", "result": "z" * 5000}, "CLAUDE", 1))
    assert "lexical OK" in out and "COUPE a 4000/" in out, out
    c = sqlite3.connect(str(db))
    assert c.execute("SELECT COUNT(*) FROM rag_fts").fetchone()[0] == 1
    c.close()


def test_plus_de_gpt4o_github_dans_le_registre():
    src = (RACINE / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    assert "gpt4o_github" not in src
