"""NR — vascularisation GOAP -> MCP : un intent sans outil MCP n'est JAMAIS un succes (fail-closed).

Mesure du 2026-09-27 (C:/tmp/mesure_joint_goap_mcp_2026-09-27.json) : 14 des 23 methodes de
forge_trajectory.ALLOWED_METHODS n'ont pas d'outil MCP homonyme (rag_search, embed, run_python...).
Les outils `plan` (execute=true) et `execute` routent chaque intent par son NOM vers registry.dispatch,
qui rend "Outil inconnu: <nom>" ; le dispatch garde ne classait en erreur que les prefixes
ERR/SECURITY/SECRET GUARD/FAIL -> le pas etait marque `completed`. REQUESTED pris pour ACHIEVED.

Invariants :
- chemin REEL (handle_execute et handle_plan, dispatch NON mocke) : un intent sans outil -> pas `failed` ;
- le message d'outil inconnu est une CONSTANTE partagee entre dispatch et la classification ;
- controle negatif : un retour ordinaire reste un `result`, une erreur dict reste une erreur.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_goap  # noqa: E402
from nokido_agent.app.forge_mcp_registry import ToolRegistry  # noqa: E402

# Nom choisi HORS de tout handler : ne depend pas de l'etat de la mesure (rag_search pourrait
# un jour gagner un outil MCP homonyme, et le test deviendrait faux sans que rien ne casse).
_INCONNU = "methode_goap_sans_outil_mcp_nr"


def _registre():
    reg = ToolRegistry(root_dir=ROOT)
    reg._event_bus = MagicMock()  # pas d'ecriture d'evenements pendant le test
    return reg


def _plan_dict():
    return {"goal": "nr outil inconnu", "plan_id": "nr_outil_inconnu", "parallel": False,
            "subgoals": [{"name": "s1", "actions": [
                {"jsonrpc": "2.0", "method": _INCONNU, "params": {}, "id": "1"}]}]}


@pytest.mark.asyncio
async def test_handle_execute_intent_sans_outil_est_failed():
    reg = _registre()
    assert not hasattr(reg, "handle_" + _INCONNU)
    out = json.loads(await reg.handle_execute({"plan": _plan_dict()}, agent="nr", ring=1))
    pas = out["steps"][0]
    assert pas["status"] == "failed", pas
    assert "Outil inconnu" in json.dumps(pas["result"], ensure_ascii=False)


@pytest.mark.asyncio
async def test_handle_plan_execute_intent_sans_outil_est_failed(monkeypatch):
    reg = _registre()
    d = _plan_dict()

    async def _plan_fixe(goal, context=None, ring_max=2):
        sg = forge_goap.SubGoal(name="s1", actions=d["subgoals"][0]["actions"])
        return forge_goap.PlanTree(goal=goal, subgoals=[sg])

    monkeypatch.setattr(forge_goap.GoalPlanner, "plan", staticmethod(_plan_fixe))
    out = json.loads(await reg.handle_plan({"goal": "nr", "execute": True}, agent="nr", ring=1))
    pas = out["trajectory"]["steps"][0]
    assert pas["status"] == "failed", pas


def test_message_outil_inconnu_est_une_constante_partagee():
    from nokido_agent.app import forge_mcp_registry as R
    assert R.OUTIL_INCONNU == "Outil inconnu"
    v = R.classer_retour_intent("%s: %s" % (R.OUTIL_INCONNU, _INCONNU), {"id": "1"})
    assert "error" in v and "result" not in v


@pytest.mark.parametrize("res,attendu", [
    ("ERR: boom", "error"),
    ("SECURITY: Acces refuse", "error"),
    ("FAIL x", "error"),
    ("ok, 3 faits", "result"),
    ({"hits": 2}, "result"),
    ({"error": "forbidden", "reason": "ring"}, "error"),
])
def test_controle_classification(res, attendu):
    from nokido_agent.app.forge_mcp_registry import classer_retour_intent
    v = classer_retour_intent(res, {"id": "7"})
    assert attendu in v
    other = "result" if attendu == "error" else "error"
    assert other not in v
