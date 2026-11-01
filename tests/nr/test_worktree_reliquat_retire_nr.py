# -*- coding: utf-8 -*-
"""NR -- owner 30/10 : 20 worktrees de tache DESENREGISTRES par git mais dont le dossier restait (~5 100 fichiers,
~1 Go au total ; git : « failed to delete ... Invalid argument »). L'executeur efface le RELIQUAT (plus enregistre,
sans .git, plus vieux que 10 min) en levant la lecture seule, DIT l'erreur Windows exacte de ce qui resiste, et ne
touche JAMAIS un worktree encore enregistre ni un dossier porteur d'un .git."""
from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as fte  # noqa: E402


def _reliquat(racine: Path, nom: str, age_s: float = 3600, avec_git: bool = False) -> Path:
    d = racine / nom
    (d / "sous").mkdir(parents=True)
    f = d / "sous" / "fige.txt"
    f.write_text("x", encoding="utf-8")
    os.chmod(f, stat.S_IREAD)  # lecture seule : la cause classique d'un rmtree refuse
    if avec_git:
        (d / ".git").write_text("gitdir: ailleurs\n", encoding="utf-8")
    t = time.time() - age_s
    os.utime(d, (t, t))
    return d


def test_rmtree_reliquat_leve_la_lecture_seule(tmp_path):
    d = _reliquat(tmp_path, "r1")
    ok, erreurs = fte._rmtree_reliquat(d)
    assert ok and not d.exists()


def test_orphelins_retire_les_reliquats_desenregistres(tmp_path, monkeypatch):
    vieux = _reliquat(tmp_path, "vieux")
    enregistre = _reliquat(tmp_path, "enregistre")
    porteur_git = _reliquat(tmp_path, "porteur", avec_git=True)
    jeune = _reliquat(tmp_path, "jeune", age_s=60)
    monkeypatch.setattr(fte, "_wt_enregistres", lambda depot=None: {enregistre.resolve()})
    fte._wt_orphelins(racine=tmp_path)
    assert not vieux.exists()
    assert enregistre.exists() and porteur_git.exists() and jeune.exists()


def test_enregistrements_illisibles_aucun_effacement(tmp_path, monkeypatch):
    vieux = _reliquat(tmp_path, "vieux")
    monkeypatch.setattr(fte, "_wt_enregistres", lambda depot=None: None)  # git illisible : on ne sait pas
    fte._wt_orphelins(racine=tmp_path)
    assert vieux.exists()
