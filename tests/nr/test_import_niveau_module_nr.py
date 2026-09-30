# -*- coding: utf-8 -*-
"""Non-regression — un nom utilise A LA PORTEE MODULE doit y etre defini.

Defaut mesure en production le 2026-08-26. `forge_autonomous_loops` portait
`import os` DANS trois fonctions (L493, L535, L1826) et nulle part au niveau module.
Une constante ajoutee le matin meme lisait `os.environ` a la portee module :

    OLLAMA_MODELE_LOCAL = os.environ.get("LAFORGE_LOOPS_OLLAMA_MODEL", ...)

Consequence : **le module entier cessait de s'importer** (`NameError: name 'os' is not
defined`). Les boucles autonomes et `/api/loops/status` tombaient — la route rendait un
500 dont le message ne nommait ni le module ni la ligne. Le commit voulait REPARER les
boucles ; il les a rendues inatteignables.

Ce qui rend ce defaut vicieux : `import os` apparait bien dans le fichier, trois fois.
Une relecture humaine — et un `findstr` — le declarent importe. Seule la PORTEE compte,
et elle ne se voit pas sans AST.

`noms_non_resolus(source)` est expose pour etre reutilise : c'est le meme piege partout.
Hermetique : lecture + AST, aucun import du module teste.
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__package__"}


def _definis_au_niveau_module(arbre: ast.Module) -> set:
    """Noms qu'un corps de module rend disponibles a sa propre portee.

    Ratisse LARGE a dessein. Un faux positif ici accuse un module sain et finit par
    faire desarmer le garde ; le vrai defaut (un nom JAMAIS lie, comme `os`) survit a
    cette largeur. Mesure a l'ecriture : la version etroite signalait `n`, `p` (cibles
    de comprehensions, qui ont leur propre portee) et `e` (`except ... as e`) sur un
    module dont l'import REUSSIT — trois faux positifs, corriges avant commit."""
    noms = set()

    def _lier(noeud):
        for x in ast.walk(noeud):
            if isinstance(x, (ast.Import, ast.ImportFrom)):
                for a in x.names:
                    noms.add((a.asname or a.name).split(".")[0])
            elif isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)):
                noms.add(x.id)          # affectation, for, with-as, walrus, comprehension
            elif isinstance(x, ast.ExceptHandler) and x.name:
                noms.add(x.name)        # `except E as e` lie e dans le bloc
            elif isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                noms.add(x.name)

    for n in arbre.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            noms.add(n.name)            # sans descendre : leur corps est une autre portee
        else:
            _lier(n)                    # un import sous try:/if: definit bien le nom
    return noms


def noms_non_resolus(source: str, nom_fichier: str = "<source>") -> list:
    """Noms LUS a la portee module sans y etre definis -> (nom, ligne).

    Ne descend PAS dans les corps de fonctions/classes : un `import os` local y est
    parfaitement valide, et c'est exactement ce qui masquait le defaut."""
    arbre = ast.parse(source, filename=nom_fichier)
    connus = _definis_au_niveau_module(arbre) | _BUILTINS
    manquants = []
    for n in arbre.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue                      # portee distincte
        for x in ast.walk(n):
            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load) \
                    and x.id not in connus:
                manquants.append((x.id, x.lineno))
    return manquants


# ------------------------------------------------- l'outil sait mordre (contre-epreuve)

def test_detecte_le_cas_reel_paye():
    """Reproduction exacte : `import os` seulement dans une fonction."""
    src = ("def f():\n    import os\n    return os.getcwd()\n\n"
           "CONST = os.environ.get('X', 'defaut')\n")
    assert ("os", 5) in noms_non_resolus(src)


def test_import_au_niveau_module_resout():
    src = "import os\n\ndef f():\n    import os\n    return os\n\nCONST = os.environ.get('X')\n"
    assert noms_non_resolus(src) == []


def test_import_sous_try_compte_comme_defini():
    """Un import garde est un import : le refuser ferait crier a faux."""
    src = "try:\n    import ujson as json\nexcept ImportError:\n    import json\n\nX = json.dumps({})\n"
    assert noms_non_resolus(src) == []


def test_alias_reconnu():
    src = "import os as _os\n\nX = _os.sep\n"
    assert noms_non_resolus(src) == []


def test_from_import_reconnu():
    src = "from pathlib import Path\n\nRACINE = Path('.')\n"
    assert noms_non_resolus(src) == []


def test_import_pointe_donne_le_nom_racine():
    src = "import logging.handlers\n\nH = logging.handlers.RotatingFileHandler\n"
    assert noms_non_resolus(src) == []


def test_les_builtins_ne_sont_pas_signales():
    src = "X = len([1, 2, 3])\nY = sorted({'a'})\n"
    assert noms_non_resolus(src) == []


def test_un_nom_utilise_dans_une_fonction_seulement_nest_pas_signale():
    """C'est LE point : la portee fonction a le droit d'importer pour elle seule."""
    src = "def f():\n    import os\n    return os.getcwd()\n"
    assert noms_non_resolus(src) == []


# --- les trois faux positifs mesures a l'ecriture, pour qu'ils ne reviennent pas ---

def test_cible_de_comprehension_non_signalee():
    src = "SOURCE = [1, 2]\nCARRES = [n * n for n in SOURCE]\n"
    assert noms_non_resolus(src) == []


def test_except_as_non_signale():
    src = "try:\n    X = 1\nexcept ValueError as e:\n    X = str(e)\n"
    assert noms_non_resolus(src) == []


def test_for_et_with_as_non_signales():
    src = ("import io\nTOTAL = 0\nfor p in [1, 2]:\n    TOTAL += p\n"
           "with io.StringIO() as f:\n    TAILLE = f.tell()\n")
    assert noms_non_resolus(src) == []


# ----------------------------------------------- le module reellement tombe en prod

def test_forge_autonomous_loops_est_importable():
    cible = ROOT / "app" / "forge_autonomous_loops.py"
    if not cible.exists():
        pytest.skip("module absent de cette copie")
    manquants = noms_non_resolus(cible.read_text(encoding="utf-8", errors="replace"),
                                 str(cible))
    assert not manquants, (
        "noms lus a la portee module sans y etre definis — le module ne s'importera "
        "PAS : %s" % manquants)
