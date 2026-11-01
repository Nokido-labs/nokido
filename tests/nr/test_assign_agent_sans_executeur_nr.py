# -*- coding: utf-8 -*-
"""NR -- owner 30/10 : `task assign agent=OPENCODE` acceptee sans un mot alors qu'aucun executeur ne porte ce nom
(OPENCODE_DEFAUT2..5, _GPTOSS, _NEMOTRON, _GLM) : 25 min orpheline. L'assignation AVERTIT (non bloquant) et
propose les executeurs proches ; un agent servi n'avertit pas ; un services.toml illisible ne dit rien (INCONNU)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.forge_mcp_registry import ToolRegistry  # noqa: E402

TOML = '''
[[services]]
name = "A"
args = ["x.py", "--agent", "OPENCODE_GLM"]
[[services]]
name = "B"
args = ["x.py", "--agent", "OPENCODE_DEFAUT2"]
[[services]]
name = "C"
args = ["x.py", "--agent", "ANTIGRAVITY"]
'''


def _reg(tmp_path, toml=TOML):
    if toml is not None:
        d = tmp_path / "proxy_deno" / "core"
        d.mkdir(parents=True)
        (d / "services.toml").write_text(toml, encoding="utf-8")
    return ToolRegistry(root_dir=tmp_path)


def test_agent_sans_executeur_avertit_et_propose(tmp_path):
    a = _reg(tmp_path)._avertissement_agent("OPENCODE")
    assert a and "OPENCODE" in a
    assert "OPENCODE_DEFAUT2" in a and "OPENCODE_GLM" in a


def test_agent_servi_n_avertit_pas(tmp_path):
    assert _reg(tmp_path)._avertissement_agent("ANTIGRAVITY") is None


def test_toml_illisible_ne_dit_rien(tmp_path):
    assert _reg(tmp_path, toml=None)._avertissement_agent("OPENCODE") is None
