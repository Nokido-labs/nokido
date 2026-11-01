# -*- coding: utf-8 -*-
"""NR -- un double `None` posé dans sys.modules fait lever ImportError, y compris via le paquet parent.

Constat (22/10, bb:architecture_rules/bug_double_none_rend_none_au_lieu_d_importerror_20261022) : tests/conftest.py
(`_setitem_avec_attribut`) pose aussi l'attribut du paquet parent quand on pose un double dans sys.modules. Pour
une valeur `None` (« module indisponible »), `sys.modules[nom] = None` fait lever ImportError, alors que
`paquet.X = None` fait rendre None à `from paquet import X` SANS erreur. Contrat :
  1. `monkeypatch.setitem(sys.modules, "pkg.X", None)` -> `from pkg import X` leve ImportError ;
  2. un double module (non None) reste lu par `from pkg import X` (comportement existant conserve) ;
  3. tout est restauré en fin de test (sys.modules ET attribut du paquet).
"""
import sys

import pytest

import app.forge_memory_availability as reel  # noqa: F401  (vrai module : l'attribut du paquet existe)

NOM = "app.forge_memory_availability"
ENFANT = "forge_memory_availability"


def test_none_dans_sys_modules_leve_importerror(monkeypatch):
    monkeypatch.setitem(sys.modules, NOM, None)
    with pytest.raises(ImportError):
        from app import forge_memory_availability  # noqa: F401


def test_double_module_reste_lu_par_from_import(monkeypatch):
    double = type(sys)("app.forge_memory_availability")
    monkeypatch.setitem(sys.modules, NOM, double)
    from app import forge_memory_availability
    assert forge_memory_availability is double


def test_restauration_en_fin_de_test():
    # Après les deux tests ci-dessus, le vrai module est revenu dans sys.modules ET sur le paquet.
    import app
    assert sys.modules[NOM] is reel
    assert getattr(app, ENFANT) is reel
