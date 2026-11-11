"""NR -- contrat `tests_verts` juge par REJEU reel (JUnit) dans le worktree, jamais sur la prose de l'agent.
Chemin reel : `_juger_livraison`. Quatre issues : VERT prouve, ROUGE, rejeu impossible, contrat sans test nomme ;
les deux dernieres sont ILLISIBLES (ni vertes ni rouges)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(240)
RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
PROSE = 'Tous les tests verts : 5 passed in 0.1s. {"intent":"OK_DONE","pointer_ref":"commit:abc1234"}'


def _desc(chemins):
    return "Fais.\n[LIVRABLE_CONTRAT] " + json.dumps({"livrable": {"type": "tests_verts", "chemins": chemins}})


def _git(wd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                    "-C", str(wd), *a], check=True, capture_output=True)


@pytest.fixture()
def m():
    spec = importlib.util.spec_from_file_location("juge_rejeu_nr", RACINE / "tools" / "forge_task_executor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._palier_pression = lambda: "CALME"
    return mod


@pytest.fixture()
def depot(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _livrer(wd, nom, corps):
    (wd / nom).write_text(corps, encoding="utf-8")
    _git(wd, "add", "-A")
    _git(wd, "commit", "-q", "-m", "tests")


def _juge(m, wd, avant, chemins):
    ok, effet, _ = m._juger_livraison(True, PROSE, str(wd), avant, desc=_desc(chemins))
    return ok, effet


def test_vert_prouve(m, depot):
    avant = m._etat_git(str(depot))
    _livrer(depot, "test_a.py", "def test_a():\n    assert 1 + 1 == 2\n")
    ok, effet = _juge(m, depot, avant, ["test_a.py"])
    assert ok is True, effet


def test_agent_dit_verts_mais_le_test_echoue(m, depot):
    avant = m._etat_git(str(depot))
    _livrer(depot, "test_a.py", "def test_a():\n    assert 1 == 2\n")
    ok, effet = _juge(m, depot, avant, ["test_a.py"])
    assert ok is False and "RIEN_PRODUIT" in effet and "ROUGE" in effet and "[ILLISIBLE]" not in effet


def test_contrat_sans_test_nomme_illisible(m, depot):
    avant = m._etat_git(str(depot))
    _livrer(depot, "test_a.py", "def test_a():\n    assert True\n")
    ok, effet = _juge(m, depot, avant, [])
    assert ok is False and "[ILLISIBLE]" in effet and "RIEN_PRODUIT" not in effet
    assert m.verdict_automatique(ok, effet, PROSE, None) != "VIDE"


def test_test_nomme_absent_illisible(m, depot):
    avant = m._etat_git(str(depot))
    _livrer(depot, "test_a.py", "def test_a():\n    assert True\n")
    ok, effet = _juge(m, depot, avant, ["test_fantome.py"])
    assert ok is False and "[ILLISIBLE]" in effet


def test_zero_test_collecte_illisible(m, depot):
    avant = m._etat_git(str(depot))
    _livrer(depot, "test_vide.py", "x = 1\n")
    ok, effet = _juge(m, depot, avant, ["test_vide.py"])
    assert ok is False and "[ILLISIBLE]" in effet


def test_garde_ram_refuse_sans_contournement(m, depot):
    avant = m._etat_git(str(depot))
    _livrer(depot, "test_a.py", "def test_a():\n    assert True\n")
    m._palier_pression = lambda: "DETRESSE"
    ok, effet = _juge(m, depot, avant, ["test_a.py"])
    assert ok is False and "[ILLISIBLE]" in effet and "garde RAM" in effet


def test_delai_depasse_illisible(m, depot):
    _livrer(depot, "test_lent.py", "import time\n\ndef test_l():\n    time.sleep(30)\n")
    etat, cause = m._rejouer_contrat_tests(str(depot), ["test_lent.py"], timeout=2)
    assert etat == "ILLISIBLE" and "delai" in cause


def test_chemin_hors_worktree_illisible(m, depot):
    etat, _ = m._rejouer_contrat_tests(str(depot), ["../x.py"])
    assert etat == "ILLISIBLE"
