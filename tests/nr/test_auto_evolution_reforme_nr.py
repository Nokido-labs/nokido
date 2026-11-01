"""NR reforme tools/forge_auto_evolution_loop.py : observation seule, erreurs distinctes."""
import ast
import importlib.util
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "tools" / "forge_auto_evolution_loop.py"


def _mod(tmp_path):
    spec = importlib.util.spec_from_file_location("evol_under_test", SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.LESSONS_FILE = tmp_path / "lessons.md"
    m.PROPOSALS_DIR = tmp_path
    m.HEARTBEAT_GLOB = str(tmp_path / "*.heartbeat")
    return m


def _lessons(m, kind, dates):
    m.LESSONS_FILE.write_text(
        "\n".join(f"### [{d}] {kind} cas numero {i}\ncorps\n" for i, d in enumerate(dates)),
        encoding="utf-8",
    )


def _props(tmp_path):
    return list(tmp_path.glob("evolution_proposal_*.md"))


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def test_ast_no_restart():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            assert "nssm" not in n.value.lower()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert n.name != "_hub_restart"


def test_stale_iso_logged_no_action(tmp_path, caplog):
    m = _mod(tmp_path)
    old = (datetime.now() - timedelta(hours=2)).isoformat()
    (tmp_path / "svc.heartbeat").write_text(json.dumps({"ts": old}))
    with caplog.at_level("INFO"):
        m.check_heartbeats({})
    assert any("svc" in r.getMessage() for r in caplog.records)
    assert not hasattr(m, "_hub_restart")


def test_heartbeat_without_key_unknown(tmp_path, caplog):
    m = _mod(tmp_path)
    (tmp_path / "x.heartbeat").write_text(json.dumps({"foo": 1}))
    with caplog.at_level("INFO"):
        m.check_heartbeats({})
    assert "INCONNU" in " ".join(r.getMessage() for r in caplog.records)


def test_solutions_zero_proposal(tmp_path):
    m = _mod(tmp_path)
    _lessons(m, "SOLUTION", [_today()] * 3)
    m.scan_lessons({})
    assert _props(tmp_path) == []


def test_errors_one_proposal_then_idempotent(tmp_path):
    m = _mod(tmp_path)
    _lessons(m, "ERREUR", [_today()] * 3)
    st = {}
    m.scan_lessons(st)
    assert len(_props(tmp_path)) == 1
    time.sleep(1.1)
    m.scan_lessons(st)
    assert len(_props(tmp_path)) == 1
    assert st["proposals_written"] == 1


def test_old_errors_zero(tmp_path):
    m = _mod(tmp_path)
    _lessons(m, "ERREUR", ["2020-01-01"] * 3)
    m.scan_lessons({})
    assert _props(tmp_path) == []
