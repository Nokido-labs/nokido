# -*- coding: utf-8 -*-
"""NR — la delegation a AGY n'approuve plus TOUT par defaut.

Veille lot_B_12 / C_02 : `_delegate_to_agy` lancait agy avec `--dangerously-skip-permissions`.
`agy --help` (releve par l'owner le 2026-09-24) n'a pas de politique fine ; defaut retenu
`--sandbox --mode accept-edits --print-timeout <borne>`, repli `legacy` EXPLICITE seulement.

Le module de l'executeur n'est pas importe (effets de bord de demarrage) : la fonction pure
`_agy_permission_args` est recopiee depuis la source dans un module temporaire, puis chargee ;
et l'on verifie par l'AST que `_delegate_to_agy` l'APPELLE (sinon la fonction serait juste
mais inutilisee).
"""

import ast
import importlib.util
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "tools" / "forge_task_executor.py"


def _fonction(nom):
    texte = SRC.read_text(encoding="utf-8")
    for n in ast.parse(texte).body:
        if isinstance(n, ast.FunctionDef) and n.name == nom:
            return n, texte
    raise AssertionError("%s absente de %s" % (nom, SRC.name))


def _politique(tmp_path):
    noeud, texte = _fonction("_agy_permission_args")
    f = tmp_path / "agy_politique_nr.py"
    f.write_text("RELAY_TIMEOUT_S = 1500\n\n\n" + ast.get_source_segment(texte, noeud) + "\n",
                 encoding="utf-8")
    spec = importlib.util.spec_from_file_location("agy_politique_nr", f)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m._agy_permission_args


def test_defaut_sans_approbation_totale(tmp_path):
    a = _politique(tmp_path)({})
    assert "--dangerously-skip-permissions" not in a, a
    assert "--sandbox" in a and a[a.index("--mode") + 1] == "accept-edits", a
    assert a[a.index("--print-timeout") + 1].endswith("s"), "une permission sans reponse doit finir, pas pendre"


def test_repli_legacy_explicite(tmp_path):
    assert _politique(tmp_path)({"LAFORGE_AGY_PERMISSIONS": "legacy"}) == ["--dangerously-skip-permissions"]


def test_la_delegation_appelle_la_politique():
    noeud, _ = _fonction("_delegate_to_agy")
    appels = [n.func.id for n in ast.walk(noeud)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "_agy_permission_args" in appels, "la delegation n'utilise pas la politique de permissions"
