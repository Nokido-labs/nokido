"""NR 24/10 -- commit en deux temps : une livraison qui touche tests/** ET du code donne DEUX commits (RED = tests
seuls, puis le reste), avec la preuve « rouge » rejouee sur l'arbre du commit RED consignee dans le 2e message."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402


def _git(wt, *args):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(wt), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)


def _repo(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    assert _git(wt, "init", "-q").returncode == 0
    _git(wt, "config", "user.email", "t@t")
    _git(wt, "config", "user.name", "t")
    _git(wt, "config", "core.hooksPath", str(tmp_path / "nohooks"))
    (wt / "base.txt").write_text("base\n", encoding="utf-8")
    _git(wt, "add", "base.txt")
    assert _git(wt, "commit", "-q", "-m", "base").returncode == 0
    return wt


def _ecrire(wt, rel, txt):
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, encoding="utf-8")


def _tracked(wt, rev):
    return set(_git(wt, "show", "--name-only", "--format=", rev).stdout.split())


def _sales(wt):
    return "\n".join(l for l in _git(wt, "status", "--porcelain").stdout.splitlines() if "__pycache__" not in l)


def _n(wt):
    return int(_git(wt, "rev-list", "--count", "HEAD").stdout)


def test_separation_tests_et_code_en_deux_commits_preuve_rouge(tmp_path):
    wt = _repo(tmp_path)
    _ecrire(wt, "tests/test_m.py", "from m import f\n\ndef test_f():\n    assert f() == 1\n")
    _ecrire(wt, "m.py", "def f():\n    return 1\n")
    note = T._committer_pour_agent(str(wt), "t1", 'ok {"commit_message":"feat(m): ajoute f"}', "X")
    assert note and "2 commits" in note, note
    assert _n(wt) == 3
    assert _tracked(wt, "HEAD~1") == {"tests/test_m.py"}
    assert _tracked(wt, "HEAD") == {"m.py"}
    sujet_red = _git(wt, "log", "-1", "--format=%s", "HEAD~1").stdout
    assert sujet_red.startswith("test(") and "RED --" in sujet_red
    corps_green = _git(wt, "log", "-1", "--format=%B", "HEAD").stdout
    assert "ROUGE" in corps_green and "preuve" in corps_green.lower()
    assert not _sales(wt)


def test_tests_deja_verts_sont_signales_sans_refus(tmp_path):
    wt = _repo(tmp_path)
    _ecrire(wt, "tests/test_ok.py", "def test_ok():\n    assert True\n")
    _ecrire(wt, "m.py", "X = 1\n")
    note = T._committer_pour_agent(str(wt), "t2", "fait", "X")
    assert note and "2 commits" in note
    assert "DEJA VERTS" in _git(wt, "log", "-1", "--format=%B").stdout


def test_tests_seuls_un_seul_commit(tmp_path):
    wt = _repo(tmp_path)
    _ecrire(wt, "tests/test_a.py", "def test_a():\n    assert True\n")
    note = T._committer_pour_agent(str(wt), "t3", "fait", "X")
    assert note and "commit executeur de 1 fichier" in note
    assert _n(wt) == 2


def test_code_seul_un_seul_commit(tmp_path):
    wt = _repo(tmp_path)
    _ecrire(wt, "m.py", "X = 1\n")
    note = T._committer_pour_agent(str(wt), "t4", "fait", "X")
    assert note and "commit executeur de 1 fichier" in note
    assert _n(wt) == 2


def test_aucun_fichier_perdu_et_juge_lit_les_deux_commits(tmp_path):
    wt = _repo(tmp_path)
    avant = T._etat_git(str(wt))
    _ecrire(wt, "tests/test_m.py", "from m import f\n\ndef test_f():\n    assert f() == 1\n")
    _ecrire(wt, "m.py", "def f():\n    return 1\n")
    _ecrire(wt, "tools/z.py", "Z = 1\n")
    T._committer_pour_agent(str(wt), "t5", "fait", "X")
    assert not _sales(wt)
    vus = set(_git(wt, "ls-files").stdout.split())
    assert {"tests/test_m.py", "m.py", "tools/z.py"} <= vus
    effet = T._effet_observe(str(wt), avant)
    assert "commits produits : 2" in effet, effet
