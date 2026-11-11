"""ACL des worktrees (owner 6/11, « de facon securise et tracable ») : traversee pour le compte hors ligne, rien d'autre."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_worktree_acl as a  # noqa: E402


@pytest.fixture()
def arbre(tmp_path):
    racine = tmp_path / "nokido_worktrees"
    (racine / "antigravity").mkdir(parents=True)
    (racine / "antigravity" / ".git").write_text("gitdir: x\n", encoding="utf-8")
    (racine / "pas_un_arbre").mkdir()
    return racine


def test_cibles_racine_et_arbres_seulement(arbre):
    assert a.cibles(arbre) == [arbre, arbre / "antigravity"]


def test_commande_exacte_lecture_et_traversee_sans_recursion(arbre):
    c = a.commande(arbre / "antigravity", "appliquer")
    assert c[0] == "icacls" and "/grant:r" in c and "LaForgeSbxOffline:(OI)(CI)(RX)" in c
    assert "/T" not in c and not any("(F)" in x or "(M)" in x or "(W)" in x for x in c)


def test_retrait_rend_le_droit_d_origine(arbre):
    assert "LaForgeSbxOffline:(OI)(CI)(R)" in a.commande(arbre, "retirer")


def test_essai_a_blanc_n_ecrit_aucune_acl_et_journalise(arbre, tmp_path, monkeypatch):
    vus = []

    def faux(cmd, **k):
        vus.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "droits", "")

    monkeypatch.setattr(a.subprocess, "run", faux)
    j = tmp_path / "j.jsonl"
    assert a.executer(arbre, "essai", journal=j) == 0
    assert vus and all(len(c) == 2 for c in vus), "essai : icacls en lecture seulement"
    lignes = [json.loads(x) for x in j.read_text(encoding="utf-8").splitlines()]
    assert lignes and lignes[0]["mode"] == "essai" and "avant" in lignes[0]


def test_application_tracee_avant_apres_et_echec_rendu(arbre, tmp_path, monkeypatch):
    def faux(cmd, **k):
        return subprocess.CompletedProcess(cmd, 5 if "/grant:r" in cmd else 0, "droits", "refus")

    monkeypatch.setattr(a.subprocess, "run", faux)
    j = tmp_path / "j.jsonl"
    assert a.executer(arbre, "appliquer", journal=j) == 1
    l0 = json.loads(j.read_text(encoding="utf-8").splitlines()[0])
    assert l0["rc"] == 5 and "avant" in l0 and "apres" in l0 and l0["utilisateur"]


def test_racine_inattendue_refusee(tmp_path):
    with pytest.raises(ValueError):
        a.cibles(tmp_path / "autre_dossier")
