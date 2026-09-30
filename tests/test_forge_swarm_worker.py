"""tests/test_forge_swarm_worker.py — ForgeSwarm M2 : worker éphémère + self-heal.

Inférence mockée (séquence d'outputs) → retry/early-exit déterministes.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from forge_swarm_patch import VFSOverlay  # noqa: E402
from forge_swarm_worker import run_worker  # noqa: E402


def _sr(search: str, replace: str) -> str:
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE\n"


GOOD = _sr("    return 1", "    return 2")
BAD1 = _sr("    return 991", "    x")  # ancre absente
BAD2 = _sr("    return 992", "    x")
BAD3 = _sr("    return 993", "    x")


def _mock(*outputs):
    seq = list(outputs)
    state = {"n": 0}

    def _f(_prompt):
        i = min(state["n"], len(seq) - 1)
        state["n"] += 1
        return seq[i]

    return _f


def _overlay(tmp_path: Path) -> VFSOverlay:
    (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    return VFSOverlay(tmp_path)


def _run(task, ov, infer, **kw):
    return asyncio.run(run_worker(task, ov, infer, **kw))


def test_worker_success_first_try(tmp_path: Path):
    ov = _overlay(tmp_path)
    r = _run({"task_id": "T1", "targets": ["m.py"], "prompt": "->2"}, ov, _mock(GOOD))
    assert r["ok"] and r["attempts"] == 1
    assert "return 2" in ov.read("m.py")


def test_worker_self_heal(tmp_path: Path):
    ov = _overlay(tmp_path)
    r = _run({"task_id": "T1", "targets": ["m.py"], "prompt": "->2"}, ov, _mock(BAD1, GOOD))
    assert r["ok"] and r["attempts"] == 2  # 1 échec puis succès
    assert "return 2" in ov.read("m.py")


def test_worker_max_retries_escalate(tmp_path: Path):
    ov = _overlay(tmp_path)
    r = _run({"task_id": "T1", "targets": ["m.py"], "prompt": "->2"}, ov, _mock(BAD1, BAD2, BAD3))
    assert not r["ok"] and r["attempts"] == 3 and r["error"]
    assert "return 1" in ov.read("m.py")  # overlay intact (rien appliqué)


def test_worker_early_exit_thrashing(tmp_path: Path):
    ov = _overlay(tmp_path)
    # même erreur 2x -> early-exit AVANT d'épuiser max_retries
    r = _run({"task_id": "T1", "targets": ["m.py"], "prompt": "->2"}, ov, _mock(BAD1, BAD1, BAD1), max_retries=3)
    assert not r["ok"] and r["attempts"] == 2


def test_worker_create_no_inference(tmp_path: Path):
    ov = _overlay(tmp_path)
    called = {"n": 0}

    def _never(_p):
        called["n"] += 1
        return ""

    r = _run({"task_id": "T1", "op": "create", "target": "new.py", "content": "z = 3\n"}, ov, _never)
    assert r["ok"] and r["attempts"] == 0
    assert ov.read("new.py") == "z = 3\n"
    assert called["n"] == 0  # create ne consulte PAS le LLM


def test_worker_emits_events(tmp_path: Path):
    ov = _overlay(tmp_path)
    events = []
    _run({"task_id": "T1", "targets": ["m.py"], "prompt": "->2"}, ov, _mock(GOOD),
         emit=lambda k, d: events.append(k))
    assert "agent_start" in events and "agent_reply" in events
