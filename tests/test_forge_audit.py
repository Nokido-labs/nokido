"""tests/test_forge_audit.py — ForgeAudit : diff-targeting + orchestrateur E2E (pool mock)."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from forge_audit import changed_lines_from_diff, enclosing_targets, run_forge_audit  # noqa: E402

_CODE = "VERSION = 1\n\n\ndef login(pw):\n    return pw == 'x'\n\n\nclass A:\n    def verify(self):\n        return True\n"


def _src(tmp: Path) -> Path:
    (tmp / "auth.py").write_text(_CODE, encoding="utf-8")
    return tmp


# ── diff-targeting (refinement Gemini : AST-overlap + niveau module) ─────────
def test_changed_lines_from_diff():
    diff = "+++ b/auth.py\n@@ -3,2 +4,3 @@\n context\n+added line\n+another\n"
    cl = changed_lines_from_diff(diff)
    assert "auth.py" in cl and len(cl["auth.py"]) == 2


def test_enclosing_targets_function(tmp_path: Path):
    root = _src(tmp_path)
    # ligne 5 = corps de login -> cible 'login'
    assert "login" in enclosing_targets("auth.py", {5}, root)


def test_enclosing_targets_method(tmp_path: Path):
    root = _src(tmp_path)
    # ligne 10 = corps de A.verify -> classe A (chevauche)
    assert "A" in enclosing_targets("auth.py", {10}, root)


def test_enclosing_targets_module_level(tmp_path: Path):
    root = _src(tmp_path)
    # ligne 1 = VERSION = 1 (hors def/class) -> '<module>'
    assert "<module>" in enclosing_targets("auth.py", {1}, root)


def test_enclosing_targets_parse_fail(tmp_path: Path):
    (tmp_path / "broken.py").write_text("def f(\n", encoding="utf-8")
    assert enclosing_targets("broken.py", {1}, tmp_path) == ["<module>"]


# ── orchestrateur E2E (pool mock, 0 LLM) ─────────────────────────────────────
class _FakePool:
    def __init__(self, out):
        self.out = out
        self.calls = 0

    async def infer(self, prompt, *, schema=None, **k):
        self.calls += 1
        return self.out


def _run(*a, **k):
    return asyncio.run(run_forge_audit(*a, **k))


def test_run_audit_filters_and_aggregates(tmp_path: Path):
    root = _src(tmp_path)
    out = json.dumps({"findings": [
        {"symbol_target": "login", "lens": "security", "severity": "CRITICAL", "issue": "timing attack"},
        {"symbol_target": "ghost", "lens": "security", "severity": "HIGH", "issue": "halluciné"},
    ]})
    pool = _FakePool(out)
    rep = _run(["auth.py"], root, lenses=["security"], pool=pool)
    assert pool.calls == 1  # 1 fichier x 1 lens
    assert len(rep["kept"]) == 1 and rep["dropped"] == 1  # ghost jeté
    assert "CRITICAL" in rep["report_md"]


def test_run_audit_fanout_count(tmp_path: Path):
    root = _src(tmp_path)
    pool = _FakePool(json.dumps({"findings": []}))
    _run(["auth.py"], root, lenses=["security", "correctness", "architecture", "style"], pool=pool)
    assert pool.calls == 4  # 1 fichier x 4 prismes (dispatcher plat)


def test_run_audit_bad_json_safe(tmp_path: Path):
    root = _src(tmp_path)
    pool = _FakePool("ceci n'est pas du JSON")
    rep = _run(["auth.py"], root, lenses=["security"], pool=pool)
    assert rep["kept"] == [] and rep["dropped"] == 0  # JSON cassé -> 0 finding, pas de crash


def test_run_audit_no_files():
    rep = _run([], ".", lenses=["security"], pool=_FakePool("{}"))
    assert rep["kept"] == []
