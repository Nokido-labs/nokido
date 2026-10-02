#!/usr/bin/env python3
"""NR — la baseline de migration classe les imports sans se mentir.

PHASE 3. Le delta avant/apres gouvernera tout le chantier : si la classification
est fausse, le progres mesure sera faux dans le meme sens.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

base = pytest.importorskip("forge_pypi_baseline")

_INTERNES = {"forge_secrets", "forge_db_path", "nokido_hub"}


def test_un_module_du_depot_est_plat_interne():
    assert base.classer_import("forge_secrets", _INTERNES) == "PLAT_INTERNE"


def test_un_tiers_sans_point_n_est_PAS_plat_interne():
    """LE piege de la journee : `numpy` n'a pas de point et n'est pas stdlib, il
    RESSEMBLE a un module frere. Il ne l'est pas. Premiere carte : 927
    `PATH_FOR_IMPORT` annonces au lieu de 911, dans le sens qui arrange."""
    assert base.classer_import("numpy", _INTERNES) == "EXTERNE"
    assert base.classer_import("libcst", _INTERNES) == "EXTERNE"


def test_un_import_par_package_est_deja_la_cible():
    for nom in ("app.forge_secrets", "tools.nokido_hub", "recon_silo.x"):
        assert base.classer_import(nom, _INTERNES) == "PACKAGE"


def test_la_stdlib_n_est_jamais_une_dette():
    for nom in ("json", "pathlib", "sys"):
        assert base.classer_import(nom, _INTERNES) == "EXTERNE"


def test_un_fichier_illisible_est_compte_pas_avale():
    """Trois etats. Un fichier qui ne parse pas n'a pas « zero import »."""
    mesure = base.compter_imports({"casse.py": "def f(:\n"}, _INTERNES)
    assert mesure["illisibles"] == 1
    assert "casse.py" in mesure["fichiers_illisibles"]


def test_le_comptage_distingue_occurrences_et_fichiers():
    """Deux imports dans un meme fichier = 2 occurrences, 1 fichier. Confondre les
    deux ferait croire a une dette plus large ou plus etroite qu'elle n'est."""
    src = "import forge_secrets\nimport forge_db_path\n"
    mesure = base.compter_imports({"a.py": src}, _INTERNES)
    assert mesure["occurrences"]["PLAT_INTERNE"] == 2
    assert mesure["fichiers"]["PLAT_INTERNE"] == 1


def test_une_baseline_sans_denominateur_n_est_pas_certifiante():
    """Regle owner : denominateur vide = NON-CERTIFIANT. Une baseline batie sur
    zero module declarerait zero dette — et paraitrait excellente."""
    mesure = base.baseline(ROOT / "tests" / "nr")   # zone sans app/ ni tools/
    assert mesure["certifiant"] is False


# Timeout 120 s (2026-10-02) : ce test parcourt l'AST de TOUT le depot (base.baseline). Sous charge,
# il a depasse les 30 s par defaut dans la CI de reference du sha 2acf5a16f -- et pytest-timeout,
# methode thread, tue alors TOUTE la suite (177 tests executes sur environ 13 000, SUITE_INCOMPLETE).
@pytest.mark.timeout(120)
def test_la_baseline_reelle_a_un_denominateur_non_vide():
    mesure = base.baseline()
    assert mesure["certifiant"] is True
    assert mesure["modules_du_depot"] > 500
    assert mesure["fichiers_lus"] > 500
