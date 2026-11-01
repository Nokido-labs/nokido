# -*- coding: utf-8 -*-
"""NR -- la consigne d'AGY exige des chemins ABSOLUS pour LIRE (30/10).

Sonde job_2e57e5b4 (docs/enquetes/sonde_lecture_agy_20261030.md, commit 18b65b0c6) : `read_file` d'AGY refuse tout
chemin RELATIF (« declaring permissions: failed to parse path: app/forge_ssot.py must be an absolute path ») et lit
sans probleme le meme fichier en chemin absolu sous son worktree, `.git` compris. 4 taches du 30/10 sont mortes la :
AGY ecrivait son test (ecriture deja en absolu), echouait a lire le code, rendait une reponse vide.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_task_executor as te  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def test_la_consigne_impose_la_lecture_en_chemin_absolu():
    wd = r"C:\x\nokido_worktrees\taches\antigravity_abc"
    c = te._consigne_agy(wd)
    assert "LIRE" in c.upper() and "ABSOLU" in c.upper()
    assert wd + "\\app\\" in c, "un exemple de chemin absolu de lecture sous le worktree doit etre donne"
