"""NR 31/10 (owner) -- taches collaboratives : DISTINCTES = cloisonnees ; un travail 3 se NOURRIT des travaux 1 et 2.

Owner : « le scope sur task.db doit etre bien defini dynamiquement. si des taches collaboratives sont distinctes il faut
bien les scinder. un travail en groupe 1 et un travail 2 peut ensuite nourrir un travail 3 ».
- C (chainage) : `depend_de` (JSON) en base ; une tache n'est servie qu'une fois TOUTES ses entrees livrees (sinon
  BLOQUE_PAR_DEPENDANCE, jamais « morte ») ; son worktree nait d'alpha AVEC les branches de ses entrees fusionnees --
  les livrables amont sont physiquement chez elle, aucune lecture croisee n'est necessaire. Conflit = refus nomme.
- B (portee) : un executeur lit le depot et SON worktree de tache ; le worktree d'une autre tache lui est refuse.
Depot git JETABLE (tmp_path), base tasks.db factice.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as E  # noqa: E402
import forge_worktree as W  # noqa: E402


def _g(d, *a):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.hooksPath=NUL",
                           "-C", str(d), *a], capture_output=True, text=True, errors="replace", encoding="utf-8", env=env)


@pytest.fixture()
def depot(tmp_path):
    d = tmp_path / "Nokido"
    d.mkdir()
    _g(d, "init", "-q", "-b", "alpha")
    for k, v in (("user.name", "t"), ("user.email", "t@t"), ("core.hooksPath", "NUL")):
        _g(d, "config", k, v)
    (d / "base.txt").write_text("base")
    _g(d, "add", "base.txt")
    assert _g(d, "commit", "-q", "-m", "base").returncode == 0
    return d


@pytest.fixture(autouse=True)
def _isole(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_SAUVEGARDES", tmp_path / "sauvegardes", raising=False)


@pytest.fixture()
def base(tmp_path, monkeypatch):
    chemin = tmp_path / "tasks.db"
    c = sqlite3.connect(chemin)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT, agent TEXT, status TEXT, result TEXT,"
              " created_at TEXT, updated_at TEXT, job_id TEXT)")
    c.commit()
    c.close()
    monkeypatch.setattr(E, "_db", lambda: sqlite3.connect(chemin))
    return chemin


def _tache(chemin, tid, statut, agent="ANTIGRAVITY", depend_de=None):
    c = sqlite3.connect(chemin)
    try:
        c.execute("ALTER TABLE tasks ADD COLUMN depend_de TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute("INSERT INTO tasks (id, description, agent, status, created_at, job_id, depend_de) VALUES (?,?,?,?,?,?,?)",
              (tid, "x", agent, statut, tid, tid, json.dumps(depend_de) if depend_de else None))
    c.commit()
    c.close()


def _livrer(depot, agent, tid, fichier, contenu="v"):
    wt = E._wt_tache_ouvrir(agent, tid, depot=depot, racine=depot.parent / "nokido_worktrees" / "taches")
    (wt / fichier).write_text(contenu)
    _g(wt, "add", fichier)
    assert _g(wt, "commit", "-q", "-m", tid).returncode == 0
    assert E._wt_tache_retirer(wt, depot=depot)


# ---------------------------------------------------------------- C : chainage
def test_entrees_livrees_tache_prete(base):
    _tache(base, "t1", "done")
    _tache(base, "t2", "done")
    _tache(base, "t3", "pending", depend_de=["t1", "t2"])
    ok, motif = E._dependances_pretes(sqlite3.connect(base), "t3")
    assert ok and not motif


def test_entree_en_cours_bloque_sans_tuer(base):
    _tache(base, "t1", "done")
    _tache(base, "t2", "running")
    _tache(base, "t3", "pending", depend_de=["t1", "t2"])
    ok, motif = E._dependances_pretes(sqlite3.connect(base), "t3")
    assert not ok and "BLOQUE_PAR_DEPENDANCE" in motif and "t2" in motif


def test_entree_echouee_ou_inconnue_bloque(base):
    _tache(base, "t1", "failed")
    _tache(base, "t3", "pending", depend_de=["t1", "fantome"])
    ok, motif = E._dependances_pretes(sqlite3.connect(base), "t3")
    assert not ok and "t1" in motif and "fantome" in motif


def test_tache_sans_entree_prete(base):
    _tache(base, "t9", "pending")
    assert E._dependances_pretes(sqlite3.connect(base), "t9") == (True, "")


def test_fetch_batch_ne_sert_pas_une_tache_bloquee(base):
    _tache(base, "t1", "running")
    _tache(base, "t2", "pending")
    _tache(base, "t3", "pending", depend_de=["t1"])
    ids = [r[0] for r in E._fetch_batch(sqlite3.connect(base), "ANTIGRAVITY")]
    assert "t2" in ids and "t3" not in ids


def test_travail_3_nait_avec_les_livrables_1_et_2(depot):
    _livrer(depot, "ANTIGRAVITY", "job_aaaa1111_1", "etude.md")
    _livrer(depot, "MISTRAL", "job_bbbb2222_2", "wiki.md")
    wt = E._wt_tache_ouvrir("CLAUDE_HEADLESS", "job_cccc3333_3", depot=depot,
                            racine=depot.parent / "nokido_worktrees" / "taches",
                            depend_de=["job_aaaa1111_1", "job_bbbb2222_2"])
    assert (wt / "etude.md").exists() and (wt / "wiki.md").exists()


def test_la_consigne_nomme_les_entrees_fusionnees(depot):
    """L'agent du travail 3 doit SAVOIR ce qu'il a recu : la consigne fixe liste ses entrees (id, branche)."""
    _livrer(depot, "ANTIGRAVITY", "job_aaaa1111_1", "etude.md")
    wt = E._wt_tache_ouvrir("CLAUDE_HEADLESS", "job_cccc3333_3", depot=depot,
                            racine=depot.parent / "nokido_worktrees" / "taches", depend_de=["job_aaaa1111_1"])
    texte = E._texte_entrees(wt)
    assert "job_aaaa1111_1" in texte and "tache/antigravity/" in texte
    assert texte in E._consigne_agy(str(wt))
    assert E._texte_entrees(depot) == ""  # sans entree : rien d'ajoute (prefixe de cache inchange)


def test_entrees_en_conflit_refus_nomme(depot):
    _livrer(depot, "ANTIGRAVITY", "job_aaaa1111_1", "meme.md", "un")
    _livrer(depot, "MISTRAL", "job_bbbb2222_2", "meme.md", "deux")
    with pytest.raises(E.WorktreeTacheRefuse) as exc:
        E._wt_tache_ouvrir("CLAUDE_HEADLESS", "job_cccc3333_3", depot=depot,
                           racine=depot.parent / "nokido_worktrees" / "taches",
                           depend_de=["job_aaaa1111_1", "job_bbbb2222_2"])
    assert "job_bbbb2222_2" in str(exc.value)


# ---------------------------------------------------------------- B : portee
def test_court_tache_une_seule_definition():
    tid = "job_f74513a2_1793430153_claude_handoff_next"
    assert W.court_tache(tid) == E._wt_court(tid)


def test_portee_de_lecture_d_un_executeur(tmp_path):
    racine = tmp_path / "nokido_worktrees"
    depot = tmp_path / "Nokido"
    a = racine / "taches" / ("antigravity_%s" % W.court_tache("job_mien"))
    b = racine / "taches" / ("mistral_%s" % W.court_tache("job_autre"))
    for d in (a, b, depot):
        d.mkdir(parents=True)
    p = W.portee_lecture("ANTIGRAVITY", ["job_mien"], wt_root=racine, depot=depot)
    assert W.dans_portee(a / "x.md", p) and W.dans_portee(depot / "app" / "y.py", p)
    assert not W.dans_portee(b / "x.md", p)


def test_owner_hors_portee_d_executeur(tmp_path):
    assert W.portee_lecture("CLAUDE", [], wt_root=tmp_path, depot=tmp_path) is None


# ---------------------------------------------------------------- cote hub (registre)
def test_hub_refuse_a_un_executeur_le_worktree_d_une_autre_tache(tmp_path, monkeypatch):
    from nokido_agent.app import forge_mcp_registry as M
    from nokido_agent.tools import forge_worktree as WN  # le module que le REGISTRE importe (deux noms d'import)
    racine = tmp_path / "nokido_worktrees"
    autre = racine / "taches" / ("mistral_%s" % W.court_tache("job_autre"))
    autre.mkdir(parents=True)
    monkeypatch.setattr(WN, "WT_ROOT", racine)
    monkeypatch.setattr(WN, "ROOT", tmp_path / "Nokido")
    monkeypatch.setattr(WN, "taches_en_cours", lambda agent, tasks_db=None: ["job_mien"])
    refus = M._hors_portee("ANTIGRAVITY", autre / "x.md")
    assert refus and "portee" in refus.lower()
    assert M._hors_portee("CLAUDE", autre / "x.md") is None  # owner : inchange


def test_assign_normalise_et_valide_depend_de():
    from nokido_agent.app import forge_mcp_registry as M
    connus = {"t1", "t2"}
    assert M._normaliser_depend_de("t1, t2", "t3", connus.__contains__) == (["t1", "t2"], None)
    assert M._normaliser_depend_de(["t1"], "t3", connus.__contains__) == (["t1"], None)
    assert M._normaliser_depend_de(None, "t3", connus.__contains__) == ([], None)
    # 31/10 08:49, epreuve reelle : un client au schema en cache envoie la liste en CHAINE JSON
    assert M._normaliser_depend_de('["t1", "t2"]', "t3", connus.__contains__) == (["t1", "t2"], None)
    _, err = M._normaliser_depend_de(["t3"], "t3", connus.__contains__)
    assert err and "elle-meme" in err
    _, err = M._normaliser_depend_de(["fantome"], "t3", connus.__contains__)
    assert err and "fantome" in err
