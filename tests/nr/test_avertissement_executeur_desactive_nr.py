# -*- coding: utf-8 -*-
"""NR -- un executeur dont tous les services sont desactives (`disabled = true` dans services.toml)
rend un avertissement disabled_by_policy / desactive, au lieu d'accepter en silence (mesure 7/11,
job_23ad5b22 orpheline sur OPENCODE_DEFAUT2 car NokidoTaskExecutorOpencodeDefaut2 etait coupe)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.forge_mcp_registry import ToolRegistry  # noqa: E402

TOML_DESACTIVE = '''
[[service]]
name = "NokidoTaskExecutorOpencodeDefaut2"
disabled = true
args = ["x.py", "--agent", "OPENCODE_DEFAUT2"]

[[service]]
name = "NokidoTaskExecutorOpencodeGlm"
disabled = false
args = ["x.py", "--agent", "OPENCODE_GLM"]

[[service]]
name = "NokidoTaskExecutorAntigravity"
args = ["x.py", "--agent", "ANTIGRAVITY"]
'''


def _reg(tmp_path, toml=TOML_DESACTIVE):
    if toml is not None:
        d = tmp_path / "proxy_deno" / "core"
        d.mkdir(parents=True, exist_ok=True)
        (d / "services.toml").write_text(toml, encoding="utf-8")
    return ToolRegistry(root_dir=tmp_path)


def test_nr_executeur_tout_desactive_rend_disabled_by_policy(tmp_path):
    reg = _reg(tmp_path)
    avert = reg._avertissement_agent("OPENCODE_DEFAUT2")
    assert avert is not None
    assert "OPENCODE_DEFAUT2" in avert
    assert "desactive" in avert.lower() or "disabled" in avert.lower() or "policy" in avert.lower()
    # Propose un executeur eligible parmi les proches ou actifs
    assert "OPENCODE_GLM" in avert


def test_nr_executeur_actif_n_avertit_pas(tmp_path):
    reg = _reg(tmp_path)
    assert reg._avertissement_agent("OPENCODE_GLM") is None
    assert reg._avertissement_agent("ANTIGRAVITY") is None
