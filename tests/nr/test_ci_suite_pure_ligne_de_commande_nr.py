"""NR -- la suite pure ne depasse plus le plafond de ligne de commande Windows, et le lanceur NOMME ce depassement.

MESURE 2026-09-26 (CI de reference sur f6b3613bb) : `pytest (suite pure)` -> « UNKNOWN (outil introuvable :
FileNotFoundError) » ; la suite n'a PAS tourne. Cause : 815 tests declares = 34 714 car. de chemins relatifs
sur UNE ligne de commande, au-dela des 32 767 de CreateProcess. Windows rend WinError 206, que Python leve en
FileNotFoundError -- d'ou un diagnostic faux (« outil introuvable »). Le 08/09 la liste tenait (WinError 206
deja instruit ce jour-la, indexe par forge_symptom_index) : elle a franchi le plafond en GRANDISSANT, ce qu'aucun
test ne surveillait. pytest >= 8.2 lit ses arguments dans un fichier `@chemin` (preuve : collecte identique sur
laforge_py314, pytest 9.0.3) ; la commande garde alors une longueur fixe.

MESURE 2026-09-29 (audit stabilite CI, mesures/audits/stabilite_ci.md) : ~900 fichiers en ARGUMENTS, meme par
`@fichier`, rendent la collecte QUADRATIQUE -- pytest re-parcourt `tests/nr` pour chacun : 237 s contre 9,8 s
avec un seul argument. Hors turbo, la suite pure passe la seule racine `tests` et la liste dans NOKIDO_CI_LISTE ;
`tests/conftest.py` ecarte les modules hors liste sans les importer et rejoue l'ordre declare.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ci_local  # noqa: E402


def test_la_liste_part_dans_un_fichier_et_la_commande_reste_courte(tmp_path):
    tests = ["tests/nr/test_%04d_un_nom_de_test_assez_long_nr.py" % i for i in range(2000)]
    liste = tmp_path / "liste.txt"
    args = ci_local._args_depuis_fichier(tests, liste)
    assert args == ["@%s" % liste]
    assert liste.read_text(encoding="utf-8").splitlines() == tests
    assert len(subprocess.list2cmdline([sys.executable, "-m", "pytest", *args, "-q"])) < 2000


def test_le_gate_suite_pure_passe_la_liste_par_fichier():
    # Chemin reel : la commande du gate n'etale plus la liste des tests sur la ligne de commande.
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert '"pytest", *_paralleles' not in src
    assert "_args_suite_pure(_paralleles, _liste_pur, _turbo)" in src
    # la variable qui porte la liste atteint bien le processus pytest de la suite pure
    assert '"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", **_env_liste})' in src


def test_hors_turbo_une_seule_racine_et_la_liste_en_variable(tmp_path):
    tests = ["tests/nr/test_b_nr.py", "tests/unit/test_a.py"]
    liste = tmp_path / "liste.txt"
    args, env = ci_local._args_suite_pure(tests, liste, turbo=False)
    assert args == ["tests"]
    assert env == {"NOKIDO_CI_LISTE": str(liste)}
    assert liste.read_text(encoding="utf-8").splitlines() == tests


@pytest.mark.parametrize("tests,turbo", [
    (["tests/nr/test_b_nr.py"], True),                            # xdist : les workers perdraient la variable
    (["tests/nr/test_b_nr.py::test_un"], False),                   # vise un test, pas un fichier
    (["tests/nr/test_b_nr.py", "app/test_hors_tests.py"], False),  # hors de la portee du conftest
    ([], False),
])
def test_repli_sur_le_fichier_quand_le_filtre_ne_s_applique_pas(tmp_path, tests, turbo):
    liste = tmp_path / "liste.txt"
    args, env = ci_local._args_suite_pure(tests, liste, turbo=turbo)
    assert args == ["@%s" % liste] and env == {}


@pytest.mark.timeout(120)
def test_la_collecte_reelle_ne_retient_que_la_liste_dans_son_ordre(tmp_path):
    # Chemin reel : un vrai pytest sur la racine `tests`, filtre par tests/conftest.py.
    # temoins sans marqueur `timeout` (plugin non charge dans ce sous-processus) ; ordre INVERSE de l'alphabet
    premier = "tests/nr/test_docstrings_trois_lecteurs_nr.py"
    second = "tests/nr/test_db_sanitize_verdict_nr.py"
    liste = tmp_path / "liste.txt"
    args, env_liste = ci_local._args_suite_pure([premier, second], liste, turbo=False)
    env = {k: v for k, v in os.environ.items() if k != "NOKIDO_CI_LISTE"}
    env.update(env_liste, PYTHONPATH=str(ROOT / "app"), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-m", "pytest", *args, "--collect-only", "-q",
                        "-o", "addopts=-p no:warnings", "-p", "no:cacheprovider"],
                       cwd=ROOT, env=env, capture_output=True, text=True, errors="replace", timeout=100)
    noeuds = [l.strip() for l in r.stdout.splitlines() if "::" in l]
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    assert noeuds and {n.split("::")[0] for n in noeuds} == {premier, second}, noeuds[:10]
    assert noeuds[0].startswith(premier + "::")
    assert noeuds[-1].startswith(second + "::")


@pytest.mark.skipif(sys.platform != "win32", reason="WinError n'existe que sous Windows")
def test_le_lanceur_nomme_winerror_206_au_lieu_d_outil_introuvable(monkeypatch, capsys):
    def popen(*a, **k):
        raise OSError(2, "Le nom du fichier ou de l'extension est trop long", None, 206)

    monkeypatch.setattr(ci_local.subprocess, "Popen", popen)
    ci_local._run("sonde_206", ["python", "-c", "pass"], blocking=False)
    sortie = capsys.readouterr().out
    assert "WinError 206" in sortie and "outil introuvable" not in sortie
