"""tests/test_forge_swarm_validator.py — ForgeSwarm M0 : plan-validator déterministe.

1 test par règle (collision-round, intégrité-FS, acyclique, couverture-bipartite)
+ structurel + plan bipartite valide.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from forge_swarm_validator import validate_swarm_plan  # noqa: E402


def _files(tmp_path: Path, *names: str) -> Path:
    for n in names:
        (tmp_path / n).write_text("x = 1\n", encoding="utf-8")
    return tmp_path


# ── Règle 1 : collision de round ─────────────────────────────────────────────
def test_rule1_round_collision(tmp_path: Path):
    root = _files(tmp_path, "a.py")
    plan = [
        {"task_id": "T1", "targets": ["a.py"], "deps": []},
        {"task_id": "T2", "targets": ["a.py"], "deps": []},  # même fichier, même round
    ]
    ok, errs = validate_swarm_plan(plan, root)
    assert not ok and any("R1" in e for e in errs)


def test_rule1_ok_when_serialized(tmp_path: Path):
    root = _files(tmp_path, "a.py")
    plan = [
        {"task_id": "T1", "targets": ["a.py"], "deps": []},
        {"task_id": "T2", "targets": ["a.py"], "deps": ["T1"]},  # round différent -> OK
    ]
    ok, errs = validate_swarm_plan(plan, root)
    assert ok, errs


# ── Règle 2 : intégrité FS ───────────────────────────────────────────────────
def test_rule2_phantom_file(tmp_path: Path):
    root = _files(tmp_path, "a.py")
    plan = [{"task_id": "T1", "targets": ["ghost.py"], "deps": [], "op": "edit_sr"}]
    ok, errs = validate_swarm_plan(plan, root)
    assert not ok and any("R2" in e for e in errs)


def test_rule2_create_then_edit(tmp_path: Path):
    root = _files(tmp_path, "a.py")
    plan = [
        {"task_id": "T1", "targets": ["new.py"], "deps": [], "op": "create"},
        {"task_id": "T2", "targets": ["new.py"], "deps": ["T1"], "op": "edit_sr"},  # créé en amont -> OK
    ]
    ok, errs = validate_swarm_plan(plan, root)
    assert ok, errs


# ── Règle 3 : acyclique ──────────────────────────────────────────────────────
def test_rule3_cycle(tmp_path: Path):
    root = _files(tmp_path, "a.py", "b.py")
    plan = [
        {"task_id": "T1", "targets": ["a.py"], "deps": ["T2"]},
        {"task_id": "T2", "targets": ["b.py"], "deps": ["T1"]},  # cycle
    ]
    ok, errs = validate_swarm_plan(plan, root)
    assert not ok and any("circulaire" in e for e in errs)


def test_rule3_unknown_dep(tmp_path: Path):
    root = _files(tmp_path, "a.py")
    plan = [{"task_id": "T1", "targets": ["a.py"], "deps": ["GHOST"]}]
    ok, errs = validate_swarm_plan(plan, root)
    assert not ok and any("inconnue" in e for e in errs)


# ── Règle 4 : couverture bipartite ───────────────────────────────────────────
def test_rule4_orphan_consumer(tmp_path: Path):
    root = _files(tmp_path, "models.py", "views.py")
    plan = [{"task_id": "T1", "targets": ["models.py"], "deps": [], "op": "rename"}]
    import_graph = {"models.py": {"views.py"}}  # views.py importe models.py
    ok, errs = validate_swarm_plan(plan, root, import_graph=import_graph)
    assert not ok and any("R4" in e and "views.py" in e for e in errs)


def test_rule4_consumer_covered(tmp_path: Path):
    root = _files(tmp_path, "models.py", "views.py")
    plan = [
        {"task_id": "T1", "targets": ["models.py"], "deps": [], "op": "rename"},
        {"task_id": "T2", "targets": ["views.py"], "deps": ["T1"], "op": "edit_sr"},  # propagation
    ]
    import_graph = {"models.py": {"views.py"}}
    ok, errs = validate_swarm_plan(plan, root, import_graph=import_graph)
    assert ok, errs


# ── Structurel + plan valide complet ─────────────────────────────────────────
def test_structural_dup_and_badop(tmp_path: Path):
    root = _files(tmp_path, "a.py")
    plan = [
        {"task_id": "T1", "targets": ["a.py"], "deps": [], "op": "frobnicate"},
        {"task_id": "T1", "targets": ["a.py"], "deps": []},  # dup id
    ]
    ok, errs = validate_swarm_plan(plan, root)
    assert not ok and any("dupliqué" in e for e in errs) and any("op invalide" in e for e in errs)


def test_valid_bipartite_plan(tmp_path: Path):
    root = _files(tmp_path, "models.py", "views.py", "api.py")
    plan = [
        {"task_id": "T1", "targets": ["models.py"], "deps": [], "op": "rename"},
        {"task_id": "T2", "targets": ["views.py"], "deps": ["T1"], "op": "edit_sr"},
        {"task_id": "T3", "targets": ["api.py"], "deps": ["T1"], "op": "edit_sr"},
    ]
    import_graph = {"models.py": {"views.py", "api.py"}}
    ok, errs = validate_swarm_plan(plan, root, import_graph=import_graph)
    assert ok, errs


def test_empty_plan_ok():
    ok, errs = validate_swarm_plan([], ".")
    assert ok and not errs
