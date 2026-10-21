"""NR -- un pointeur `fichier::symbole` ou `fichier:ligne` designe un fichier EXISTANT, pas un fichier absent.

Mesure 19/10 (job_55a851be, AGY, enquete PUCT v2 jugee INTEGREE a la relecture) : `"pointer_ref":
"tools/forge_roadmap_keeper.py::plan_puct"` -> « [artefact ABSENT] fichier declare absent » et livraison classee en
echec. Le juge cherchait un fichier nomme `forge_roadmap_keeper.py::plan_puct`. Un vrai fichier absent reste accuse.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402


@pytest.fixture
def wt(tmp_path):
    (tmp_path / "outils_nr").mkdir()
    (tmp_path / "outils_nr" / "module_temoin.py").write_text("def f():\n    pass\n", encoding="utf-8")
    return str(tmp_path)


@pytest.mark.parametrize("ref", ["outils_nr/module_temoin.py::f", "outils_nr/module_temoin.py:2",
                                 "outils_nr/module_temoin.py#L1-L2", "outils_nr/module_temoin.py::Classe.methode"])
def test_un_suffixe_de_symbole_ou_de_ligne_ne_rend_pas_le_fichier_absent(wt, ref):
    assert T._artefact_declare_absent('{"pointer_ref": "%s"}' % ref, wt) is None


def test_un_fichier_vraiment_absent_reste_accuse(wt):
    r = T._artefact_declare_absent('{"pointer_ref": "outils_nr/module_fantome.py::f"}', wt)
    assert r and "module_fantome.py" in r
