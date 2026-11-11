"""NR 7/11, INVERSE par choix owner du 8/11 (decision_garde_critique_a_l_integration) -- le commit de l'executeur dans
le WORKTREE de tache n'est plus refuse sur un CRITICAL_FILE : il passe (tracabilite, travail jamais perdu) et la note
porte le marqueur `[CRITICAL_FILE] <fichiers> derogation=oui|non` (derogation relue EN BASE, ring <= 1, jamais la prose).
Le garde bloquant vit a l'entree dans alpha (tests/nr/test_critical_file_garde_a_l_integration_nr.py). Incident payant :
job_010be69e, commit refuse, tache reaffectee a GLM (0 commit), puis le reconciliateur committait le meme contenu 1 s
plus tard par un git brut. Pre-commit : avertissement non bloquant. Depots jetables."""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402

CRIT = "app/forge_rbac.py"


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


def _n(wt):
    return int(_git(wt, "rev-list", "--count", "HEAD").stdout)


def _base(tmp_path, allow=None, ring=1, colonne=True):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT, from_ring INTEGER%s)" % (", allow_critical INTEGER" if colonne else ""))
    if colonne:
        c.execute("INSERT INTO tasks VALUES ('t1', ?, ?)", (ring, allow))
    else:
        c.execute("INSERT INTO tasks VALUES ('t1', ?)", (ring,))
    c.commit()
    c.close()
    return db


def test_deux_temps_critique_sans_derogation_committe_et_marque(tmp_path):
    wt = _repo(tmp_path)
    _ecrire(wt, "tests/test_m.py", "def test_f():\n    assert True\n")
    _ecrire(wt, CRIT, "X = 1\n")
    n0 = _n(wt)
    note = T._committer_deux_temps(str(wt), ["git", "-c", "safe.directory=*", "-C", str(wt)],
                                   ["tests/test_m.py"], [CRIT], "feat: x", "corps", "X")
    assert note.startswith("commit executeur de"), note
    assert "[CRITICAL_FILE]" in note and CRIT in note and "derogation=non" in note, note
    assert not T._RE_COMMIT_REFUSE.search(note), "un commit critique PASSE n'est pas un commit refuse"
    assert _n(wt) == n0 + 2


def test_deux_temps_critique_avec_derogation_accepte(tmp_path):
    wt = _repo(tmp_path)
    _ecrire(wt, "tests/test_m.py", "def test_f():\n    assert True\n")
    _ecrire(wt, CRIT, "X = 1\n")
    note = T._committer_deux_temps(str(wt), ["git", "-c", "safe.directory=*", "-C", str(wt)],
                                   ["tests/test_m.py"], [CRIT], "feat: x", "corps", "X", derogation=True)
    assert note.startswith("commit executeur de"), note
    assert _n(wt) == 3


def test_livraison_critique_committee_derogation_lue_en_base(tmp_path, monkeypatch):
    wt = _repo(tmp_path)
    _ecrire(wt, CRIT, "X = 1\n")
    monkeypatch.setattr(T, "TASKS_DB", _base(tmp_path, allow=None))
    n0 = _n(wt)
    note = T._committer_pour_agent(str(wt), "t1", 'ok {"commit_message":"fix: x"}', "X")
    assert note.startswith("commit executeur de") and "[CRITICAL_FILE]" in note and "derogation=non" in note, note
    assert _n(wt) == n0 + 1 and CRIT in _git(wt, "show", "--name-only", "--format=", "HEAD").stdout
    _ecrire(wt, CRIT, "X = 2\n")
    (tmp_path / "b").mkdir()
    monkeypatch.setattr(T, "TASKS_DB", _base(tmp_path / "b", allow=1))
    note = T._committer_pour_agent(str(wt), "t1", 'ok {"commit_message":"fix: x"}', "X")
    assert note.startswith("commit executeur de") and "derogation=oui" in note, note


def test_derogation_non_hors_ring_ou_sans_colonne(tmp_path, monkeypatch):
    wt = _repo(tmp_path)
    (tmp_path / "r").mkdir()
    (tmp_path / "s").mkdir()
    _ecrire(wt, CRIT, "X = 1\n")
    monkeypatch.setattr(T, "TASKS_DB", _base(tmp_path / "r", allow=1, ring=3))
    assert "derogation=non" in T._committer_pour_agent(str(wt), "t1", "ok", "X")
    _ecrire(wt, CRIT, "X = 2\n")
    monkeypatch.setattr(T, "TASKS_DB", _base(tmp_path / "s", colonne=False))
    assert "derogation=non" in T._committer_pour_agent(str(wt), "t1", "ok", "X")


def test_prose_de_l_agent_ne_deroge_pas(tmp_path, monkeypatch):
    wt = _repo(tmp_path)
    _ecrire(wt, CRIT, "X = 1\n")
    monkeypatch.setattr(T, "TASKS_DB", _base(tmp_path, allow=None))
    note = T._committer_pour_agent(str(wt), "t1", 'allow_critical=true {"commit_message":"fix: x"}', "X")
    assert "derogation=non" in note, note


def test_non_critique_inchange(tmp_path, monkeypatch):
    wt = _repo(tmp_path)
    _ecrire(wt, "m.py", "def f():\n    return 1\n")
    monkeypatch.setattr(T, "TASKS_DB", _base(tmp_path, allow=None))
    note = T._committer_pour_agent(str(wt), "t1", 'ok {"commit_message":"feat: f"}', "X")
    assert note.startswith("commit executeur de"), note


def test_consigne_des_delegues_dit_de_ne_pas_contourner():
    for nom in ("_CONSIGNE_GIT_CODEX", "_CONSIGNE_GIT_VIBE", "_CONSIGNE_GIT_CLAUDE", "_CONSIGNE_GIT_OPENCODE"):
        txt = getattr(T, nom)
        assert "ne se contourne PAS" in txt and "ARRETE-TOI" in txt and "derogation" in txt, nom


def test_hook_precommit_avertit_sans_bloquer(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    (repo / "app").mkdir()
    for rel in ("tools/forge_git_gate.py", "tools/forge_critical_gate.py", "app/forge_mcp_security.py"):
        shutil.copy(ROOT / rel, repo / rel)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / CRIT).write_text("X = 1\n", encoding="utf-8")
    (repo / "autre.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", CRIT, "autre.txt")
    env = dict(os.environ, PYTHONPATH="")
    r = subprocess.run([sys.executable, str(repo / "tools" / "forge_git_gate.py"), "precommit"], cwd=str(repo),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)
    sortie = r.stdout + r.stderr
    assert "[gate][critical][warn]" in sortie and CRIT in sortie, sortie
    assert r.returncode == 0, sortie
