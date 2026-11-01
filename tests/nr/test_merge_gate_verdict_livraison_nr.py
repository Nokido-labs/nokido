# -*- coding: utf-8 -*-
"""NR — une livraison d'exécuteur est VÉRIFIÉE par le corps, pas par Claude : verdict nokido.delivery-verdict/1.

__FORGE_COLOR__ = "immunitaire/guard : non-regression du verificateur de livraison des executeurs"

CE QUI A ÉTÉ PAYÉ (21/10). AGY a rendu `OK_DONE` sur l'archive chiffrée (63bbcf04b) : 5 NR sur 7 rouges, qu'il ne
pouvait pas jouer sous sa sandbox. Claude a dû extraire le commit par git dans un mini-arbre et jouer les tests à la
main. Décision owner : `OK_DONE` dit « tentative finie », jamais « travail accepté » ; c'est le corps qui l'établit,
par une ENVELOPPE de `oracle_gele` (pas un second vérificateur) :
  verifier_livraison(depot, task_id, sha, base, fichiers, tests, attempt=1, timeout=600, sortie=None) -> dict
- seuls les fichiers NOMMÉS sont lus au sha livré ; les autres sont dits `hors_consigne`, jamais appliqués ;
- les tests viennent de la BASE de confiance (`tests/` protégé) : une copie modifiée par l'exécuteur ne compte pas ;
- verdict en liste blanche : PASS seulement si la suite a tourné et passé ; FAIL, ERROR, TIMEOUT, UNKNOWN,
  SUITE_INCOMPLETE, INVALID sinon ; `promotion` vaut toujours NOT_ATTEMPTED (évaluer ≠ intégrer) ;
- `sortie` reçoit le verdict JSON (le `.rc` lu par l'orchestrateur) ; CLI `--verifier-livraison`, rc 0 sur PASS seul.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.timeout(300)


def _mod(monkeypatch):
    spec = importlib.util.spec_from_file_location("forge_merge_gate_nr", ROOT / "tools" / "forge_merge_gate.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "forge_merge_gate_nr", mod)
    spec.loader.exec_module(mod)
    return mod


def _git(depot, *args):
    r = subprocess.run(["git", "-c", "user.name=nr", "-c", "user.email=nr@nr", "-c", "safe.directory=*", *args],
                       cwd=str(depot), capture_output=True, text=True, errors="replace")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _ecrire(depot, chemin, texte):
    p = depot / chemin
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texte, encoding="utf-8")


@pytest.fixture
def depot(tmp_path):
    d = tmp_path / "depot"
    d.mkdir()
    _git(d, "init", "-q", "-b", "alpha")
    _ecrire(d, "pytest.ini", "[pytest]\n")  # rootdir = l'arbre jetable, jamais le depot Nokido
    _ecrire(d, "pkg/__init__.py", "")
    _ecrire(d, "pkg/mod.py", "def f():\n    return 1\n")
    _ecrire(d, "tests/test_mod.py", "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parents[1]))\n"
                                    "from pkg.mod import f\n\n\ndef test_f():\n    assert f() == 2\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "RED")
    return d


def _livrer(depot, fichiers: dict, message="GREEN") -> tuple:
    """(base, sha) : une branche de livraison partant d'alpha, comme le worktree d'un executeur."""
    base = _git(depot, "rev-parse", "HEAD")
    _git(depot, "checkout", "-q", "-b", "livraison_%d" % len(_git(depot, "branch", "--list").splitlines()))
    for chemin, texte in fichiers.items():
        _ecrire(depot, chemin, texte)
    _git(depot, "add", "-A")
    _git(depot, "commit", "-q", "-m", message)
    sha = _git(depot, "rev-parse", "HEAD")
    _git(depot, "checkout", "-q", "alpha")
    return base, sha


def test_livraison_juste_rend_pass(monkeypatch, depot, tmp_path):
    m = _mod(monkeypatch)
    base, sha = _livrer(depot, {"pkg/mod.py": "def f():\n    return 2\n"})
    sortie = tmp_path / "job.rc"
    v = m.verifier_livraison(depot, "job_x", sha, base, ["pkg/mod.py"], ["tests/test_mod.py"], sortie=sortie)
    assert v["schema"] == "nokido.delivery-verdict/1" and v["verdict"] == "PASS", v
    assert v["commit_sha"] == sha and v["base_sha"] == base and v["task_id"] == "job_x" and v["attempt"] == 1
    assert v["tests"]["passed"] == 1 and v["tests"]["failed"] == 0 and v["promotion"] == "NOT_ATTEMPTED"
    assert json.loads(sortie.read_text(encoding="utf-8"))["verdict"] == "PASS"


def test_livraison_rouge_rend_fail_et_le_test_fautif(monkeypatch, depot):
    m = _mod(monkeypatch)
    base, sha = _livrer(depot, {"pkg/mod.py": "def f():\n    return 3\n"})
    v = m.verifier_livraison(depot, "job_x", sha, base, ["pkg/mod.py"], ["tests/test_mod.py"])
    assert v["verdict"] == "FAIL", v
    assert v["tests"]["failed"] == 1
    assert any("test_f" in t["test"] for t in v["failed_tests"]), v["failed_tests"]


def test_les_tests_de_l_executeur_ne_comptent_pas(monkeypatch, depot):
    m = _mod(monkeypatch)
    base, sha = _livrer(depot, {"pkg/mod.py": "def f():\n    return 3\n",
                                "tests/test_mod.py": "def test_f():\n    assert True\n"})
    v = m.verifier_livraison(depot, "job_x", sha, base, ["pkg/mod.py"], ["tests/test_mod.py"])
    assert v["verdict"] == "FAIL", "le test reecrit par l'executeur a ete joue a la place de la reference %r" % v
    assert "tests/test_mod.py" in v["hors_consigne"]


def test_nommer_un_fichier_protege_est_invalide(monkeypatch, depot):
    m = _mod(monkeypatch)
    base, sha = _livrer(depot, {"tests/test_mod.py": "def test_f():\n    assert True\n"})
    v = m.verifier_livraison(depot, "job_x", sha, base, ["tests/test_mod.py"], ["tests/test_mod.py"])
    assert v["verdict"] == "INVALID", v


def test_fichier_nomme_absent_du_commit_rend_fail_sans_execution(monkeypatch, depot):
    m = _mod(monkeypatch)
    base, sha = _livrer(depot, {"pkg/mod.py": "def f():\n    return 2\n"})
    v = m.verifier_livraison(depot, "job_x", sha, base, ["pkg/absent.py"], ["tests/test_mod.py"])
    assert v["verdict"] == "FAIL" and "pkg/absent.py" in v["raison"], v
    assert v["tests"]["passed"] == 0 and v["tests"]["incomplete"] is True


def test_sha_inconnu_rend_unknown(monkeypatch, depot):
    m = _mod(monkeypatch)
    base = _git(depot, "rev-parse", "HEAD")
    v = m.verifier_livraison(depot, "job_x", "0" * 40, base, ["pkg/mod.py"], ["tests/test_mod.py"])
    assert v["verdict"] == "UNKNOWN", v


def test_aucun_test_collecte_rend_suite_incomplete(monkeypatch, depot):
    m = _mod(monkeypatch)
    base, sha = _livrer(depot, {"pkg/mod.py": "def f():\n    return 2\n"})
    v = m.verifier_livraison(depot, "job_x", sha, base, ["pkg/mod.py"], ["tests/test_mod.py::inexistant"])
    assert v["verdict"] in ("SUITE_INCOMPLETE", "ERROR") and v["verdict"] != "PASS", v


def test_delai_depasse_rend_timeout(monkeypatch, depot):
    m = _mod(monkeypatch)
    base, sha = _livrer(depot, {"pkg/mod.py": "import time\ntime.sleep(30)\n\n\ndef f():\n    return 2\n"})
    v = m.verifier_livraison(depot, "job_x", sha, base, ["pkg/mod.py"], ["tests/test_mod.py"], timeout=3)
    assert v["verdict"] == "TIMEOUT", v


def test_le_point_d_entree_cli_ecrit_le_rc(depot, tmp_path):
    base, sha = _livrer(depot, {"pkg/mod.py": "def f():\n    return 2\n"})
    sortie = tmp_path / "cli.rc"
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "forge_merge_gate.py"), "--verifier-livraison",
                        "--depot", str(depot), "--task-id", "job_cli", "--commit", sha, "--base", base,
                        "--fichiers", "pkg/mod.py", "--tests", "tests/test_mod.py", "--sortie", str(sortie)],
                       cwd=str(ROOT), capture_output=True, text=True, errors="replace", timeout=240,
                       env=dict(os.environ, PYTHONNOUSERSITE="1"))
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    assert json.loads(sortie.read_text(encoding="utf-8"))["task_id"] == "job_cli"
