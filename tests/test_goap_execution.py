
import asyncio
import json
import unittest
from app.forge_goap import PlanTree, SubGoal, execute_plan, GOAPExecutionError

class TestGOAPExecution(unittest.IsolatedAsyncioTestCase):
    async def test_success_flow(self):
        """Vérifie l'exécution séquentielle réussie."""
        plan = PlanTree(goal="Test success")
        sg = SubGoal(name="sub1", actions=[
            {"jsonrpc": "2.0", "method": "web_search", "params": {"query": "test1"}, "id": "1"},
            {"jsonrpc": "2.0", "method": "web_search", "params": {"query": "test2"}, "id": "2"}
        ])
        plan.subgoals.append(sg)

        execution_order = []

        async def mock_dispatch(intent):
            execution_order.append(intent["params"]["query"])
            return {"jsonrpc": "2.0", "result": {"ok": True}, "id": intent["id"]}

        traj = await execute_plan(plan, dispatch_fn=mock_dispatch)
        
        self.assertEqual(len(traj.steps), 2)
        self.assertEqual(traj.steps[0].status, "completed")
        self.assertEqual(traj.steps[1].status, "completed")
        self.assertEqual(execution_order, ["test1", "test2"])

    async def test_rollback_flow(self):
        """Vérifie l'arrêt au premier échec et le déclenchement du rollback."""
        plan = PlanTree(goal="Test failure")
        sg = SubGoal(name="sub1", actions=[
            {"jsonrpc": "2.0", "method": "web_search", "params": {"query": "step1"}, "id": "1"},
            {"jsonrpc": "2.0", "method": "web_search", "params": {"query": "fail_me"}, "id": "2"},
            {"jsonrpc": "2.0", "method": "web_search", "params": {"query": "step3"}, "id": "3"}
        ])
        plan.subgoals.append(sg)

        dispatched = []

        async def mock_dispatch(intent):
            dispatched.append(intent["params"]["query"])
            if intent["params"]["query"] == "fail_me":
                return {"jsonrpc": "2.0", "error": {"code": -1, "message": "forced failure"}, "id": intent["id"]}
            return {"jsonrpc": "2.0", "result": {"ok": True}, "id": intent["id"]}

        traj = await execute_plan(plan, dispatch_fn=mock_dispatch, rollback=True)
        
        # On doit avoir 2 steps dans la trajectoire (le 3e n'est jamais lancé)
        self.assertEqual(len(traj.steps), 2)
        self.assertEqual(traj.steps[0].status, "completed")
        self.assertEqual(traj.steps[1].status, "failed")
        self.assertEqual(dispatched, ["step1", "fail_me"])

    async def test_registry_handle_execute_gating(self):
        """Vérifie que handle_execute propage le ring et applique le gating de dispatch."""
        from app.forge_mcp_registry import ToolRegistry
        from pathlib import Path

        reg = ToolRegistry(root_dir=Path("."))

        # Mock dispatch pour simuler le gating de ring
        async def mock_dispatch(name, args, agent, ring):
            if ring > 2:
                return "SECURITY: Acces refuse (agent ring > 2)"
            return {"jsonrpc": "2.0", "result": "success"}

        reg.dispatch = mock_dispatch

        # Plan d'exécution contenant une étape
        plan_dict = {
            "goal": "Test gating",
            "plan_id": "test_plan_123",
            "parallel": False,
            "subgoals": [
                {
                    "name": "sub1",
                    "actions": [
                        {"jsonrpc": "2.0", "method": "run", "params": {"command": "echo 1"}, "id": "1"}
                    ]
                }
            ]
        }

        # 1. Appel avec ring=4 (UNTRUSTED) -> doit échouer pour cause de sécurité
        res_fail = await reg.handle_execute({"plan": plan_dict}, agent="untrusted", ring=4)
        res_fail_data = json.loads(res_fail)
        self.assertEqual(res_fail_data["steps"][0]["status"], "failed")
        self.assertIn("SECURITY", res_fail_data["steps"][0]["result"]["error"])

        # 2. Appel avec ring=2 (TRUSTED) -> doit réussir
        res_ok = await reg.handle_execute({"plan": plan_dict}, agent="trusted", ring=2)
        res_ok_data = json.loads(res_ok)
        self.assertEqual(res_ok_data["steps"][0]["status"], "completed")

if __name__ == "__main__":
    unittest.main()
