"""NR : task action=result sans task_id valide (vide ou inconnu) est refuse explicitement.

Bug 2026-10-22 : handle_task_result renvoyait {"ok": true} sans rien ecrire (UPDATE sur 0 ligne).
"""
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.forge_mcp_registry import ToolRegistry  # noqa: E402


class _Reg:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / "sandbox").mkdir(parents=True, exist_ok=True)

    _task_db = ToolRegistry._task_db


def _appel(reg, args):
    return asyncio.run(ToolRegistry.handle_task_result(reg, args, "CLAUDE", 2))


def _est_refus(res):
    try:
        d = json.loads(res)
    except Exception:
        return False
    return d.get("ok") is False and bool(d.get("error"))


def test_task_id_vide_refuse(tmp_path):
    res = _appel(_Reg(tmp_path), {"task_id": "", "result": "x"})
    assert _est_refus(res), res


def test_task_id_absent_refuse(tmp_path):
    res = _appel(_Reg(tmp_path), {"result": "x"})
    assert _est_refus(res), res


def test_task_id_inconnu_refuse(tmp_path):
    res = _appel(_Reg(tmp_path), {"task_id": "tsk_inexistant", "result": "x"})
    assert _est_refus(res), res
    assert "tsk_inexistant" in res


def test_task_id_inconnu_n_ecrit_rien(tmp_path):
    reg = _Reg(tmp_path)
    _appel(reg, {"task_id": "tsk_inexistant", "result": "x"})
    c = sqlite3.connect(str(tmp_path / "sandbox" / "tasks.db"))
    assert c.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
