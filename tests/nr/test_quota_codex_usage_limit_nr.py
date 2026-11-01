"""NR -- recette Codex owner 28/10 (codex-1-9065795) : le quota ChatGPT epuise de Codex n'etait pas reconnu.

Message reel : session/prompt -> -32603 « You’ve hit your usage limit. To continue using Codex ... try again at
Nov 17th, 2026 1:38 PM. », codexErrorInfo usageLimitExceeded. _RE_QUOTA ne le voyait pas : une tache confiee
a Codex echouait sans repli.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as E  # noqa: E402

MESSAGE_REEL = ("session/prompt -> {'code': -32603, 'message': 'Internal error', 'data': {'message': "
                "'You’ve hit your usage limit. To continue using Codex and get access to GPT-5.3-Codex, start a "
                "free trial of Plus today, or try again at Nov 17th, 2026 1:38 PM.', "
                "'codexErrorInfo': 'usageLimitExceeded'}}")


def test_quota_codex_reel_reconnu():
    assert E._RE_QUOTA.search(MESSAGE_REEL)


def test_code_usage_limit_exceeded_seul_reconnu():
    assert E._RE_QUOTA.search("codexErrorInfo: usageLimitExceeded")


def test_texte_ordinaire_non_reconnu():
    assert not E._RE_QUOTA.search("la limite d'usage de la memoire est documentee dans le module")
