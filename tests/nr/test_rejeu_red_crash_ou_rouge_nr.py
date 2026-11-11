"""Rejeu RED de l'executeur (owner 6/11) : un test qui ne demarre pas n'est pas un rouge, et sa cause reste lisible."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as ex  # noqa: E402


def _depot(tmp_path, corps: str) -> tuple:
    d = tmp_path / "depot"
    (d / "tests").mkdir(parents=True)
    (d / "tests" / "test_x_nr.py").write_text(corps, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    g = ["git", "-c", "safe.directory=*", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(d)]
    for a in (["init", "-q"], ["add", "-A"], ["commit", "-q", "--no-verify", "-m", "x"]):
        subprocess.run(g + a, check=True, capture_output=True, env=env)
    sha = subprocess.run(g + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True, errors="replace", env=env).stdout.strip()
    return d, sha


@pytest.mark.parametrize("corps,etat", [
    ("def test_x():\n    assert True\n", "VERT"),
    ("def test_x():\n    assert False\n", "ROUGE"),
    ("import module_qui_n_existe_pas\n\ndef test_x():\n    assert True\n", "INDETERMINE"),
])
def test_etat_du_rejeu(tmp_path, monkeypatch, corps, etat):
    # 8/11 (CI lot p1) : un LAFORGE_PYTHON pollue par un test voisin (py.exe SANS pytest, pose puis
    # restaure tard/HORS monkeypatch) faisait echouer pytest en OSError -> INDETERMINE au lieu de ROUGE.
    # Figure l'interpreteur sur celui du worker (qui, par definition, porte pytest) : l'etat reel ne repond plus.
    monkeypatch.setenv("LAFORGE_PYTHON", sys.executable)
    d, sha = _depot(tmp_path, corps)
    obtenu, extrait = ex._rejouer_tests_sur_commit(str(d), sha, ["tests/test_x_nr.py"])
    assert obtenu == etat, extrait
    assert extrait.strip(), "la preuve ne doit jamais etre vide"


@pytest.mark.parametrize("pollution", [
    {"PYTEST_ADDOPTS": "--asyncio-mode=auto"},
    {"PYTEST_PLUGINS": "plugin_qui_n_existe_pas_811"},
])
def test_rejeu_independant_env_exterieur(tmp_path, monkeypatch, pollution):
    # 8/11 (mesure rejeu) : le pytest IMBRIQUE heritait de l'atelier exterieur — plugins auto-charges
    # (pytest-benchmark, hypothesis -> rc=2) ou PYTEST_ADDOPTS falsifie (rc=4) — et un [assert False]
    # du commit RED passait pour « CRASH, le test n'a pas tourne » (INDETERMINE). Le rejeu juge le
    # COMMIT, pas l'environnement qui l'observe : l'autoload doit etre coupe et les PYTEST_* poses
    # en aval ignores -- hermetique AVEC ou SANS PYTEST_DISABLE_PLUGIN_AUTOLOAD dehors.
    monkeypatch.setenv("LAFORGE_PYTHON", sys.executable)
    monkeypatch.delenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", raising=False)
    for cle, val in pollution.items():
        monkeypatch.setenv(cle, val)
    d, sha = _depot(tmp_path, "def test_x():\n    assert False\n")
    obtenu, extrait = ex._rejouer_tests_sur_commit(str(d), sha, ["tests/test_x_nr.py"])
    assert obtenu == "ROUGE", extrait
    assert extrait.strip(), "la preuve ne doit jamais etre vide"


def test_le_crash_dit_sa_cause(tmp_path):
    d, sha = _depot(tmp_path, "import module_qui_n_existe_pas\n\ndef test_x():\n    assert True\n")
    _, extrait = ex._rejouer_tests_sur_commit(str(d), sha, ["tests/test_x_nr.py"])
    assert "CRASH" in extrait and "rc=2" in extrait


def test_pytest_absent_n_est_pas_un_rouge(tmp_path, monkeypatch):
    d, sha = _depot(tmp_path, "def test_x():\n    assert False\n")
    vrai = subprocess.run

    def faux(cmd, *a, **k):
        if "pytest" in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "python.exe: No module named pytest\n")
        return vrai(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", faux)
    etat, extrait = ex._rejouer_tests_sur_commit(str(d), sha, ["tests/test_x_nr.py"])
    assert etat == "INDETERMINE" and "No module named" in extrait


def test_stderr_conserve(tmp_path, monkeypatch):
    d, sha = _depot(tmp_path, "def test_x():\n    assert True\n")
    vrai = subprocess.run

    def faux(cmd, *a, **k):
        if "pytest" in cmd:
            return subprocess.CompletedProcess(cmd, 3, "", "panne en stderr seulement\n")
        return vrai(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", faux)
    etat, extrait = ex._rejouer_tests_sur_commit(str(d), sha, ["tests/test_x_nr.py"])
    assert etat == "INDETERMINE" and "panne en stderr seulement" in extrait


def _capter(monkeypatch, tmp_path, rc=0, err=""):
    d, sha = _depot(tmp_path, "def test_x():\n    assert True\n")
    vu = []
    vrai = subprocess.run

    def faux(cmd, *a, **k):
        if "pytest" in cmd:
            vu.append(cmd[0])
            return subprocess.CompletedProcess(cmd, rc, "", err)
        return vrai(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", faux)
    return d, sha, vu


def test_interpreteur_laforge_python_prioritaire(tmp_path, monkeypatch):
    py = tmp_path / "py.exe"
    py.write_text("")
    monkeypatch.setenv("LAFORGE_PYTHON", str(py))
    d, sha, vu = _capter(monkeypatch, tmp_path)
    ex._rejouer_tests_sur_commit(str(d), sha, ["tests/test_x_nr.py"])
    assert vu == [str(py)]


def test_interpreteur_repli_si_fichier_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_PYTHON", str(tmp_path / "absent.exe"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    d, sha, vu = _capter(monkeypatch, tmp_path)
    ex._rejouer_tests_sur_commit(str(d), sha, ["tests/test_x_nr.py"])
    assert vu == [sys.executable]


def test_message_cite_interpreteur_employe(tmp_path, monkeypatch):
    py = tmp_path / "py.exe"
    py.write_text("")
    monkeypatch.setenv("LAFORGE_PYTHON", str(py))
    d, sha, vu = _capter(monkeypatch, tmp_path, 1, "No module named pytest")
    etat, extrait = ex._rejouer_tests_sur_commit(str(d), sha, ["tests/test_x_nr.py"])
    assert etat == "INDETERMINE" and str(py) in extrait
