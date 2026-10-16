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

MESURE 2026-10-14 (calibration `--turbo --turbo-workers 3`) : le turbo, lui, retombait encore sur `@fichier`
parce que les workers xdist ne recevaient pas la variable -- chaque worker a passe plus de 10 min en collecte
(13 M d'operations de metadonnees, zero lecture) sans importer un seul test. Le conftest transmet desormais le
chemin par `workerinput` ; le turbo prend la forme filtree, et un vrai run xdist le prouve ci-dessous.
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


def test_le_turbo_prend_aussi_la_forme_filtree(tmp_path):
    tests = ["tests/nr/test_b_nr.py", "tests/unit/test_a.py"]
    liste = tmp_path / "liste.txt"
    args, env = ci_local._args_suite_pure(tests, liste, turbo=True)
    assert args == ["tests"]
    assert env == {"NOKIDO_CI_LISTE": str(liste)}


@pytest.mark.parametrize("tests,turbo", [
    (["tests/nr/test_b_nr.py::test_un"], True),                    # vise un test, pas un fichier
    (["tests/nr/test_b_nr.py::test_un"], False),
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


@pytest.mark.parametrize("libre_go,attendu", [(6.0, 4), (4.8, 4), (4.7, 3), (3.6, 3), (3.5, 2), (1.0, 2)])
def test_les_workers_du_turbo_suivent_la_ram_libre(monkeypatch, libre_go, attendu):
    # Mesure 2026-10-14 : pic 3 809 Mo a -n 3, ~4 300 Mo a -n 4, borne d'un job 6 000 Mo. L'ancien defaut (moitie
    # des coeurs = 8) l'aurait depassee.
    import types

    import psutil
    monkeypatch.setattr(psutil, "virtual_memory", lambda: types.SimpleNamespace(available=libre_go * 2 ** 30))
    assert ci_local._workers_turbo(None) == attendu


def test_les_workers_demandes_priment_et_la_ram_illisible_est_dite(monkeypatch, capsys):
    import psutil
    assert ci_local._workers_turbo(5) == 5

    def _illisible():
        raise PermissionError("acces refuse")

    monkeypatch.setattr(psutil, "virtual_memory", _illisible)
    assert ci_local._workers_turbo(None) == 3
    assert "ILLISIBLE" in capsys.readouterr().out


@pytest.mark.timeout(120)
def test_un_plantage_natif_laisse_sa_trace_dans_le_fichier_du_processus(tmp_path):
    # Mesure 2026-10-14 : worker xdist mort sans trace ; 15 plantages pyarrow (arrow.dll, 0xc0000005) au journal
    # Windows. Chemin reel : le conftest arme faulthandler vers un fichier, puis le processus plante en natif.
    code = ("import ctypes, faulthandler, importlib.util, sys, types\n"
            "if sys.platform == 'win32':\n"
            "    ctypes.windll.kernel32.SetErrorMode(0x0002)  # pas de boite WER pendant un test\n"
            "s = importlib.util.spec_from_file_location('conftest_temoin', r'%s')\n"
            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
            "print(m._armer_faulthandler(types.SimpleNamespace(workerinput={'workerid': 'gw9'})), flush=True)\n"
            "faulthandler._sigsegv()\n") % (ROOT / "tests" / "conftest.py")
    env = {k: v for k, v in os.environ.items() if k not in ("NOKIDO_CI_LISTE", "PYTEST_ADDOPTS")}
    env.update(NOKIDO_FAULTHANDLER_DIR=str(tmp_path), PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, errors="replace",
                       timeout=100)
    assert r.returncode != 0, "le processus temoin devait planter"
    traces = list(tmp_path.glob("faulthandler_gw9_*.log"))
    assert len(traces) == 1, (traces, r.stdout[-500:], r.stderr[-500:])
    texte = traces[0].read_text(encoding="utf-8", errors="replace")
    assert "fatal" in texte.lower() and "File " in texte, texte[:500]


def test_ci_local_cable_et_relit_les_traces_de_plantage(tmp_path, capsys):
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert '"NOKIDO_FAULTHANDLER_DIR": str(_fh_dir)' in src and "_rapporter_faulthandler(_fh_dir)" in src
    (tmp_path / "faulthandler_gw0_1.log").write_text("", encoding="utf-8")
    (tmp_path / "faulthandler_gw1_2.log").write_text("Windows fatal exception: access violation\n"
                                                      '  File "x.py", line 1 in f\n', encoding="utf-8")
    traces = ci_local._rapporter_faulthandler(tmp_path)
    assert [t[0] for t in traces] == ["faulthandler_gw1_2.log"]
    assert "PLANTAGE NATIF" in capsys.readouterr().out


def test_le_basetemp_turbo_compense_le_segment_xdist():
    # Mesure 2026-10-14 (reference ce23f35a8) : `popen-gwN\` ajoute par xdist a fait franchir la limite de chemin
    # a 7 tests git (« '$GIT_DIR' too big »). Le basetemp turbo doit raccourcir AU MOINS d'autant.
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert '_btmp = _btmp.parent / "bt"' in src
    assert len("pytest_basetemp") - len("bt") >= len("popen-gw9") + 1


def test_le_gate_turbo_ne_prend_plus_la_moitie_des_coeurs():
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert '_workers_turbo(getattr(a, "turbo_workers", None))' in src
    assert "(os.cpu_count() or 2) // 2" not in src


@pytest.mark.timeout(180)
def test_les_workers_xdist_ne_collectent_que_la_liste(tmp_path):
    # Chemin reel du turbo : racine `tests` + liste, DEUX workers. Sans la transmission par `workerinput`,
    # chaque worker collecterait tout `tests/` (des milliers de modules) et ce run expirerait.
    pytest.importorskip("xdist")
    premier = "tests/nr/test_docstrings_trois_lecteurs_nr.py"
    second = "tests/nr/test_db_sanitize_verdict_nr.py"
    liste = tmp_path / "liste.txt"
    args, env_liste = ci_local._args_suite_pure([premier, second], liste, turbo=True)
    assert args == ["tests"]
    env = {k: v for k, v in os.environ.items() if k not in ("NOKIDO_CI_LISTE", "PYTEST_ADDOPTS")}
    env.update(env_liste, PYTHONPATH=str(ROOT / "app"), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTHONIOENCODING="utf-8", PYTHONNOUSERSITE="1")
    r = subprocess.run([sys.executable, "-m", "pytest", *args, "-v", "-p", "xdist", "-n", "2",
                        "--dist=loadfile", "-o", "addopts=-p no:warnings", "-p", "no:cacheprovider",
                        "--basetemp=%s" % (tmp_path / "bt")],
                       cwd=ROOT, env=env, capture_output=True, text=True, errors="replace", timeout=150)
    sortie = r.stdout + r.stderr
    assert "INTERNALERROR" not in sortie, sortie[-2000:]
    # lignes de resultat des workers : `[gw0] [ 50%] PASSED tests/nr/...::test_x`
    joues = {l.split()[-1].split("::")[0] for l in r.stdout.splitlines()
             if l.startswith("[gw") and "::" in l}
    assert joues == {premier, second}, (sorted(joues)[:10], sortie[-1500:])
    assert r.returncode in (0, 1), sortie[-1500:]


@pytest.mark.skipif(sys.platform != "win32", reason="WinError n'existe que sous Windows")
def test_le_lanceur_nomme_winerror_206_au_lieu_d_outil_introuvable(monkeypatch, capsys):
    def popen(*a, **k):
        raise OSError(2, "Le nom du fichier ou de l'extension est trop long", None, 206)

    monkeypatch.setattr(ci_local.subprocess, "Popen", popen)
    ci_local._run("sonde_206", ["python", "-c", "pass"], blocking=False)
    sortie = capsys.readouterr().out
    assert "WinError 206" in sortie and "outil introuvable" not in sortie
