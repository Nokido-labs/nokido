"""NR — `--commit --push` COMMITE avant de publier, et ne publie pas dans le vide.

Mesure 2026-09-19 : `forge_bump_superrepo --commit --push` a annonce « PUBLIE »
sans avoir rien commite. Cause structurelle : le bloc `if args.push:` etait place
AVANT la detection de drift et rendait `return`, si bien que tout le chemin de
commit etait INATTEIGNABLE des que `--push` etait passe.

Le verdict n'etait pas faux, il etait VIDE : sans commit, « le distant porte le
meme commit que le local » est vrai trivialement. Un verdict qui ne sait pas
distinguer FAIT de RIEN A FAIRE ne certifie rien — c'est la meme famille que
`SUITE_COMPLETE` sur une suite qui n'a rien joue.

Cout reel : le gitlink du superrepo est reste sur l'ancien sha, donc un clone
frais n'aurait pas recupere le travail publie dans le submodule. Exactement le
symptome que l'owner signalait.
"""
import importlib
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
fbs = importlib.import_module("forge_bump_superrepo")

SHA = "e5ab874eb3afeb55c96a4f057fca206a0c7ebd1a"


class _Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


@pytest.fixture
def scene(monkeypatch):
    """Un drift MESURE, un distant qui porte deja le sha, git mocke."""
    journal = []

    def _git(*a, timeout=None, arbre=False):
        journal.append(list(a))
        if a[:1] == ("diff",):
            return _Proc(rc=1)          # quelque chose EST stage
        if a[:2] == ("rev-parse", "HEAD"):
            return _Proc(out="superrepo-head\n")
        return _Proc()

    monkeypatch.setattr(fbs, "git", _git)
    monkeypatch.setattr(fbs, "_git_distant", lambda sub, *a, timeout=None: SHA + "\trefs/heads/alpha")
    monkeypatch.setattr(fbs, "publier",
                        lambda branche: (journal.append(["PUBLIER"]),
                                         {"ok": True, "tip_avant": "x", "tip_apres": "y",
                                          "local": "y", "bruit": []})[1])

    faux_di = types.SimpleNamespace(
        _scan_submodule_drift=lambda: [{"target": "Nokido", "kind": "submodule_non_bumpe",
                                        "detail": "pointe X alors que HEAD est Y"}],
        _git=lambda arbre, *a: SHA if a[:2] == ("rev-parse", "HEAD") else "",
        _submodules_declares=lambda: (["Nokido"], ""),
        SUPERREPO=ROOT.parent,
        DERNIERS_ECHECS_GIT=[],
    )
    mod = types.ModuleType("nokido_agent.app.forge_delivery_integrity")
    for k, v in vars(faux_di).items():
        setattr(mod, k, v)
    paquet = types.ModuleType("nokido_agent.app")
    paquet.forge_delivery_integrity = mod
    monkeypatch.setitem(sys.modules, "nokido_agent", types.ModuleType("nokido_agent"))
    monkeypatch.setitem(sys.modules, "nokido_agent.app", paquet)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_delivery_integrity", mod)
    return journal


def _lancer(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["forge_bump_superrepo.py", *argv])
    return fbs.main()


def test_commit_et_push_COMMITE_avant_de_publier(scene, monkeypatch):
    rc = _lancer(monkeypatch, "--commit", "--push", "--message", "sujet court")

    assert rc == 0
    verbes = [a[0] for a in scene]
    assert "commit" in verbes, "aucun commit : c'est le defaut du 2026-09-19"
    assert "PUBLIER" in verbes, "et la publication doit tout de meme avoir lieu"
    assert verbes.index("commit") < verbes.index("PUBLIER"), \
        "l'ordre est une CONDITION : on ne publie que ce qu'on vient de committer"


def test_l_index_recoit_le_gitlink_du_sha_lu(scene, monkeypatch):
    _lancer(monkeypatch, "--commit", "--push", "--message", "sujet court")
    maj = [a for a in scene if a[0] == "update-index"]
    assert maj, "le pointeur doit etre ecrit dans l'index"
    assert SHA in maj[0][-1] and "160000" in maj[0][-1]


def test_push_SEUL_reste_une_publication_pure(scene, monkeypatch):
    """Cas legitime : le commit existe deja, on ne rescanne pas."""
    rc = _lancer(monkeypatch, "--push")
    verbes = [a[0] for a in scene]
    assert rc == 0
    assert "PUBLIER" in verbes
    assert "commit" not in verbes and "update-index" not in verbes


def test_un_dry_run_ne_publie_ni_ne_commite(scene, monkeypatch):
    rc = _lancer(monkeypatch)
    verbes = [a[0] for a in scene]
    assert rc == 0
    assert "commit" not in verbes and "PUBLIER" not in verbes and "update-index" not in verbes


def test_un_commit_en_ECHEC_n_est_jamais_publie(scene, monkeypatch):
    """Publier apres un commit rate republierait l'ancien etat en le disant neuf."""
    vrai_git = fbs.git

    def _git_ko(*a, timeout=None, arbre=False):
        if a[:1] == ("commit",):
            scene.append(list(a))
            return _Proc(rc=1, err="hook refuse")
        return vrai_git(*a, timeout=timeout, arbre=arbre)

    monkeypatch.setattr(fbs, "git", _git_ko)
    rc = _lancer(monkeypatch, "--commit", "--push", "--message", "sujet court")

    assert rc != 0, "un commit rate doit remonter"
    assert "PUBLIER" not in [a[0] for a in scene], \
        "on ne publie pas apres un commit en echec"
