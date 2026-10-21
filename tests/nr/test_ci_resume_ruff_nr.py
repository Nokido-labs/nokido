"""NR -- le gate ruff de la CI locale rend un RESUME lisible (codes comptes, fichiers), pas seulement des lignes brutes.

Item SSoT roadmap_p1_ci_github_apres_0212_20261015 : « resume ruff lisible dans le journal (aujourd'hui lignes brutes
seules, tools/ci_local.py) ». `resume_ruff` lit les deux formats de ruff (complet `--> f:l:c` et concis `f:l:c: CODE`) ;
sortie sans violation -> None (rien a resumer, jamais un faux « 0 »).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import ci_local as C  # noqa: E402

COMPLET = """F821 Undefined name `foo`
 --> app/forge_x.py:12:5
   |
E999 SyntaxError: unexpected indent
 --> tools/forge_y.py:3:1
F821 Undefined name `bar`
 --> app/forge_x.py:40:9
Found 3 errors."""

CONCIS = "app/forge_x.py:12:5: F821 Undefined name `foo`\ntools/forge_y.py:3:1: E999 SyntaxError"


def test_resume_du_format_complet():
    r = C.resume_ruff(COMPLET)
    assert r.startswith("ruff : 3 violation(s)") and "F821x2" in r and "E999x1" in r
    assert "app/forge_x.py" in r and "tools/forge_y.py" in r


def test_resume_du_format_concis():
    r = C.resume_ruff(CONCIS)
    assert r.startswith("ruff : 2 violation(s)") and "F821x1" in r and "E999x1" in r


def test_rien_a_resumer_rend_none():
    assert C.resume_ruff("All checks passed!") is None


def test_la_ci_imprime_le_resume_apres_le_gate_ruff():
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    i = src.index('"ruff critique (E9,F63,F7)"')
    assert "resume_ruff(" in src[i:i + 1500]
