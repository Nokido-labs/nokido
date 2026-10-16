# -*- coding: utf-8 -*-
"""NR -- la reprise durable ne rejoue une activity que pour les MEMES entrees (audit ChatGPT, 15/10).

`tools/forge_durable_workflow.WorkflowContext.activity` ecrivait `input_hash` mais ne le relisait
jamais : une meme `step_key` rappelee avec d'autres entrees rendait l'ANCIENNE sortie en silence.

Contrat (chemin reel, base SQLite temporaire) :
  1. memes entrees -> replay, effet de bord NON re-execute ;
  2. autres entrees -> WorkflowDivergence, ni replay de la sortie perimee, ni re-execution ;
  3. ligne anterieure sans hash -> rejouee, mais COMPTEE comme non verifiee.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_durable_workflow as dw  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = dw.WorkflowStore(tmp_path / "traces.db")
    yield s
    s.conn.close()


def _effet(appels):
    def doubler(x):
        appels.append(x)
        return {"y": 2 * x}
    return doubler


def test_memes_entrees_rejoue_sans_reexecuter(store):
    appels = []
    assert dw.WorkflowContext(store, "r1").activity("a", _effet(appels), 3) == {"y": 6}
    ctx = dw.WorkflowContext(store, "r1")
    assert ctx.activity("a", _effet(appels), 3) == {"y": 6}
    assert appels == [3] and ctx.replayed == 1 and ctx.replayed_sans_hash == 0


def test_autres_entrees_divergence_ni_replay_ni_execution(store):
    appels = []
    dw.WorkflowContext(store, "r2").activity("a", _effet(appels), 3)
    with pytest.raises(dw.WorkflowDivergence) as e:
        dw.WorkflowContext(store, "r2").activity("a", _effet(appels), 4)
    assert appels == [3] and e.value.step_key == "a"


def test_ligne_sans_hash_rejouee_mais_comptee_non_verifiee(store):
    store.put_step("r3", "a", "doubler", None, {"y": 6}, "completed")
    appels = []
    ctx = dw.WorkflowContext(store, "r3")
    assert ctx.activity("a", _effet(appels), 99) == {"y": 6}
    assert appels == [] and ctx.replayed_sans_hash == 1
