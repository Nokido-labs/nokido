"""tests/nr/test_nr_worktree_nr.py — NR pour forge_nr_worktree.py.

Prouve :
1. Chemin hors perimetre nokido_worktrees/ refuse.
2. Argument non test refuse (pas de shell generique, refus d'options -* ou commandes arbitraires).
3. Le code et les chemins du worktree sont bien ceux importes et cibles (cwd & PYTHONPATH).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_nr_worktree as NW  # noqa: E402


def test_chemin_hors_perimetre_refuse(tmp_path):
    dossier_hors = tmp_path / "autre_endroit"
    dossier_hors.mkdir()
    with pytest.raises(ValueError, match="Chemin hors perimetre nokido_worktrees"):
        NW.valider_worktree(dossier_hors)


def test_chemin_inexistant_refuse(tmp_path):
    wt_simule = tmp_path / "nokido_worktrees" / "inexistant"
    with pytest.raises(ValueError, match="n'existe pas ou n'est pas un dossier"):
        NW.valider_worktree(wt_simule)


def test_chemin_valide_dans_perimetre(tmp_path):
    wt_simule = tmp_path / "nokido_worktrees" / "taches" / "antigravity_12345"
    wt_simule.mkdir(parents=True)
    res = NW.valider_worktree(wt_simule)
    assert res == wt_simule.resolve()


def test_argument_non_test_refuse():
    # Options shell / pytest
    with pytest.raises(ValueError, match="Option interdite"):
        NW.valider_arguments_tests(["-s", "tests/nr/test_x_nr.py"])

    with pytest.raises(ValueError, match="Option interdite"):
        NW.valider_arguments_tests(["--lf"])

    # Commande ou argument hors motif .py
    with pytest.raises(ValueError, match="Argument non test refuse"):
        NW.valider_arguments_tests(["rm -rf /"])

    with pytest.raises(ValueError, match="Argument non test refuse"):
        NW.valider_arguments_tests(["echo hello"])


def test_arguments_tests_valides():
    tests = ["tests/nr/test_something_nr.py", "tests/unit/test_other.py::test_fn"]
    valides = NW.valider_arguments_tests(tests)
    assert valides == tests


def test_worktree_importe_et_cible(tmp_path, monkeypatch):
    wt_simule = tmp_path / "nokido_worktrees" / "taches" / "antigravity_test"
    wt_simule.mkdir(parents=True)

    app_dir = wt_simule / "app"
    app_dir.mkdir()
    # Module specifique a ce worktree
    (app_dir / "mon_module_wt.py").write_text("SIGNATURE = 'MODULE_WORKTREE_OK'\n", encoding="utf-8")

    app_racine = tmp_path / "app_racine"
    app_racine.mkdir()
    (app_racine / "mon_module_wt.py").write_text("SIGNATURE = 'MODULE_RACINE_WRONG'\n", encoding="utf-8")

    # Faux subprocess.run pour verifier l'environnement transmis
    env_recu = {}
    cwd_recu = {}

    def fake_run(cmd, cwd=None, env=None, **kwargs):
        cwd_recu["cwd"] = cwd
        env_recu["PYTHONPATH"] = env.get("PYTHONPATH")
        class FakeRes:
            stdout = "1 passed in 0.05s"
            stderr = ""
            returncode = 0
        return FakeRes()

    monkeypatch.setattr(NW.subprocess, "run", fake_run)

    res = NW.executer_tests_worktree(wt_simule, ["tests/nr/test_sample_nr.py"])
    assert res["ok"] is True
    assert cwd_recu["cwd"] == str(wt_simule.resolve())
    assert str(wt_simule.resolve()) in env_recu["PYTHONPATH"].split(os.pathsep)
    assert str((wt_simule / "app").resolve()) in env_recu["PYTHONPATH"].split(os.pathsep)


# --- shell borne (reporte de l'ancien test_worktree_cmd_borne_nr, meme implementation) ---
import subprocess  # noqa: E402


@pytest.fixture()
def arbre(tmp_path):
    racine = tmp_path / "nokido_worktrees"
    wt = racine / "antigravity_abc"
    (wt / "tests").mkdir(parents=True)
    (wt / ".git").write_text("gitdir: ailleurs\n", encoding="utf-8")
    (wt / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (wt / "tests" / "test_ok_nr.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (wt / "tests" / "test_ko_nr.py").write_text("def test_ko():\n    assert False\n", encoding="utf-8")
    return racine, wt


@pytest.mark.parametrize("argv", [
    ["pytest", "tests/test_ok_nr.py"],
    ["pytest", "tests/test_ok_nr.py", "-q", "-x", "--tb=short"],
    ["git", "status", "--short"],
    ["git", "diff", "--stat"],
    ["ruff", "check", "tests/test_ok_nr.py"],
])
def test_commandes_permises(arbre, argv):
    racine, wt = arbre
    assert NW.valider(wt, argv, racine=racine)[0] is True


@pytest.mark.parametrize("argv", [
    ["powershell", "-c", "dir"],
    ["python", "-c", "print(1)"],
    ["git", "push"],
    ["git", "-c", "core.sshCommand=x", "status"],
    ["git", "diff", "--output=../x"],
    ["git", "diff", "--ext-diff"],
    ["pytest", "../autre/test_x.py"],
    ["pytest", "C:/Windows/test_x.py"],
    ["pytest", "tests/test_ok_nr.py", "-p", "plugin_malin"],
    ["pytest", "--rootdir=C:/", "tests/test_ok_nr.py"],
    ["pytest", "-c", "../pytest.ini"],
    ["pytest", "--junitxml=C:/x.xml"],
    ["ruff", "format", "tests"],
    [],
])
def test_commandes_refusees(arbre, argv):
    racine, wt = arbre
    ok, motif = NW.valider(wt, argv, racine=racine)
    assert ok is False and motif


def test_hors_racine_refuse(arbre, tmp_path):
    racine, _ = arbre
    dehors = tmp_path / "dehors"
    dehors.mkdir()
    (dehors / ".git").write_text("gitdir: x\n", encoding="utf-8")
    assert NW.valider(dehors, ["git", "status"], racine=racine)[0] is False
    assert NW.valider(racine / "antigravity_abc" / ".." / ".." / "dehors", ["git", "status"], racine=racine)[0] is False


def test_dossier_sans_git_refuse(arbre):
    racine, _ = arbre
    (racine / "pas_un_arbre").mkdir()
    assert NW.valider(racine / "pas_un_arbre", ["git", "status"], racine=racine)[0] is False


def test_executer_sans_shell_cwd_fixe_temp_hors_arbre(arbre, monkeypatch):
    racine, wt = arbre
    vu = {}

    def faux_run(cmd, **kw):
        vu.update(kw, cmd=cmd)
        return subprocess.CompletedProcess(cmd, 0, "1 passed\n", "")

    monkeypatch.setattr(NW.subprocess, "run", faux_run)
    monkeypatch.setenv("GIT_DIR", "C:/ailleurs")
    r = NW.executer(wt, ["pytest", "tests/test_ok_nr.py"], racine=racine)
    assert r["rc"] == 0 and "1 passed" in r["sortie"]
    assert vu.get("shell") in (None, False) and isinstance(vu["cmd"], list)
    assert Path(vu["cwd"]).resolve() == wt.resolve()
    temp = Path(vu["env"]["TMPDIR"]).resolve()
    assert not temp.is_relative_to(wt.resolve()), "compte hors ligne : aucune ecriture dans l'arbre"
    assert vu["env"]["TEMP"] == vu["env"]["TMPDIR"] == vu["env"]["TMP"]
    assert "GIT_DIR" not in vu["env"] and vu["env"]["PYTHONNOUSERSITE"] == "1"
    assert not temp.exists()
    assert not (wt / ".tmp_nr_worktree").exists()


def test_refus_ne_lance_rien(arbre, monkeypatch):
    racine, wt = arbre
    monkeypatch.setattr(NW.subprocess, "run", lambda *a, **k: pytest.fail("rien ne doit etre lance"))
    r = NW.executer(wt, ["powershell", "-c", "dir"], racine=racine)
    assert r["rc"] == NW.RC_REFUS and "refus" in r["sortie"].lower()


def test_pytest_reel_rouge_et_vert_distingues(arbre):
    racine, wt = arbre
    # La sortie accompagne le rc (7/11) : en CI job_d9e2c3a3500b le rouge a rendu rc=2 (session INTERROMPUE ou
    # erreur de collecte, pas un echec de test) sans rien montrer, et ne se reproduit ni en local ni sous le meme
    # basetemp profond. Le contrat est inchange : vert = 0, rouge = 1, jamais confondus.
    vert = NW.executer(wt, ["pytest", "tests/test_ok_nr.py", "-q", "-p", "no:cacheprovider", "-v"], racine=racine)
    assert vert["rc"] == 0, vert["sortie"][-2000:]
    assert "rootdir: %s" % wt in vert["sortie"]
    rouge = NW.executer(wt, ["pytest", "tests/test_ko_nr.py", "-q", "-p", "no:cacheprovider", "-v"], racine=racine)
    assert rouge["rc"] == 1, rouge["sortie"][-2000:]
    assert "rootdir: %s" % wt in rouge["sortie"]


def test_main_forme_worktree_et_forme_historique(arbre, monkeypatch, capsys):
    racine, wt = arbre
    monkeypatch.setattr(NW, "RACINE_WORKTREES", racine)
    monkeypatch.setattr(NW.subprocess, "run", lambda c, **k: subprocess.CompletedProcess(c, 0, "ok\n", ""))
    assert NW.main(["--worktree", str(wt), "--", "git", "status"]) == 0
    assert "BILAN: rc=0" in capsys.readouterr().out
    assert NW.main([str(wt.parent / "dehors"), "tests/nr/test_x_nr.py"]) == 2
