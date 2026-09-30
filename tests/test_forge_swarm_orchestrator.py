"""tests/test_forge_swarm_orchestrator.py — ForgeSwarm M5 : E2E (mock LLM).

Valide le pipeline complet validator → DAGRunner(workers) → overlay → commit/discard.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from forge_swarm_orchestrator import run_forge_swarm  # noqa: E402


def _sr(s: str, r: str) -> str:
    return f"<<<<<<< SEARCH\n{s}\n=======\n{r}\n>>>>>>> REPLACE\n"


def _router(mapping: dict):
    def _f(prompt: str):
        for k, out in mapping.items():
            if k in prompt:
                return out
        return "AUCUN BLOC"

    return _f


def _m(tmp: Path) -> Path:
    (tmp / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    return tmp


def _run(*a, **k):
    return asyncio.run(run_forge_swarm(*a, **k))


def test_e2e_two_independent(tmp_path: Path):
    _m(tmp_path)
    (tmp_path / "n.py").write_text("def g():\n    return 10\n", encoding="utf-8")
    plan = [
        {"task_id": "T1", "targets": ["m.py"], "deps": [], "prompt": "TASK-T1"},
        {"task_id": "T2", "targets": ["n.py"], "deps": [], "prompt": "TASK-T2"},
    ]
    infer = _router({"TASK-T1": _sr("    return 1", "    return 2"),
                     "TASK-T2": _sr("    return 10", "    return 20")})
    r = _run(plan, tmp_path, infer)
    assert r["ok"], r
    assert "return 2" in (tmp_path / "m.py").read_text()
    assert "return 20" in (tmp_path / "n.py").read_text()


def test_e2e_cascade_phantom_state(tmp_path: Path):
    _m(tmp_path)
    plan = [
        {"task_id": "T1", "targets": ["m.py"], "deps": [], "prompt": "TASK-T1"},
        {"task_id": "T2", "targets": ["m.py"], "deps": ["T1"], "prompt": "TASK-T2"},
    ]
    # T2 ancre "return 2" = la version PATCHÉE par T1 (overlay), pas le disque ("return 1").
    infer = _router({"TASK-T1": _sr("    return 1", "    return 2"),
                     "TASK-T2": _sr("    return 2", "    return 3")})
    r = _run(plan, tmp_path, infer)
    assert r["ok"], r
    assert "return 3" in (tmp_path / "m.py").read_text()  # cascade overlay OK


def test_e2e_reject_invalid_plan(tmp_path: Path):
    _m(tmp_path)
    plan = [  # collision : m.py par 2 workers, même round
        {"task_id": "T1", "targets": ["m.py"], "deps": [], "prompt": "x"},
        {"task_id": "T2", "targets": ["m.py"], "deps": [], "prompt": "y"},
    ]
    r = _run(plan, tmp_path, _router({}))
    assert not r["ok"] and r["stage"] == "validate"
    assert "return 1" in (tmp_path / "m.py").read_text()  # disque intact


def test_e2e_worker_fail_atomic(tmp_path: Path):
    _m(tmp_path)
    (tmp_path / "n.py").write_text("def g():\n    return 10\n", encoding="utf-8")
    plan = [
        {"task_id": "T1", "targets": ["m.py"], "deps": [], "prompt": "TASK-T1"},  # ok
        {"task_id": "T2", "targets": ["n.py"], "deps": [], "prompt": "TASK-T2"},  # échec
    ]
    infer = _router({"TASK-T1": _sr("    return 1", "    return 2"),
                     "TASK-T2": _sr("    return 999", "    x")})  # ancre absente
    r = _run(plan, tmp_path, infer)
    assert not r["ok"] and r["stage"] == "execute"
    # un échec -> overlay DISCARD -> disque 100% intact (atomicité all-or-nothing)
    assert "return 1" in (tmp_path / "m.py").read_text()
    assert "return 10" in (tmp_path / "n.py").read_text()


def test_e2e_fail_fast_skips_dependent(tmp_path: Path):
    _m(tmp_path)
    plan = [
        {"task_id": "T1", "targets": ["m.py"], "deps": [], "prompt": "TASK-T1"},       # échoue
        {"task_id": "T2", "targets": ["m.py"], "deps": ["T1"], "prompt": "TASK-T2"},   # skip
    ]
    infer = _router({"TASK-T1": _sr("    return 999", "    x"),
                     "TASK-T2": _sr("    return 2", "    return 3")})
    r = _run(plan, tmp_path, infer)
    assert not r["ok"]
    assert "T1" in r["failed"] and "T2" in r["failed"]  # T2 sauté (dépendance échouée)


def test_e2e_dry_run_no_disk(tmp_path: Path):
    _m(tmp_path)
    plan = [{"task_id": "T1", "targets": ["m.py"], "deps": [], "prompt": "TASK-T1"}]
    infer = _router({"TASK-T1": _sr("    return 1", "    return 2")})
    r = _run(plan, tmp_path, infer, dry_run=True)
    assert r["ok"]
    assert "return 1" in (tmp_path / "m.py").read_text()  # dry_run -> aucune écriture


async def _infer_lent(prompt: str):
    await asyncio.sleep(5)
    return "AUCUN BLOC"


def test_e2e_timeout_compte_dans_failed(tmp_path: Path):
    """NR 26/09 : un pas coupe par le timeout du DAGRunner ne revenait jamais dans _exec ;
    l'essaim rendait ok=False avec failed=[] (mesure : 12 taches locales, 10 TIMEOUT)."""
    _m(tmp_path)
    plan = [{"task_id": "T1", "targets": ["m.py"], "deps": [], "prompt": "TASK-T1"}]
    r = _run(plan, tmp_path, _infer_lent, timeout_per_step=0.2)
    assert not r["ok"] and r["stage"] == "execute", r
    assert r["failed"] == ["T1"], r
    assert str(r["results"]["T1"]).startswith("TIMEOUT"), r
    assert "return 1" in (tmp_path / "m.py").read_text()


def test_e2e_dependant_d_un_pas_coupe_est_saute(tmp_path: Path):
    """NR 26/09 : le DAGRunner range un pas TIMEOUT dans `done` ; son dependant partait sur un
    overlay prive du patch attendu. Il doit etre saute, et compte en echec."""
    _m(tmp_path)
    appels = []

    async def _infer(prompt: str):
        if "TASK-T1" in prompt:
            await asyncio.sleep(5)
        appels.append(prompt)
        return _sr("    return 1", "    return 3")

    plan = [
        {"task_id": "T1", "targets": ["m.py"], "deps": [], "prompt": "TASK-T1"},
        {"task_id": "T2", "targets": ["m.py"], "deps": ["T1"], "prompt": "TASK-T2"},
    ]
    r = _run(plan, tmp_path, _infer, timeout_per_step=0.2)
    assert not r["ok"], r
    assert r["failed"] == ["T1", "T2"], r
    assert r["results"]["T2"].get("skipped") is True, r
    assert appels == [], appels  # T2 n'a jamais interroge le modele
    assert "return 1" in (tmp_path / "m.py").read_text()
