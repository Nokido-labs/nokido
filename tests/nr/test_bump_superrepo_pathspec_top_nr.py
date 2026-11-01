"""NR -- le commit du bump ne part qu'avec ses gitlinks, meme lance depuis un CWD hors de l'arbre (1/11).

MESURE du 31/10 : `forge_bump_superrepo.py --commit` (LaForgeTrusted) a indexe `Nokido -> 02cde886` puis rendu
`error: pathspec 'Nokido' did not match any file(s) known to git` ; le bump a ete fini en git direct (c8586a7).
HYPOTHESE REFUTEE ICI : un CWD hors de l'arbre avec `--git-dir` + `--work-tree` ne casse PAS le pathspec (ce test
passe sur le code d'origine). La cause tient au compte LaForgeTrusted (ACL / lecture du submodule) : ILLISIBLE depuis
le bac, a instruire sous ce compte (GIT_TRACE). Ce test garde la propriete reelle : seul le pointeur part.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_bump_superrepo as S  # noqa: E402


def _git(depot, *a):
    return subprocess.run(["git", "-c", "safe.directory=*", "-c", "user.name=t", "-c", "user.email=t@t",
                           "-C", str(depot), *a], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True)


def _depot_gitlink(tmp_path, monkeypatch):
    """Superrepo jetable dont `Nokido` est un GITLINK (mode 160000) indexe, sans dossier lisible -- comme sous
    LaForgeTrusted le 31/10 et le 1/11 (pathspec 'Nokido' did not match, deux fois)."""
    depot = tmp_path / "superrepo"
    depot.mkdir()
    _git(depot, "init", "-q")
    (depot / "AUTRE.md").write_text("a\n", encoding="utf-8")
    _git(depot, "add", "AUTRE.md")
    _git(depot, "update-index", "--add", "--cacheinfo", "160000,%s,Nokido" % ("1" * 40))
    _git(depot, "commit", "-q", "-m", "init")
    _git(depot, "update-index", "--cacheinfo", "160000,%s,Nokido" % ("2" * 40))
    monkeypatch.setattr(S, "SUPERREPO", depot)
    monkeypatch.setattr(S, "_auth", lambda: ([], dict(os.environ)))
    return depot


def test_un_gitlink_indexe_sans_dossier_se_commite(tmp_path, monkeypatch):
    depot = _depot_gitlink(tmp_path, monkeypatch)
    r = S._committer_pointeurs(["Nokido"], "chore(sm): bump gitlink Nokido")
    assert r.returncode == 0, r.stderr
    assert _git(depot, "rev-parse", "HEAD:Nokido").stdout.strip() == "2" * 40


def test_un_gitlink_sans_dossier_ne_part_qu_avec_l_index_de_l_owner_intact(tmp_path, monkeypatch):
    depot = _depot_gitlink(tmp_path, monkeypatch)
    (depot / "AUTRE.md").write_text("b\n", encoding="utf-8")
    _git(depot, "add", "AUTRE.md")                    # ce que l'owner a indexe ne part JAMAIS avec un bump
    r = S._committer_pointeurs(["Nokido"], "chore(sm): bump gitlink Nokido")
    assert r.returncode == 0, r.stderr
    assert _git(depot, "show", "--name-only", "--format=", "HEAD").stdout.split() == ["Nokido"]
    assert _git(depot, "rev-parse", "HEAD:Nokido").stdout.strip() == "2" * 40   # jamais une suppression
    assert _git(depot, "diff", "--cached", "--name-only").stdout.split() == ["AUTRE.md"]


def test_le_commit_des_pointeurs_reussit_depuis_un_cwd_hors_de_l_arbre(tmp_path, monkeypatch):
    depot = tmp_path / "superrepo"
    depot.mkdir()
    _git(depot, "init", "-q")
    (depot / "Nokido").write_text("v1\n", encoding="utf-8")
    (depot / "AUTRE.md").write_text("a\n", encoding="utf-8")
    _git(depot, "add", "Nokido", "AUTRE.md")
    _git(depot, "commit", "-q", "-m", "init")
    (depot / "Nokido").write_text("v2\n", encoding="utf-8")
    (depot / "AUTRE.md").write_text("b\n", encoding="utf-8")
    _git(depot, "add", "Nokido", "AUTRE.md")          # AUTRE.md indexe par l'owner : ne doit PAS partir

    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    monkeypatch.chdir(ailleurs)                        # le CWD du compte LaForgeTrusted, hors de l'arbre
    monkeypatch.setattr(S, "SUPERREPO", depot)
    monkeypatch.setattr(S, "_auth", lambda: ([], dict(os.environ)))

    r = S._committer_pointeurs(["Nokido"], "chore(sm): bump gitlink Nokido")
    assert r.returncode == 0, r.stderr
    dernier = _git(depot, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert dernier == ["Nokido"]                       # le seul pointeur, jamais ce que l'owner avait indexe
    assert "AUTRE.md" in _git(depot, "diff", "--cached", "--name-only").stdout
