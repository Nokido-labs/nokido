"""NR -- chaque tache deleguee part d'alpha, par la brique EXISTANTE `forge_worktree.sync` (owner 17/10).

Mesure 17/10 ~00:30 : le worktree d'AGY etait sur agy/lot-20261016-soir, 60 commits derriere alpha ; une tache serait
partie du code de la veille sans que rien ne le dise. Owner : « il faut que Nokido soit en mesure de debloquer la
situation ». J'avais d'abord ecrit `_partir_d_alpha` dans l'executeur SANS consulter le domaine : doublon de
`tools/forge_worktree.sync` (rebase de la branche de l'agent sur alpha, meme worktree `nokido_worktrees/<agent>`,
mesure). Owner : « respecte l'anti dedup ». L'executeur appelle donc `forge_worktree.sync` ; la brique est ETENDUE d'un
trou reel : sur conflit, `git rebase` s'arretait EN PLEIN REBASE et laissait le worktree casse pour l'agent, contrairement
a sa docstring (« NON destructif si conflit »).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402
import forge_worktree as W  # noqa: E402


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True, errors="replace").stdout.strip()


@pytest.fixture
def wt(tmp_path, monkeypatch):
    """Depot principal (alpha a 2 commits) et worktree LIE de l'agent `antigravity`, sur `lot`, au premier."""
    p = tmp_path / "principal"
    p.mkdir()
    _git(p, "init", "-q", "-b", "alpha")
    _git(p, "config", "user.email", "nr@test")
    _git(p, "config", "user.name", "nr")
    (p / "a.txt").write_text("1\n", encoding="utf-8")
    _git(p, "add", "a.txt")
    _git(p, "commit", "-q", "-m", "un")
    _git(p, "branch", "lot")
    (p / "a.txt").write_text("2\n", encoding="utf-8")
    _git(p, "commit", "-q", "-am", "deux")
    racine = tmp_path / "wts"
    racine.mkdir()
    _git(p, "worktree", "add", "-q", str(racine / "antigravity"), "lot")
    monkeypatch.setattr(W, "WT_ROOT", racine)
    return racine / "antigravity"


def _en_plein_rebase(d) -> bool:
    return any(Path(_git(d, "rev-parse", "--git-path", x)).is_absolute() and Path(_git(d, "rev-parse", "--git-path", x)).exists()
               or (Path(d) / _git(d, "rev-parse", "--git-path", x)).exists() for x in ("rebase-merge", "rebase-apply"))


def test_un_worktree_en_retard_est_rebase_sur_alpha(wt):
    r = W.sync("antigravity")
    assert r.get("rebased") is True, r
    subprocess.run(["git", "-c", "safe.directory=*", "-C", str(wt), "merge-base", "--is-ancestor", "alpha", "HEAD"],
                   check=True)


def test_un_marqueur_indexe_ne_bloque_pas_le_rebase_et_survit(wt):
    """Mesure 17/10 ~19 h 40 : worktree opencode_nemotron reste sur 4048d8ff6 (alpha bien plus loin) ; seul `.nokido.agent`
    INDEXE (A) -- `git rebase` refuse un index non vide, donc la tache ne partait plus d'alpha. Le marqueur est garde."""
    (wt / ".nokido.agent").write_text("OPENCODE_NEMOTRON\n", encoding="utf-8")
    _git(wt, "add", ".nokido.agent")
    r = W.sync("antigravity")
    assert r.get("rebased") is True, r
    subprocess.run(["git", "-c", "safe.directory=*", "-C", str(wt), "merge-base", "--is-ancestor", "alpha", "HEAD"],
                   check=True)
    assert (wt / ".nokido.agent").read_text(encoding="utf-8").strip() == "OPENCODE_NEMOTRON"
    assert not _en_plein_rebase(wt)


# Decision owner 19/10 (« preserver puis repartir ») : l'invariant « un travail en cours n'est jamais touche » laissait
# GLM (rebase en conflit), GPTOSS (non suivis ecrases par le checkout) et NEMOTRON (non indexes) COINCES : chaque tache
# partait d'une base perimee au milieu des restes et ne pouvait pas etre commitee (« travail laisse non committe »).
# Nouvel invariant : JAMAIS PERDU -- tout l'etat part sur preserve/<agent>-<horodatage>, puis la branche repart d'alpha.

def _sur_alpha(d) -> bool:
    return _git(d, "rev-parse", "HEAD") == _git(d, "rev-parse", "alpha")


def _preserve(r, d, fichier) -> str:
    assert r.get("preserve", "").startswith("preserve/antigravity-"), r
    return _git(d, "show", "%s:%s" % (r["preserve"], fichier))


def test_un_conflit_est_preserve_puis_la_branche_repart_d_alpha(wt):
    (wt / "a.txt").write_text("travail de l'agent\n", encoding="utf-8")
    _git(wt, "commit", "-q", "-am", "travail")
    r = W.sync("antigravity")
    assert r.get("rebased") is True and r.get("assaini") is True, r
    assert not _en_plein_rebase(wt)
    assert _sur_alpha(wt) and _git(wt, "rev-parse", "--abbrev-ref", "HEAD") == "lot"
    assert _preserve(r, wt, "a.txt") == "travail de l'agent"


def test_un_travail_en_cours_est_preserve_jamais_perdu(wt):
    (wt / "a.txt").write_text("en cours\n", encoding="utf-8")
    r = W.sync("antigravity")
    assert r.get("rebased") is True and r.get("assaini") is True, r
    assert _sur_alpha(wt) and (wt / "a.txt").read_text(encoding="utf-8") == "2\n"
    assert _preserve(r, wt, "a.txt") == "en cours"


def test_un_non_suivi_qui_bloque_est_preserve_et_le_marqueur_survit(wt, tmp_path):
    p = tmp_path / "principal"
    (p / "b.txt").write_text("alpha\n", encoding="utf-8")
    _git(p, "add", "b.txt")
    _git(p, "commit", "-q", "-m", "trois")
    (wt / "b.txt").write_text("reste non suivi\n", encoding="utf-8")
    (wt / ".nokido.agent").write_text("ANTIGRAVITY\n", encoding="utf-8")
    r = W.sync("antigravity")
    assert r.get("rebased") is True, r
    assert _sur_alpha(wt) and (wt / "b.txt").read_text(encoding="utf-8") == "alpha\n"
    assert _preserve(r, wt, "b.txt") == "reste non suivi"
    assert (wt / ".nokido.agent").read_text(encoding="utf-8").strip() == "ANTIGRAVITY"


def test_l_executeur_delegue_a_la_brique_existante(monkeypatch):
    vu = []
    monkeypatch.setattr(W, "sync", lambda agent: vu.append(agent) or {"agent": agent, "rebased": True, "msg": ""})
    T._preparer_worktree("ANTIGRAVITY")
    T._preparer_worktree("MISTRAL")
    assert vu == ["antigravity", "mistral"]
    assert not hasattr(T, "_partir_d_alpha"), "le doublon de forge_worktree.sync doit avoir quitte l'executeur"
