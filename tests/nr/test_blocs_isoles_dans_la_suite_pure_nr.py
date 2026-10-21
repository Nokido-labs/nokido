# -*- coding: utf-8 -*-
"""NR : un bloc ISOLE qui n'est pas dans PURE_TESTS ne tourne nulle part.

Mesure du 2026-10-18 : tools/ci_local.py ne retient les BLOCS_ISOLES que parmi les tests de PURE_TESTS
(`_isoles_presents`) ; 10 entrees sur 22 etaient hors PURE_TESTS -> jamais executees, dont 5 fichiers
test_hub_* ROUGES (19 echecs) que la CI de reference verte ne voyait pas. Declarer un test isole sans le
verser revient a l'eteindre en silence : un garde branche sur un signal que personne n'emet.

Un ecart n'est tolere que NOMME, avec sa raison, dans ISOLES_EN_REPARATION (tools/ci_local.py).
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _listes():
    arbre = ast.parse((ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8"))
    pure, isoles, reparation = [], [], {}
    for n in arbre.body:
        if not (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)):
            continue
        nom = n.targets[0].id
        if nom == "PURE_TESTS":
            pure = ast.literal_eval(n.value)
        elif nom == "BLOCS_ISOLES":
            isoles = [e.elts[0].value for e in n.value.elts
                      if isinstance(e, ast.Tuple) and e.elts and isinstance(e.elts[0], ast.Constant)]
        elif nom == "ISOLES_EN_REPARATION":
            reparation = ast.literal_eval(n.value)
    assert pure and isoles, "PURE_TESTS ou BLOCS_ISOLES illisible"
    return pure, isoles, reparation


def test_chaque_bloc_isole_tourne_ou_est_nomme_en_reparation():
    pure, isoles, reparation = _listes()
    inertes = [t for t in isoles if t not in pure and t not in reparation]
    assert not inertes, (
        "%d bloc(s) isole(s) hors PURE_TESTS -- jamais executes en CI :\n  %s\nLes verser dans PURE_TESTS, "
        "ou les nommer avec leur raison dans ISOLES_EN_REPARATION." % (len(inertes), "\n  ".join(inertes)))


def test_une_reparation_porte_sa_raison_et_ne_tourne_pas_deja():
    pure, isoles, reparation = _listes()
    assert isinstance(reparation, dict)
    for t, raison in reparation.items():
        assert isinstance(raison, str) and len(raison.strip()) >= 20, "%s : raison absente ou trop courte" % t
        assert t in isoles, "%s n'est pas un bloc isole : rien a reparer ici" % t
        assert t not in pure, "%s tourne deja (PURE_TESTS) : le retirer de ISOLES_EN_REPARATION" % t
