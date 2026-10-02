import pytest
import asyncio
from pathlib import Path
# Noms CANONIQUES, ceux de la production : le worker attrape nokido_agent.app.forge_swarm_patch.PatchError.
# Importer VFSOverlay sous `app.` chargeait une SECONDE instance du module, dont la PatchError
# echappait au `except` du worker (test rouge pour une raison etrangere au comportement teste).
from nokido_agent.app.forge_swarm_worker import run_worker
from nokido_agent.app.forge_swarm_patch import VFSOverlay

def test_worker_comportement_principal(tmp_path: Path):
    vfs = VFSOverlay(tmp_path)
    vfs.apply({"op": "create", "target": "a.py", "content": "def func(): pass\n"})
    
    def mock_infer(prompt):
        return "<<<<<<< SEARCH\ndef func(): pass\n=======\ndef func(): return 1\n>>>>>>> REPLACE"
        
    task = {"task_id": "t1", "op": "edit_sr", "targets": ["a.py"]}
    res = asyncio.run(run_worker(task, vfs, mock_infer))
    assert res["ok"] is True
    assert res["attempts"] == 1
    assert "return 1" in vfs.read("a.py")

def test_worker_anti_thrashing(tmp_path: Path):
    vfs = VFSOverlay(tmp_path)
    vfs.apply({"op": "create", "target": "a.py", "content": "hello\n"})
    
    def bad_infer(prompt):
        # Toujours une mauvaise reponse -> PatchError ancre introuvable
        return "<<<<<<< SEARCH\nnot_in_file\n=======\nrepl\n>>>>>>> REPLACE"
    
    task = {"task_id": "t1", "op": "edit_sr", "targets": ["a.py"]}
    res = asyncio.run(run_worker(task, vfs, bad_infer, max_retries=5))
    
    # Doit fail tot a cause de l'anti-thrashing
    assert res["ok"] is False
    assert res["attempts"] < 5
    assert "ancre SEARCH non trouvée" in res["error"]
