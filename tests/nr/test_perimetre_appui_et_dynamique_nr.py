# -*- coding: utf-8 -*-
"""Non-regression — le perimetre voit les tests d'APPUI et les imports DYNAMIQUES.

Mesure du 2026-09-08, apres generation de 57 tests d'appui : la couverture n'a bouge
que de 448 a 449. Les tests generes etaient INVISIBLES a mon propre capteur, par deux
angles morts qui se cumulaient :

  - NOMMAGE : ils s'appellent `test_appui_<stem>_nr.py`, qui ne correspond a aucune
    des quatre conventions (`test_<stem>_nr.py`, `test_<court>_nr.py`, ...).
  - IMPORT : ils font `importlib.import_module("forge_x")` — une CHAINE. La detection
    par import ne lisait que les `import x` / `from x import y` STATIQUES.

J'ai donc genere 57 tests qui ne comptaient pas dans la metrique qu'ils devaient faire
monter. Sans la mesure, j'aurais annonce un progres inexistant.

CHIFFRAGE PREALABLE, par simulation avant d'ecrire le correctif :
    5e convention (appui)  +57
    imports dynamiques      +2      <- et non "le plus payant", comme je l'avais dit
    total  449 -> 508  (19,8 % -> 22,3 %)
Le comptage de fichiers concernes (72) ne dit RIEN du gain : ces fichiers couvrent
presque tous des modules deja vus par une autre voie.

Hermetique : arborescence fabriquee en tmp_path, racine injectee.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_mutation_judge import perimetre_mesure, perimetre_mesure_detail  # noqa: E402


def _ecrire(base: Path, rel: str, contenu: str) -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenu, encoding="utf-8")


def test_le_test_d_appui_est_vu_par_convention(tmp_path):
    """`test_appui_<stem>_nr.py` est la 5e convention : c'est celle des generes."""
    _ecrire(tmp_path, "app/forge_zzz.py", "x = 1\n")
    _ecrire(tmp_path, "tests/nr/test_appui_forge_zzz_nr.py",
            "def test_le_module_se_charge():\n    assert 1\n")
    assert perimetre_mesure("app/forge_zzz.py", racine=tmp_path) == \
        ["tests/nr/test_appui_forge_zzz_nr.py"]


def test_un_import_DYNAMIQUE_est_vu(tmp_path):
    """`import_module("x")` exerce le module autant qu'un import statique."""
    _ecrire(tmp_path, "app/forge_dyn.py", "x = 1\n")
    _ecrire(tmp_path, "tests/nr/test_autre_chose_nr.py",
            'import importlib\n\n\ndef test_a():\n'
            '    assert importlib.import_module("forge_dyn")\n')
    assert perimetre_mesure("app/forge_dyn.py", racine=tmp_path) == \
        ["tests/nr/test_autre_chose_nr.py"]


def test_la_convention_nommee_passe_devant_l_appui(tmp_path):
    """Un NR ecrit a la main prime sur un appui genere : il en dit plus."""
    _ecrire(tmp_path, "app/forge_zzz.py", "x = 1\n")
    _ecrire(tmp_path, "tests/nr/test_forge_zzz_nr.py", "def test_a():\n    assert 1\n")
    _ecrire(tmp_path, "tests/nr/test_appui_forge_zzz_nr.py", "def test_b():\n    assert 1\n")
    r = perimetre_mesure("app/forge_zzz.py", racine=tmp_path)
    assert r[0] == "tests/nr/test_forge_zzz_nr.py", r


def test_pas_de_doublon_entre_convention_et_import(tmp_path):
    _ecrire(tmp_path, "app/forge_zzz.py", "x = 1\n")
    _ecrire(tmp_path, "tests/nr/test_appui_forge_zzz_nr.py",
            'import importlib\n\n\ndef test_a():\n'
            '    assert importlib.import_module("forge_zzz")\n')
    r = perimetre_mesure("app/forge_zzz.py", racine=tmp_path)
    assert r == ["tests/nr/test_appui_forge_zzz_nr.py"]


def test_une_MENTION_du_nom_ne_suffit_toujours_pas(tmp_path):
    """Elargir la detection ne doit pas la rendre credule."""
    _ecrire(tmp_path, "app/forge_zzz.py", "x = 1\n")
    _ecrire(tmp_path, "tests/nr/test_mention_nr.py",
            "# import_module de forge_zzz serait bien\nNOM = 'forge_zzz'\n\n\n"
            "def test_r():\n    assert 1\n")
    assert perimetre_mesure("app/forge_zzz.py", racine=tmp_path) == []


def test_le_detail_range_l_appui_dans_la_convention(tmp_path):
    _ecrire(tmp_path, "app/forge_zzz.py", "x = 1\n")
    _ecrire(tmp_path, "tests/nr/test_appui_forge_zzz_nr.py", "def test_a():\n    assert 1\n")
    d = perimetre_mesure_detail("app/forge_zzz.py", racine=tmp_path)
    assert d["par_convention"] == ["tests/nr/test_appui_forge_zzz_nr.py"]
    assert d["par_import"] == []
