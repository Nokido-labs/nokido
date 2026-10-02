import pytest
from pathlib import Path
from app.forge_swarm_validator import validate_swarm_plan

def test_validator_comportement_principal(tmp_path: Path):
    # Fichiers de depart
    (tmp_path / "f1.py").write_text("")
    (tmp_path / "f2.py").write_text("")

    plan = [
        {"task_id": "T1", "targets": ["f1.py"], "deps": [], "op": "edit_sr"},
        {"task_id": "T2", "targets": ["f2.py"], "deps": ["T1"], "op": "edit_sr"}
    ]
    ok, errs = validate_swarm_plan(plan, root=tmp_path)
    assert ok is True
    assert not errs

def test_validator_r1_collision(tmp_path: Path):
    (tmp_path / "f1.py").write_text("")
    plan = [
        {"task_id": "T1", "targets": ["f1.py"], "deps": [], "op": "edit_sr"},
        {"task_id": "T2", "targets": ["f1.py"], "deps": [], "op": "edit_sr"}
    ]
    ok, errs = validate_swarm_plan(plan, root=tmp_path)
    assert ok is False
    assert any("R1: fichier 'f1.py' ciblé par" in e for e in errs)

def test_validator_cycle_et_inconnu(tmp_path: Path):
    plan = [
        {"task_id": "T1", "targets": ["f.py"], "deps": ["T2"], "op": "create"},
        {"task_id": "T2", "targets": ["f2.py"], "deps": ["T1"], "op": "create"}
    ]
    ok, errs = validate_swarm_plan(plan, root=tmp_path)
    assert ok is False
    assert any("R3: dépendance circulaire" in e for e in errs)
