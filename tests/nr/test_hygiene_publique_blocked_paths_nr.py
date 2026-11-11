"""NR -- geste owner 1 (8/11) : la vitrine publique ne recoit plus les journaux d'agents, les *.old ni les brouillons.

Rapport docs/rapports/revues_externes_verifiees_20261108.md (A5) : 39 journaux .agents/<role>_<lot>/, SKILL.md.old et 6
brouillons suivis par git partaient dans le dist public (.git-publish-rules.json, profil public). Lit le VRAI fichier de
regles et la VRAIE fonction de filtrage (app/forge_git_egress.py:_path_blocked).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import forge_git_egress as E  # noqa: E402

REGLES = json.loads((ROOT / ".git-publish-rules.json").read_text(encoding="utf-8"))
MOTIFS = REGLES["profiles"]["public"]["blocked_paths"]

BLOQUES = [
    ".agents/auditor_m5/handoff.md", ".agents/explorer_m1/progress.md", ".agents/reviewer_1/BRIEFING.md",
    ".agents/reviewer_2/ORIGINAL_REQUEST.md", ".agents/test_creator_m2/handoff.md", ".agents/victory_auditor/progress.md",
    ".agents/worker_m3_m4/handoff.md", ".agents/worker_remediation/progress.md", ".agents/skills/forge-core/SKILL.md.old",
    "app/debug.py", "app/debug_graph_fix.py", "app/_internal/_cmd_rag_patch.py", "app/_internal/_release_tmp.py",
    "app/_internal/_sandbox_at.py", "app/_internal/_sandbox_at_real.py",
    # geste 6 (audit Z.ai verifie, 8/11) : scripts ponctuels et reliquat orphelin
    "tools/_patch_bridge.py", "tools/_grant_deep_explore.py", ".secrets.baseline",
]
PUBLIES = [
    ".agents/skills/forge-core/SKILL.md", "README.md", "app/forge_hub_handlers.py", "app/_internal/__init__.py",
    "app/forge_git_egress.py", "docs/wiki/Home.md", "tools/forge_patch_audit.py", "tools/forge_secrets_cli.py",
]


@pytest.mark.parametrize("chemin", BLOQUES)
def test_journal_ou_brouillon_bloque(chemin):
    assert E._path_blocked(chemin, MOTIFS) is not None, chemin


@pytest.mark.parametrize("chemin", PUBLIES)
def test_piece_utile_reste_publiee(chemin):
    assert E._path_blocked(chemin, MOTIFS) is None, (chemin, E._path_blocked(chemin, MOTIFS))
