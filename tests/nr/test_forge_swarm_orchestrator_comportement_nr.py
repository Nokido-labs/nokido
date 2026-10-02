import pytest
import asyncio
from pathlib import Path
from app.forge_swarm_orchestrator import run_forge_swarm

def test_orchestrator_comportement_principal(tmp_path: Path):
    def mock_infer(prompt):
        return ""
        
    plan = [
        {"task_id": "t1", "op": "create", "targets": ["a.py"], "content": "hello", "deps": []},
        {"task_id": "t2", "op": "create", "targets": ["b.py"], "content": "world", "deps": ["t1"]}
    ]
    
    res = asyncio.run(run_forge_swarm(plan, tmp_path, mock_infer))
    assert res["ok"] is True
    assert len(res["touched"]) == 2
    assert (tmp_path / "a.py").is_file()
    assert (tmp_path / "b.py").is_file()

def test_orchestrator_rollback_total(tmp_path: Path):
    (tmp_path / "a.py").write_text("hello\n")
    
    def mock_infer(prompt):
        # Pour t2 edit_sr, provoquera PatchError
        return "<<<<<<< SEARCH\nwrong\n=======\nbad\n>>>>>>> REPLACE"
        
    plan = [
        {"task_id": "t1", "op": "create", "targets": ["b.py"], "content": "world", "deps": []}, # Va reussir
        {"task_id": "t2", "op": "edit_sr", "targets": ["a.py"], "deps": ["t1"]} # Va echouer
    ]
    
    res = asyncio.run(run_forge_swarm(plan, tmp_path, mock_infer))
    assert res["ok"] is False
    assert "t2" in res["failed"]
    
    # Verification du rollback complet: le fichier cree en t1 ne doit pas exister sur le disque
    assert not (tmp_path / "b.py").exists()
