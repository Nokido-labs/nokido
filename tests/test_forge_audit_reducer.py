"""tests/test_forge_audit_reducer.py — ForgeAudit : filtre AST-existence + dédup + render."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from forge_audit_reducer import reduce_findings, render_markdown, symbol_matches  # noqa: E402


def _src(tmp: Path) -> Path:
    (tmp / "auth.py").write_text(
        "def login(pw):\n    return pw == 'x'\n\n\nclass Authenticator:\n    def verify(self):\n        return True\n",
        encoding="utf-8",
    )
    return tmp


def test_symbol_matches_lenient():
    real = {"login", "Authenticator", "Authenticator.verify"}
    assert symbol_matches("login", real)
    assert symbol_matches("verify", real)               # méthode courte -> matche Class.verify
    assert symbol_matches("Authenticator.verify", real)
    assert symbol_matches("<module>", real)             # findings module-level OK
    assert not symbol_matches("ghost_function", real)   # inexistant


def test_drops_hallucination(tmp_path: Path):
    root = _src(tmp_path)
    findings = {"auth.py": [
        {"symbol_target": "login", "lens": "security", "severity": "CRITICAL", "issue": "timing"},
        {"symbol_target": "ghost_fn", "lens": "security", "severity": "HIGH", "issue": "halluciné"},
    ]}
    rep = reduce_findings(findings, root)
    assert rep["dropped"] == 1 and len(rep["kept"]) == 1
    assert rep["kept"][0]["symbol_target"] == "login"


def test_keeps_real_method(tmp_path: Path):
    root = _src(tmp_path)
    rep = reduce_findings({"auth.py": [
        {"symbol_target": "verify", "lens": "correctness", "severity": "MEDIUM", "issue": "edge"}]}, root)
    assert len(rep["kept"]) == 1 and rep["dropped"] == 0  # 'verify' matche Authenticator.verify


def test_dedup_same_symbol_lens(tmp_path: Path):
    root = _src(tmp_path)
    rep = reduce_findings({"auth.py": [
        {"symbol_target": "login", "lens": "security", "severity": "HIGH", "issue": "a"},
        {"symbol_target": "login", "lens": "security", "severity": "HIGH", "issue": "b (doublon)"},
    ]}, root)
    assert len(rep["kept"]) == 1  # dédup (fichier, symbole, lens)


def test_sort_by_severity(tmp_path: Path):
    root = _src(tmp_path)
    rep = reduce_findings({"auth.py": [
        {"symbol_target": "login", "lens": "style", "severity": "LOW", "issue": "x"},
        {"symbol_target": "verify", "lens": "security", "severity": "CRITICAL", "issue": "y"},
    ]}, root)
    assert rep["kept"][0]["severity"] == "CRITICAL"  # trié


def test_render_markdown():
    md = render_markdown([{"file": "a.py", "symbol_target": "f", "lens": "security",
                           "severity": "CRITICAL", "issue": "bug", "fix_suggestion": "fix()"}], dropped=2)
    assert "CRITICAL" in md and "`a.py::f`" in md and "fix()" in md and "2 hallucination" in md
    assert render_markdown([], 0).startswith("# ForgeAudit — RAS")
