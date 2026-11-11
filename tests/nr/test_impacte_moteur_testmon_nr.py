# -*- coding: utf-8 -*-
"""NR -- testmon comme MOTEUR de l'option existante `--impacte` de ci_local (choix owner 10/11 soir).

Livrable OPENCODE_GPTOSS (de7db9d55 + 8d6f77dfa, branche tache/opencode_gptoss/6240f416ec3d), integre par
governed_edit. Contrat :
  1. `--impacte` ET `_has("testmon")` -> `--testmon` dans les args pytest +
     env TESTMON_DATAFILE=<racine>/sandbox/ci/.testmondata (dossier cree) ;
     l'heuristique par fichiers n'est alors pas appliquee ; moteur="testmon".
  2. `--impacte` sans testmon -> comportement actuel (pas de `--testmon`) ;
     moteur="fichiers (testmon absent)".
  3. Sans `--impacte` : JAMAIS `--testmon`.
  4. `--impacte` reste NON CERTIFIANT (SUITE_PARTIELLE, aucune capture de sha).
  5. (verificateur, 10/11) la suite pure tourne sous PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 : `--testmon` SEUL est rejete
     (« unrecognized arguments: --testmon », mesure) ; le plugin doit etre charge explicitement
     (`-p testmon.pytest_testmon`, mesure : « testmon: new DB », verts).
"""
# pylint: disable=import-error,wrong-import-position,unnecessary-lambda-assignment
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ci_local  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def _a(impacte: bool):
    return SimpleNamespace(impacte=impacte)


def test_cas1_testmon_present_ajoute_testmon_et_datafile():
    """--impacte + testmon : --testmon, TESTMON_DATAFILE sous sandbox/ci, moteur testmon."""
    args, env, moteur = ci_local._args_selection_impacte(_a(True), lambda mod: mod == "testmon")
    assert "--testmon" in args
    assert env.get("TESTMON_DATAFILE", "").replace("\\", "/").endswith("sandbox/ci/.testmondata")
    assert moteur == "testmon"


def test_cas1b_plugin_charge_explicitement_sous_autoload_coupe():
    """PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 : le plugin est charge par -p AVANT --testmon."""
    args, _, _ = ci_local._args_selection_impacte(_a(True), lambda mod: mod == "testmon")
    assert args[:2] == ["-p", "testmon.pytest_testmon"] and args.index("--testmon") > 1


def test_cas2_sans_testmon_pas_de_testmon():
    """--impacte sans testmon : rien de testmon, moteur fichiers."""
    args, env, moteur = ci_local._args_selection_impacte(_a(True), lambda mod: False)
    assert "--testmon" not in args and "TESTMON_DATAFILE" not in env
    assert str(moteur).startswith("fichiers")


def test_cas3_sans_impacte_jamais_testmon():
    """Sans --impacte : jamais --testmon, meme testmon present."""
    args, env, _ = ci_local._args_selection_impacte(_a(False), lambda mod: True)
    assert "--testmon" not in args and "TESTMON_DATAFILE" not in env


def test_ci_local_branche_testmon():
    """La commande de la suite pure recoit les args et l'env de la selection."""
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert "*_impacte_args" in src and "**_impacte_env" in src and "[impacte] moteur=%s" in src
