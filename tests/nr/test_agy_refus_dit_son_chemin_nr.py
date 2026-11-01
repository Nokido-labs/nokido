# -*- coding: utf-8 -*-
"""NR -- un refus du bac d'AGY dit QUOI a ete refuse, pas seulement l'outil (30/10).

4 taches ANTIGRAVITY du 30/10 ont rendu « actions refusees par le bac : read_file » sans le chemin : impossible de
savoir si AGY lisait hors de son worktree (chemin absolu du depot principal ? pointeur `.git` du worktree ?).
`lire_sortie_agy` ne gardait que la cle `action` de chaque refus. Contrat : les autres champs du refus (chemin,
arguments) sont rendus, tronques.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_task_executor as te  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def test_le_refus_porte_son_chemin():
    raw = json.dumps({"status": "SUCCESS", "response": "",
                      "denied_actions": [{"action": "read_file",
                                          "path": "C:/depot/.git/worktrees/antigravity/HEAD"}]})
    ok, detail = te.lire_sortie_agy(raw)
    assert ok is False
    assert "read_file" in detail and ".git/worktrees/antigravity/HEAD" in detail, detail


def test_un_refus_texte_reste_lisible():
    raw = json.dumps({"status": "SUCCESS", "response": "", "denied_actions": ["unsandboxed RunCommand"]})
    ok, detail = te.lire_sortie_agy(raw)
    assert ok is False and "unsandboxed RunCommand" in detail
