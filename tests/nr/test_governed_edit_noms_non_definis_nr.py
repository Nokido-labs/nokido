"""NR du 27/10 : governed_edit signale les noms NON DEFINIS d'un .py (pyflakes F821), sans bloquer l'ecriture.

Mesure : `json.loads` dans un module qui importe `json as _json` est passe par « AST+secret OK », puis a coute
deux tours de NR (NameError avale par un except). L'AST ne voit pas un nom non resolu ; pyflakes si.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import forge_governed_edit as G  # noqa: E402


def test_un_nom_non_defini_est_signale():
    code = "import json as _json\n\ndef f(l):\n    return json.loads(l)\n"
    assert G.noms_non_definis(code) == ["json"]


def test_un_code_propre_ne_signale_rien():
    assert G.noms_non_definis("import json\n\ndef f(l):\n    return [json.loads(x) for x in l]\n") == []


def test_une_syntaxe_cassee_ne_leve_pas():
    assert G.noms_non_definis("def f(:\n") == []  # la syntaxe est le travail de la garde AST, pas de celle-ci
