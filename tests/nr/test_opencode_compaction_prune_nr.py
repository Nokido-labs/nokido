# -*- coding: utf-8 -*-
"""NR -- 30/10 (reglages des CLI, preuve mot pour mot : config.mdx d'OpenCode « prune - Remove old tool outputs to save
tokens (default: false) ») : chaque instance OpenCode deleguee a la compaction ACTIVE avec elagage des anciennes
sorties d'outils (masquage des observations), que le modele soit cloud, local ou celui par defaut."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as fte  # noqa: E402


def test_compaction_avec_elagage_pour_tout_modele():
    for modele in ("ollama/qwen2.5-coder:7b", "ollama_cloud/gpt-oss:120b", "groq/openai/gpt-oss-120b", ""):
        cfg = fte._config_opencode_instance("OPENCODE_GLM", modele)
        assert cfg.get("compaction") == {"auto": True, "prune": True}, modele


def test_le_shell_reste_refuse():
    assert fte._config_opencode_instance("OPENCODE_GLM", "")["permission"]["bash"] == "deny"
