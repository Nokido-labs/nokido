"""Relecture du 7/11 de la boucle du reconciliateur : deux defauts que ses 11 tests verts ne voyaient pas."""
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_worktree as W  # noqa: E402


def _arbre_git(d: Path) -> Path:
    d.mkdir(parents=True)
    # `.git` en FICHIER, depot git a cote (7/11, CI job_d9e2c3a3500b) : c'est la forme d'un vrai worktree de tache, et
    # sous le basetemp de la CI de reference (~174 car.) `taches/claude_headless_abcd1234/.git/objects/xx/<38>` passait
    # MAX_PATH (262 car.) -- `git commit` rendait rc 1 avant tout appel au reconciliateur. Le nom du worktree, qui porte
    # l'intention (agent a plusieurs mots), est inchange.
    gitdir = d.parent.parent / ("g_" + d.name[-6:])
    for a in (["init", "-q", "--separate-git-dir", str(gitdir)], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", "-c", "safe.directory=*", *a], cwd=d, check=True, capture_output=True, text=True, errors="replace")
    (d / "travail.txt").write_text("non committe\n", encoding="utf-8")
    return d


def _base(tmp_path, agent: str) -> Path:
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT)")
    c.execute("INSERT INTO tasks VALUES ('job_x', ?, 'running')", (agent,))
    c.commit()
    c.close()
    return db


def test_agent_a_plusieurs_mots_tache_en_vol_vue_et_arbre_intact(tmp_path):
    wt = _arbre_git(tmp_path / "taches" / "claude_headless_abcd1234")
    r = W.reconcilier_worktree_orphelin(wt, root=wt, tasks_db=_base(tmp_path, "CLAUDE_HEADLESS"), notifier=lambda *a: "ok")
    assert r["action"] == "ignore" and r["motif"] == "tache_en_vol"
    assert r["agent"] == "claude_headless" and r["court"] == "abcd1234"
    assert (wt / "travail.txt").exists()
    st = subprocess.run(["git", "-c", "safe.directory=*", "status", "--short"], cwd=wt, capture_output=True, text=True, errors="replace").stdout
    assert "travail.txt" in st, "rien ne doit avoir ete committe"


def test_nom_illisible_arbre_intact_et_signale(tmp_path):
    wt = _arbre_git(tmp_path / "taches" / "sansseparateur")
    vus = []
    r = W.reconcilier_worktree_orphelin(wt, root=wt, tasks_db=_base(tmp_path, "AUTRE"), notifier=lambda *a: vus.append(a))
    assert r["motif"] == "nom_illisible" and vus


class _Niveau:
    def __init__(self, niveau, expire=False):
        self.fresh_level, self.expired = niveau, expire


def test_capteur_expire_ne_vaut_pas_zero(monkeypatch):
    from nokido_agent.app import forge_endocrine as en
    import psutil

    monkeypatch.setattr(en, "read_full", lambda nom: _Niveau(0.0, expire=True))
    monkeypatch.setattr(psutil, "virtual_memory", lambda: type("M", (), {"percent": 90.0})())
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None: 10.0)
    assert W.garde_ressources_au_rouge() is True


def test_capteur_frais_bas_laisse_passer(monkeypatch):
    from nokido_agent.app import forge_endocrine as en

    monkeypatch.setattr(en, "read_full", lambda nom: _Niveau(0.1))
    assert W.garde_ressources_au_rouge() is False


def test_tout_muet_abstention(monkeypatch):
    from nokido_agent.app import forge_endocrine as en
    import psutil

    def panne(*a, **k):
        raise RuntimeError("muet")

    monkeypatch.setattr(en, "read_full", panne)
    monkeypatch.setattr(psutil, "virtual_memory", panne)
    assert W.garde_ressources_au_rouge() is True
