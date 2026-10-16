# -*- coding: utf-8 -*-
"""NR — app/forge_orchestration_gate.py : plan_route et soumission DEPORT (Constat 5).

Contexte (Audit ChatGPT 15/10) :
La docstring de `plan_route()` promettait :
  « forge_workflow.submit se déclenche si lane==DEPORT. »
Mais l'implémentation se contentait de classifier et renvoyer la décision
sans jamais appeler `forge_workflow.submit()`.

Ce test vérifie sur le CHEMIN RÉEL (`plan_route`) :
1. Une action routée sur la voie DEPORT déclenche la préparation/soumission
   du workflow via `forge_workflow.submit` et renvoie la clé `submission`.
2. Le fichier de plan généré par la soumission existe réellement sur disque.
3. Une action routée sur NATIVE ou LOCAL ne déclenche aucune soumission DEPORT.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

from nokido_agent.app.forge_orchestration_gate import Action, Lane, plan_route


@pytest.mark.asyncio
async def test_plan_route_triggers_submit_on_deport():
    """Une action classée DEPORT doit déclencher forge_workflow.submit."""
    # Action typique DEPORT (kind veille ou est_steps >= 3)
    action = Action(prompt="veille technologique et benchmark NPU AMD", kind="veille")

    res = await plan_route(action)

    assert res.get("lane") == Lane.DEPORT.value
    assert "submission" in res, "plan_route() sur voie DEPORT doit contenir la clé 'submission'"
    sub = res["submission"]
    assert isinstance(sub, dict), "submission doit être un dictionnaire"
    assert "plan_path" in sub, "submission doit contenir 'plan_path'"
    plan_file = Path(sub["plan_path"])
    assert plan_file.exists(), f"Le fichier de plan {plan_file} doit exister sur le disque"


@pytest.mark.asyncio
async def test_plan_route_preserves_custom_plan_on_deport():
    """Si l'action fournit un plan explicite, celui-ci doit être soumis tel quel."""
    custom_plan = {
        "name": "custom-deport-plan-42",
        "phases": [
            {
                "name": "P_AUDIT",
                "mode": "parallel",
                "agents": [{"role": "analyste", "provider": "groq", "prompt": "analyser"}],
            }
        ],
    }
    action = Action(
        prompt="gros refactor architectural",
        kind="refactor_multi",
        est_steps=8,
        plan=custom_plan,
    )

    res = await plan_route(action)

    assert res.get("lane") == Lane.DEPORT.value
    assert "submission" in res
    plan_file = Path(res["submission"]["plan_path"])
    assert plan_file.exists()
    content = plan_file.read_text(encoding="utf-8")
    assert "custom-deport-plan-42" in content


def test_ecrire_plan_ecrit_et_ne_lance_rien(tmp_path, monkeypatch):
    """Decision owner du 15/10 : `submit` promettait un lancement jamais fait -> renomme `ecrire_plan`.
    Le contrat : un plan ECRIT sur disque, aucun `job_id`, et la note le dit ; `submit` reste un alias."""
    from nokido_agent.app import forge_workflow as wf

    monkeypatch.setattr(wf, "ROOT", tmp_path)
    r = wf.ecrire_plan({"name": "nr-ecrire-plan", "phases": []})
    assert Path(r["plan_path"]).exists() and "nr-ecrire-plan" in Path(r["plan_path"]).read_text(encoding="utf-8")
    assert "job_id" not in r and "rien n'est lance" in r["note"]
    assert wf.submit({"name": "nr-alias", "phases": []}).keys() == r.keys()


@pytest.mark.asyncio
async def test_plan_route_no_submit_on_native():
    """Une action classée NATIVE ne doit pas générer de soumission DEPORT."""
    action = Action(prompt="edition simple de fichier", kind="file_edit", est_tokens=300)

    res = await plan_route(action)

    assert res.get("lane") == Lane.NATIVE.value
    assert res.get("submission") is None, "Une action NATIVE ne doit pas avoir de submission DEPORT"
