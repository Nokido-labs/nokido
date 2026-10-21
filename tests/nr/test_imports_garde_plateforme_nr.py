"""NR -- l'etape `imports` de la recette lit les gardes de PLATEFORME et la presence telle qu'un NOUVEAU processus la voit.

Audit de la dist publique (20/10, run 38863059811) : l'etape `imports` declarait 9 services BLOQUES par
win32api/win32event sur les TROIS systemes, alors que la mesure de l'organisme, dans le meme run, les montrait tous
TOURNE (57 TOURNE, `ne_tournent_pas` vide). Deux defauts du classifieur, pas des services :
  * `tools/forge_runas_launcher.py::main` fait `if os.name != "nt": return main_posix(...)` AVANT `import win32event` :
    hors Windows ces imports ne s'executent jamais. Le classifieur ne lisait pas le garde ;
  * sous Windows, pywin32 est installe par pip PENDANT la recette ; son `.pth` (win32, win32/lib) n'est lu qu'au
    demarrage d'un interpreteur, donc `find_spec('win32api')` echouait dans le processus de la recette seulement.

Ce qui est garde : un import propre a l'autre plateforme n'est pas requis, et il est DIT (`hors_plateforme`), jamais
efface ; un test de plateforme dont on ne peut rien deduire (`sys.platform != "linux"`) ne retire rien ; un module
rendu visible par un `.pth` pose pendant la recette n'est pas « manquant ».
"""
from __future__ import annotations

import importlib.util
import site
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("acceptance_plateforme_nr", RACINE / "tools" / "forge_install_acceptance.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.R.clear()
    return m


def test_un_retour_anticipe_hors_windows_rend_les_imports_suivants_propres_a_windows(tmp_path, monkeypatch):
    m = _module()
    entree = tmp_path / "lanceur.py"
    entree.write_text(
        "import os\n"
        "def main():\n"
        "    if os.name != 'nt':\n"
        "        return main_posix()\n"
        "    import module_win_xyz\n"
        "if __name__ == '__main__':\n    main()\n", encoding="utf-8")
    monkeypatch.setattr(m, "WIN", False)
    r = m.imports_tiers(entree, locaux={})
    assert "module_win_xyz" not in r["requis"]
    assert r["hors_plateforme"] == {"module_win_xyz"}, "un import ecarte est DIT, pas efface"
    b = m.bilan_imports({"S": entree}, locaux={})
    assert b["services_bloques"] == [] and b["hors_plateforme"] == {"module_win_xyz": ["S"]}
    monkeypatch.setattr(m, "WIN", True)
    assert "module_win_xyz" in m.imports_tiers(entree, locaux={})["requis"]


def test_les_branches_de_plateforme_et_le_test_indecidable(tmp_path, monkeypatch):
    m = _module()
    entree = tmp_path / "svc.py"
    entree.write_text(
        "import sys\n"
        "if sys.platform == 'win32':\n    import mod_seul_win_xyz\nelse:\n    import mod_seul_posix_xyz\n"
        "if sys.platform != 'linux':\n    import mod_indecidable_xyz\n", encoding="utf-8")
    monkeypatch.setattr(m, "WIN", False)
    r = m.imports_tiers(entree, locaux={})
    assert r["requis"] == {"mod_seul_posix_xyz", "mod_indecidable_xyz"}, "vrai sous Windows ET macOS : rien a deduire"
    monkeypatch.setattr(m, "WIN", True)
    r = m.imports_tiers(entree, locaux={})
    assert r["requis"] == {"mod_seul_win_xyz", "mod_indecidable_xyz"}


def test_le_lanceur_runas_reel_n_exige_pywin32_que_sous_windows(monkeypatch):
    m = _module()
    lanceur = m.ROOT / "tools" / "forge_runas_launcher.py"
    monkeypatch.setattr(m, "WIN", False)
    assert "win32event" not in m.imports_tiers(lanceur, m._locaux_du_depot())["requis"]
    monkeypatch.setattr(m, "WIN", True)
    assert "win32event" in m.imports_tiers(lanceur, m._locaux_du_depot())["requis"]


def test_un_module_rendu_visible_par_un_pth_pose_pendant_la_recette_n_est_pas_absent(tmp_path, monkeypatch):
    m = _module()
    sp = tmp_path / "site"
    (sp / "lib_pth").mkdir(parents=True)
    (sp / "lib_pth" / "mod_pth_xyz_42.py").write_text("", encoding="utf-8")
    (sp / "paquet.pth").write_text("lib_pth\n", encoding="utf-8")
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(site, "getsitepackages", lambda: [str(sp)])
    monkeypatch.setattr(site, "getusersitepackages", lambda: str(tmp_path / "absent"))
    entree = tmp_path / "svc.py"
    entree.write_text("import mod_pth_xyz_42\n", encoding="utf-8")
    b = m.bilan_imports({"S": entree}, locaux={})
    assert b["manquants_requis"] == {} and b["services_bloques"] == [], b
