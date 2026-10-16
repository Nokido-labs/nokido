# -*- coding: utf-8 -*-
"""NR -- les worktrees de preuve se purgent SANS PERTE, dans TOUTES les racines ou on les cree (owner 15/10).

Owner 15/10 : « il faut reconcilier ca, le travail ne doit pas etre perdu ». Mesure du jour : 94 worktrees
(~8 Go), dont 44 sous D:/Temp/nokido_proof (hook pre-push, session owner) que la retention ne voyait pas ;
et `git worktree remove --force` aurait efface sans rien dire un travail non commite.

Contrat, sur un VRAI depot git temporaire :
  1. `perte_possible` : arbre propre ou artefacts de preuve seuls -> None ; fichier hors artefacts ->
     raison ; commit porte par le seul worktree -> COMMIT_ORPHELIN ;
  2. le registre des racines s'ecrit sans doublon, illisible -> [] ;
  3. la retention parcourt les racines inscrites, et GARDE (en le disant) un worktree a perte possible.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_log_retention as ret  # noqa: E402
import forge_worktree as fw  # noqa: E402


def _git(cwd, *a):
    p = subprocess.run(["git", "-c", "safe.directory=*", "-c", "user.name=t", "-c", "user.email=t@t", *a],
                       cwd=str(cwd), capture_output=True, text=True, errors="replace")
    assert p.returncode == 0, p.stderr
    return p.stdout


@pytest.fixture
def court(tmp_path_factory):
    """Racine COURTE, independante du nom du test. CI de reference du 15/10 : sous le worktree de preuve,
    `tmp_path` + le nom de ce test (60 car.) + `.git/worktrees/<nom>` depassaient la borne de git pour
    Windows (PATH_MAX - 40) -> `fatal: '$GIT_DIR' too big` au `worktree add`."""
    return tmp_path_factory.mktemp("w")


@pytest.fixture
def depot(court, monkeypatch):
    d = court / "depot"
    d.mkdir()
    _git(d, "init", "-q")
    (d / "a.txt").write_text("a", encoding="utf-8")
    _git(d, "add", "a.txt")
    _git(d, "commit", "-q", "-m", "init")
    monkeypatch.setattr(fw, "ROOT", d)
    monkeypatch.setattr(fw, "REGISTRE_RACINES", court / "proof_roots.json")
    return d


def _worktree(depot, chemin):
    _git(depot, "worktree", "add", "-q", "--detach", str(chemin), "HEAD")
    return chemin


def test_perte_possible_sur_un_vrai_depot(depot, court):
    wt = _worktree(depot, court / "wt")
    assert fw.perte_possible(wt) is None                               # propre
    (wt / "sandbox").mkdir()
    (wt / "sandbox" / "junit.xml").write_text("x", encoding="utf-8")
    assert fw.perte_possible(wt) is None                               # artefact de preuve seul
    (wt / "notes.md").write_text("travail", encoding="utf-8")
    assert "hors artefacts" in fw.perte_possible(wt)                   # vrai travail non suivi
    (wt / "notes.md").unlink()
    (wt / "b.txt").write_text("b", encoding="utf-8")
    _git(wt, "add", "b.txt")
    _git(wt, "commit", "-q", "-m", "seul ici")
    assert "COMMIT_ORPHELIN" in fw.perte_possible(wt)                  # commit porte par ce seul worktree


def test_registre_des_racines_sans_doublon(depot, court):
    assert fw.racines_de_preuve_inscrites() == []
    assert fw.inscrire_racine_de_preuve(court / "r1") and fw.inscrire_racine_de_preuve(court / "r1")
    assert fw.racines_de_preuve_inscrites() == [str(court / "r1")]
    fw.REGISTRE_RACINES.write_text("{illisible", encoding="utf-8")
    assert fw.racines_de_preuve_inscrites() == []


def test_create_proof_sous_pytest_n_inscrit_rien(depot, court, monkeypatch):
    """Defaut paye le 15/10 : 15 racines de tests inscrites dans le VRAI registre au premier rejeu."""
    monkeypatch.setattr(fw, "PROOF_ROOT", court / "preuves")
    sha = _git(depot, "rev-parse", "HEAD").strip()
    r = fw.create_proof(sha, "exec-test")
    assert "error" not in r, r
    assert fw.racines_de_preuve_inscrites() == [] and not fw.REGISTRE_RACINES.exists()


def test_retention_parcourt_les_racines_inscrites_et_garde_la_perte(depot, court, monkeypatch):
    base = court / "nokido_proof"
    sain = _worktree(depot, base / "ci-reference-sain" / "worktree")
    risque = _worktree(depot, base / "ci-reference-risque" / "worktree")
    (risque / "travail.py").write_text("x = 1", encoding="utf-8")
    vieux = time.time() - 30 * 86400
    for e in (base / "ci-reference-sain", base / "ci-reference-risque"):
        os.utime(e, (vieux, vieux))
    fw.inscrire_racine_de_preuve(base)
    uniques, _ill = ret._racines_de_preuve(fw)
    assert any(os.path.normcase(str(u)) == os.path.normcase(str(base)) for u in uniques)
    monkeypatch.setattr(ret, "PROOF_KEEP", 0)
    monkeypatch.setattr(ret, "PROOF_DAYS", 1)
    r = ret._purger_une_racine_de_preuve(fw, base, dry=False)
    assert not sain.exists() and risque.exists() and (risque / "travail.py").exists(), r
    assert any("GARDE (perte possible)" in x["msg"] for x in r["erreurs"]), r
