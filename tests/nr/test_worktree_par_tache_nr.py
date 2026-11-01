"""NR 29/10 -- un worktree PAR TACHE : deux taches simultanees d'un meme agent ne se voient ni ne se commitent.

Mesure : job_3a3347e0 (securite) et job_b6c4b5a1 (strategies) partageaient nokido_worktrees/claude_headless ;
l'executeur a committe les fichiers de l'une sous l'etiquette de l'autre. Depot git JETABLE (tmp_path).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as E  # noqa: E402
import pytest  # noqa: E402


def _g(d, *a):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.hooksPath=NUL",
                           "-C", str(d), *a], capture_output=True, text=True, errors="replace", encoding="utf-8", env=env)


@pytest.fixture()
def depot(tmp_path):
    d = tmp_path / "Nokido"
    d.mkdir()
    _g(d, "init", "-q", "-b", "alpha")
    # identite et hooks LOCAUX au depot jetable : les commits de l'EXECUTEUR (pas seulement ceux de `_g`) doivent
    # passer sous tout compte -- le compte du job n'a pas d'identite git globale (2 NR rouges sous job, 29/10)
    for k, v in (("user.name", "t"), ("user.email", "t@t"), ("core.hooksPath", "NUL")):
        _g(d, "config", k, v)
    (d / "base.txt").write_text("base")
    _g(d, "add", "base.txt")
    assert _g(d, "commit", "-q", "-m", "base").returncode == 0
    return d


@pytest.fixture(autouse=True)
def _isole(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_SAUVEGARDES", tmp_path / "sauvegardes", raising=False)


def _wtroot(depot):
    return depot.parent / "nokido_worktrees" / "taches"


def test_deux_taches_deux_arbres_commits_disjoints(depot):
    a = E._wt_tache_ouvrir("CLAUDE_HEADLESS", "job_3a3347e0", depot=depot, racine=_wtroot(depot))
    b = E._wt_tache_ouvrir("CLAUDE_HEADLESS", "job_b6c4b5a1", depot=depot, racine=_wtroot(depot))
    assert a != b and a.exists() and b.exists()
    (a / "securite.txt").write_text("s")
    (b / "strategie.txt").write_text("t")
    assert not (a / "strategie.txt").exists() and not (b / "securite.txt").exists()
    for wt, tid in ((a, "job_3a3347e0"), (b, "job_b6c4b5a1")):
        n = E._committer_pour_agent(str(wt), tid, "", "CLAUDE_HEADLESS")
        assert n and n.startswith("commit executeur de"), n
    fa = _g(depot, "show", "--name-only", "--format=", "tache/claude_headless/3a3347e0").stdout.split()
    fb = _g(depot, "show", "--name-only", "--format=", "tache/claude_headless/b6c4b5a1").stdout.split()
    assert fa == ["securite.txt"] and fb == ["strategie.txt"]


def test_branche_dediee_et_base_alpha(depot):
    a = E._wt_tache_ouvrir("CODEX", "job_aaaa1111", depot=depot, racine=_wtroot(depot))
    assert _g(a, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "tache/codex/aaaa1111"
    assert _g(a, "rev-parse", "HEAD").stdout == _g(depot, "rev-parse", "alpha").stdout


def test_echec_creation_refuse_motive_sans_repli(depot):
    (depot.parent / "nokido_worktrees").mkdir()
    (depot.parent / "nokido_worktrees" / "taches").write_text("fichier, pas dossier")  # creation impossible
    with pytest.raises(E.WorktreeTacheRefuse) as e:
        E._wt_tache_ouvrir("CLAUDE_HEADLESS", "job_x1", depot=depot, racine=_wtroot(depot))
    assert "worktree" in str(e.value).lower()


def test_retrait_apres_livraison_branche_gardee(depot):
    a = E._wt_tache_ouvrir("CLAUDE_HEADLESS", "job_c0ffee01", depot=depot, racine=_wtroot(depot))
    (a / "f.txt").write_text("x")
    n = E._committer_pour_agent(str(a), "job_c0ffee01", "", "CLAUDE_HEADLESS")
    assert n and n.startswith("commit executeur de"), n
    assert E._wt_tache_retirer(a, depot=depot) is True
    assert not a.exists()
    assert _g(depot, "rev-parse", "--verify", "tache/claude_headless/c0ffee01").returncode == 0


def test_jamais_de_retrait_avec_changements_non_commites(depot):
    a = E._wt_tache_ouvrir("CLAUDE_HEADLESS", "job_dead0001", depot=depot, racine=_wtroot(depot))
    (a / "perdu.txt").write_text("non committe")
    assert E._wt_tache_retirer(a, depot=depot) is False
    assert (a / "perdu.txt").exists()


def test_creation_interrompue_ne_bloque_pas_la_tentative_suivante(depot):
    # 30/10 job_7234db4e : `worktree add` coupe avant l'extraction (tete detachee, index vide) -> lu « travail non
    # committe », chaque reprise de la tache etait REFUSEE. Le reste est retire, la tache repart.
    racine = _wtroot(depot)
    racine.mkdir(parents=True)
    reste = racine / "opencode_defaut3_7234db4e"
    assert _g(depot, "worktree", "add", "--detach", "--no-checkout", str(reste), "alpha").returncode == 0
    # git laisse ce verrou quand `worktree add` est coupe (vu sur le reste reel du 30/10)
    assert _g(depot, "worktree", "lock", "--reason", "initializing", str(reste)).returncode == 0
    (reste / "base.txt").write_text("base")  # extraction partielle
    assert E._chemins_travail(str(reste))  # vu comme du travail avant le correctif
    a = E._wt_tache_ouvrir("OPENCODE_DEFAUT3", "job_7234db4e", depot=depot, racine=racine)
    assert _g(a, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "tache/opencode_defaut3/7234db4e"


def test_worktree_sale_sur_une_autre_branche_reste_refuse(depot):
    a = E._wt_tache_ouvrir("MISTRAL", "job_831823a2", depot=depot, racine=_wtroot(depot))
    _g(a, "checkout", "-q", "-b", "autre")
    (a / "perdu.txt").write_text("x")
    with pytest.raises(E.WorktreeTacheRefuse):
        E._wt_tache_ouvrir("MISTRAL", "job_831823a2", depot=depot, racine=_wtroot(depot))
    assert (a / "perdu.txt").exists()


def test_tete_detachee_avec_index_garde_le_travail(depot):
    a = E._wt_tache_ouvrir("CLAUDE_HEADLESS", "job_dead0002", depot=depot, racine=_wtroot(depot))
    _g(a, "checkout", "-q", "--detach")
    (a / "perdu.txt").write_text("non committe")
    assert E._creation_interrompue(a) is False
    assert E._wt_tache_retirer(a, depot=depot) is False
    assert (a / "perdu.txt").exists()


def test_orphelin_de_plus_de_24h_signale_pas_supprime(depot):
    a = E._wt_tache_ouvrir("CLAUDE_HEADLESS", "job_0ld00001", depot=depot, racine=_wtroot(depot))
    vieux = time.time() - 25 * 3600
    os.utime(a, (vieux, vieux))
    assert E._wt_orphelins(racine=_wtroot(depot)) == [a]
    assert a.exists()


def test_workdir_suit_le_contexte_de_tache(depot):
    a = E._wt_tache_ouvrir("CLAUDE_HEADLESS", "job_beef0001", depot=depot, racine=_wtroot(depot))
    jeton = E._WT_TACHE.set(a)
    try:
        assert E._workdir_claude() == a and Path(E._workdir_agy()) == a
        assert E._workdir_codex() == a and E._workdir_vibe() == a and E._workdir_opencode("OPENCODE_GLM") == a
    finally:
        E._WT_TACHE.reset(jeton)
    assert E._workdir_claude() != a


# 29/10 soir : identifiants REELS `job_<hex>_<ts>_claude_task_assign` -- les 12 derniers caracteres valaient
# `detaskassign` pour TOUTES les taches : 4 taches OPENCODE_DEFAUT* refusees (« deja present »). Et une tache
# coupee par un redemarrage laissait son worktree propre, qui bloquait sa propre reprise.
_ID_A = "job_7cb88566_1793287142_claude_task_assign"
_ID_B = "job_54bd496e_1793287147_claude_task_assign"


def test_ids_reels_meme_suffixe_deux_arbres_distincts(depot):
    a = E._wt_tache_ouvrir("OPENCODE_DEFAUT2", _ID_A, depot=depot, racine=_wtroot(depot))
    b = E._wt_tache_ouvrir("OPENCODE_DEFAUT2", _ID_B, depot=depot, racine=_wtroot(depot))
    assert a != b and a.exists() and b.exists()
    assert "detaskassign" not in a.name and a.name.split("_")[-1].startswith("7cb88566")


def test_reprise_worktree_propre_de_la_meme_tache_reouvert(depot):
    a = E._wt_tache_ouvrir("OPENCODE_DEFAUT3", _ID_A, depot=depot, racine=_wtroot(depot))
    # redemarrage : le `finally` n'a pas tourne, le worktree PROPRE reste
    a2 = E._wt_tache_ouvrir("OPENCODE_DEFAUT3", _ID_A, depot=depot, racine=_wtroot(depot))
    assert a2 == a and a2.exists()


def test_reprise_worktree_sale_travail_preserve(depot):
    # 29/10 : refus = moyen de preserver. 30/10 : le refus faisait tourner la tache en reaffectation (executeur
    # relance pendant la tache) ; la MEME tache sur SA branche reprend dedans, travail intact.
    a = E._wt_tache_ouvrir("OPENCODE_DEFAUT4", _ID_A, depot=depot, racine=_wtroot(depot))
    (a / "travail.txt").write_text("non committe")
    a2 = E._wt_tache_ouvrir("OPENCODE_DEFAUT4", _ID_A, depot=depot, racine=_wtroot(depot))
    assert a2 == a
    assert (a / "travail.txt").read_text() == "non committe"


def test_interrupteur(monkeypatch):
    monkeypatch.setenv("NOKIDO_WORKTREE_PAR_TACHE", "0")
    assert E._wt_tache_arme() is False
    monkeypatch.delenv("NOKIDO_WORKTREE_PAR_TACHE")
    assert E._wt_tache_arme() is True
