"""NR -- le cache tiktoken verifie est trouve AUSSI depuis un worktree (CI de reference, executeurs).

Mesure 25/10 (CI de reference 1021fb487) : 3 rouges test_conseiller_souverain_escalade_nr, `ConnectionError ...
/encodings/cl100k_base.tiktoken` sous LaForgeSbxOffline. Cause : forge_llm_router pose CUSTOM_TIKTOKEN_CACHE_DIR vers
<racine>/sandbox/tiktoken_cache SEULEMENT si ce dossier existe ; dans un worktree (preuve de CI, executeurs) il
n'existe pas (non versionne) -> litellm retombe sur son fichier embarque au mauvais contenu -> tiktoken retelecharge
-> echec hors ligne. Contrat : la racine d'abord, sinon le depot PRINCIPAL designe par le fichier `.git` du worktree.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_llm_router as R  # noqa: E402


def test_le_cache_de_la_racine_d_abord(tmp_path):
    (tmp_path / "sandbox" / "tiktoken_cache").mkdir(parents=True)
    assert R._dossier_cache_tiktoken(tmp_path) == tmp_path / "sandbox" / "tiktoken_cache"


def test_depuis_un_worktree_le_cache_du_depot_principal(tmp_path):
    principal = tmp_path / "principal"
    (principal / ".git" / "worktrees" / "preuve").mkdir(parents=True)
    (principal / "sandbox" / "tiktoken_cache").mkdir(parents=True)
    wt = tmp_path / "worktree"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: %s\n" % (principal / ".git" / "worktrees" / "preuve").as_posix(), encoding="utf-8")
    assert R._dossier_cache_tiktoken(wt) == principal / "sandbox" / "tiktoken_cache"


def test_aucun_cache_rend_none(tmp_path):
    assert R._dossier_cache_tiktoken(tmp_path) is None
