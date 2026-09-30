# -*- coding: utf-8 -*-
"""NR — UNE seule version, declaree a deux endroits qui ne doivent jamais diverger.

__FORGE_COLOR__ = "qualite/build : non-regression de l'invariant de version"

Contrat owner du 2026-09-10 :

    git tag = pyproject.version = wheel = sdist = PyPI = GitHub Release

Le job `build` garde deja tag == pyproject == artefacts. Mais le paquet declare
AUSSI sa version dans son propre `__init__` :

    pyproject.toml            version     = "0.20.0"
    nokido_agent/__init__.py  __version__ = "0.20.0"

et `verify-testpypi` IMPRIME `nokido_agent.__version__` comme preuve de ce qui
est installe. Si les deux divergent, la preuve affiche une version que
l'artefact ne porte pas — un temoin qui ment est pire qu'un temoin absent.

DEFAUT MESURE le 2026-09-10 : au moment du bump 0.19.0 -> 0.20.0, rien ne
garantissait que les deux bougent ensemble. Trouve en cherchant OU vit la
version, pas par un test.

Lecture par AST et par texte, jamais par import : le module `nokido_agent`
installe un MetaPathFinder a l'import, et un NR n'a pas a le declencher pour
lire une constante.
"""
from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "nokido_agent" / "__init__.py"

_SEMVER = re.compile(r"^\d+\.\d+\.\d+([.\-+].+)?$")


def _version_pyproject() -> str:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]


def _version_init() -> str | None:
    """`__version__` lu dans l'AST — sans executer le module."""
    arbre = ast.parse(INIT.read_text(encoding="utf-8"))
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant):
            for cible in n.targets:
                if isinstance(cible, ast.Name) and cible.id == "__version__":
                    return n.value.value
    return None


def test_les_deux_declarations_EXISTENT():
    """Denominateur : si `__version__` disparaissait, le test d'egalite passerait
    a vide et l'invariant ne serait plus garde par rien."""
    assert PYPROJECT.is_file(), "pyproject.toml introuvable"
    assert INIT.is_file(), "nokido_agent/__init__.py introuvable"
    assert _version_init() is not None, (
        "`__version__` a disparu de nokido_agent/__init__.py — verify-testpypi "
        "l'imprime comme preuve de ce qui est installe")


def test_pyproject_et_le_paquet_declarent_la_MEME_version():
    p, i = _version_pyproject(), _version_init()
    assert p == i, (
        f"versions divergentes : pyproject={p!r} mais nokido_agent.__version__={i!r}. "
        "La preuve d'installation afficherait une version que l'artefact ne porte pas.")


def test_la_version_a_une_forme_exploitable_par_un_TAG():
    """Le tag vaut `v` + cette chaine, et le job `build` compare les deux : une
    version fantaisiste rendrait la garde tag == pyproject ininterpretable."""
    p = _version_pyproject()
    assert _SEMVER.match(p), f"version non exploitable comme tag : {p!r}"
