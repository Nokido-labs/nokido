"""NR -- le hook post-commit n'abandonne plus en SILENCE quand son journal est refuse (2026-10-18).

Mesure du 18/10 : aucun `=== post-commit` dans logs/post_commit.log depuis e16af4302 (17/10 23:00) -- 36 commits
jamais indexes ni rafraichis au SSoT. Cause : les commits faits par un compte du hub (`CLAUDE|HUB_SHELL`, compte
LaForgeSbxOffline) n'ont pas le droit d'ouvrir `logs/post_commit.log` / `logs/ssot_maintainer.log` (PermissionError
mesure), et le hook l'avalait : `except Exception: pass` autour de open()+Popen. `sandbox/logs/` est inscriptible
par ce compte (mesure). Le correctif POST_COMMIT ring 3 (d87a1a595) ne pouvait donc pas s'observer.
La fonction est extraite du hook par AST et chargee par importlib : le hook entier s'executerait au chargement.
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / ".githooks" / "post-commit"


def _fonction(nom, tmp_path):
    arbre = ast.parse(HOOK.read_text(encoding="utf-8"))
    noeud = next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == nom)
    mod = tmp_path / "_hook_extrait.py"
    mod.write_text("import os\nimport subprocess\nimport sys\n\n" + ast.unparse(noeud) + "\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_hook_extrait", mod)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return getattr(m, nom)


def test_journal_refuse_replie_sur_sandbox_logs_et_le_dit(tmp_path, capsys):
    racine = tmp_path / "depot"
    racine.mkdir()
    (racine / "logs").write_text("un FICHIER a la place du dossier : toute ouverture dedans echoue")
    f = _fonction("_ouvrir_journal", tmp_path)(str(racine), "post_commit.log")
    try:
        assert Path(f.name) == racine / "sandbox" / "logs" / "post_commit.log"
    finally:
        f.close()
    assert "post_commit.log" in capsys.readouterr().err, "un repli se DIT"


def test_journal_normal_reste_dans_logs(tmp_path):
    racine = tmp_path / "depot"
    racine.mkdir()
    f = _fonction("_ouvrir_journal", tmp_path)(str(racine), "post_commit.log")
    try:
        assert Path(f.name) == racine / "logs" / "post_commit.log"
    finally:
        f.close()


def test_aucun_journal_possible_lance_quand_meme_et_le_dit(tmp_path, capsys):
    racine = tmp_path / "depot"
    racine.mkdir()
    (racine / "logs").write_text("x")
    (racine / "sandbox").write_text("x")
    assert _fonction("_ouvrir_journal", tmp_path)(str(racine), "post_commit.log") is subprocess.DEVNULL
    assert "post_commit.log" in capsys.readouterr().err


def test_les_deux_lancements_de_fond_passent_par_le_repli():
    src = HOOK.read_text(encoding="utf-8")
    assert src.count('_ouvrir_journal(root, "post_commit.log")') == 1
    assert src.count('_ouvrir_journal(root, "ssot_maintainer.log")') == 1
