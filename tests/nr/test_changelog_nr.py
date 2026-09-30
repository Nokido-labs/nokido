# -*- coding: utf-8 -*-
"""NR — une section de CHANGELOG par push, tiree des commits, sans rien inventer (owner 2026-09-29).

Tient : le classement des sujets (conventional commits, type inconnu dit « Autres »),
l'idempotence (une plage n'est jamais ecrite deux fois), et la couverture mesuree sur un
VRAI depot git : ce qui part sans section est compte, la section posee le couvre, le commit
de changelog lui-meme ne se reclame pas.
"""
import importlib.util
import subprocess
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (l.45)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("forge_changelog", ROOT / "tools" / "forge_changelog.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def test_les_sujets_sont_classes_sans_etre_reformules():
    assert C.rubrique("feat(qualite): rend les docstrings") == ("Nouveautés", "**qualite** : rend les docstrings")
    assert C.rubrique("fix: corrige x") == ("Corrections", "corrige x")
    assert C.rubrique("chore(sm): bump")[0] == "Maintenance"
    assert C.rubrique("Merge truc sans type") == ("Autres", "Merge truc sans type")
    assert C.rubrique("feat(api)!: casse")[1].startswith("⚠️ RUPTURE")
    assert C.est_commit_de_changelog("docs(changelog): push du jour")
    assert not C.est_commit_de_changelog("docs(wiki): page")
    assert not C.est_commit_de_changelog("fix(changelog): corrige le generateur"), (
        "un changement de CODE de portee changelog doit figurer au changelog")


def test_une_plage_n_est_jamais_ecrite_deux_fois():
    s = C.rendre_section([("abc1234", "feat(x): un"), ("def5678", "fix: deux")], "aaaa111", "def5678", "alpha", "2026-09-29")
    assert "### Nouveautés" in s and "### Corrections" in s and "(2 commits)" in s
    t1, ecrit1 = C.inserer("", s)
    t2, ecrit2 = C.inserer(t1, s)
    assert ecrit1 and not ecrit2 and t1 == t2
    assert t1.startswith("# Changelog") and t1.count(C.MARQUEUR) == 1
    s2 = C.rendre_section([("0123abc", "docs: trois")], "def5678", "0123abc", "alpha", "2026-09-30")
    t3, _ = C.inserer(t1, s2)
    assert t3.index("0123abc") < t3.index("abc1234"), "la section la plus recente va en tete"
    assert C.derniere_fin(t3) == "0123abc"


def _git(d, *a):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(d), *a], check=True,
                          capture_output=True, text=True, errors="replace").stdout.strip()


def test_la_couverture_se_mesure_sur_un_vrai_depot(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "nr@local")
    _git(tmp_path, "config", "user.name", "nr")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "chore: base")
    publie = _git(tmp_path, "rev-parse", "HEAD")
    for i, sujet in enumerate(("feat(x): un", "fix(y): deux")):
        (tmp_path / ("f%d.txt" % i)).write_text(sujet, encoding="utf-8")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", sujet)
    assert [s for _, s in C.non_couverts(publie, "HEAD", tmp_path)] == ["feat(x): un", "fix(y): deux"]
    fin = _git(tmp_path, "rev-parse", "--short", "HEAD")
    section = C.rendre_section(C.commits(publie, "HEAD", tmp_path), publie[:7], fin, "alpha", "2026-09-29")
    (tmp_path / C.FICHIER).write_text(C.inserer("", section)[0], encoding="utf-8")
    _git(tmp_path, "add", C.FICHIER)
    _git(tmp_path, "commit", "-q", "-m", "docs(changelog): push du jour")
    assert C.non_couverts(publie, "HEAD", tmp_path) == [], "le commit de changelog ne se reclame pas lui-meme"
    (tmp_path / "g.txt").write_text("g", encoding="utf-8")
    _git(tmp_path, "add", "g.txt")
    _git(tmp_path, "commit", "-q", "-m", "feat: apres coup")
    assert [s for _, s in C.non_couverts(publie, "HEAD", tmp_path)] == ["feat: apres coup"]


def test_une_fin_inscrite_injoignable_ne_vaut_pas_couvert(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "nr@local")
    _git(tmp_path, "config", "user.name", "nr")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "chore: base")
    publie = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    _git(tmp_path, "add", "b.txt")
    _git(tmp_path, "commit", "-q", "-m", "feat: b")
    (tmp_path / C.FICHIER).write_text("# Changelog\n\n<!-- changelog: aaaaaaa..fffffff -->\n", encoding="utf-8")
    assert [s for _, s in C.non_couverts(publie, "HEAD", tmp_path)] == ["feat: b"]
