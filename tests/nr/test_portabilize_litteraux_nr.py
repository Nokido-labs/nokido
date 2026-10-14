# -*- coding: utf-8 -*-
"""Le portabiliseur ne reecrit qu'un litteral Python ENTIER (2026-10-09).

Sa regex prenait pour un litteral le chemin home entre guillemets NICHE dans un autre litteral, et y ecrivait
`__import__("os").path.expanduser(...)` EN TEXTE : 4 icacls inertes dans forge_sandbox_setup (droits jamais poses,
echec tu par check=False), une regex morte dans multi_llm_daemon, sa propre docstring. py_compile ne pouvait pas le
voir : le resultat compile.
"""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.timeout(60)
MOTIF = '__import__("os").path.expanduser('


def _portabiliseur():
    spec = importlib.util.spec_from_file_location("forge_path_portabilize_nr",
                                                  ROOT / "tools" / "forge_path_portabilize.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_seul_un_litteral_entier_est_reecrit():
    m = _portabiliseur()
    home = "C:\\" + "Users\\" + "Naar" + "ob"  # assemble : la generisation du dist ne doit pas reecrire ce test
    src = ('a = r"%s\\x"\n' % home
           + "b = rf'icacls \"%s\" /grant'\n" % home
           + "c = re.compile(r'(\"%s\\py\\.exe[^\"]+\")')\n" % home)
    nouveau, n, manuel = m.py_transform(src)
    lignes = nouveau.splitlines()
    assert n == 1 and lignes[0].startswith('a = ' + MOTIF)
    assert lignes[1] == src.splitlines()[1] and lignes[2] == src.splitlines()[2], "jamais une sous-chaine niche"
    assert len(manuel) == 2, "les occurrences non reecrites sont DITES"
    compile(nouveau, "<nr>", "exec")


def _motifs_du_demon():
    arbre = ast.parse((ROOT / "tools" / "multi_llm_daemon.py").read_text(encoding="utf-8"))
    for n in arbre.body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_CMD_PATTERNS":
            return [re.compile(c.args[0].value, re.IGNORECASE if len(c.args) > 1 else 0) for c in n.value.elts]
    raise AssertionError("_CMD_PATTERNS introuvable")


@pytest.mark.parametrize("texte,attendu", [
    ("Run D:/x/miniforge3/python.exe --version now", "D:/x/miniforge3/python.exe --version now"),
    ('Lancer "C:\\Users\\bob\\miniforge3\\python.exe" -V', "C:\\Users\\bob\\miniforge3\\python.exe"),
])
def test_l_extraction_de_commande_vaut_pour_toute_session(texte, attendu):
    trouves = [p.search(texte).group(1).strip().strip('"') for p in _motifs_du_demon() if p.search(texte)]
    assert attendu in trouves


@pytest.mark.parametrize("fichier", ["tools/forge_sandbox_setup.py", "tools/multi_llm_daemon.py"])
def test_aucune_chaine_de_code_ne_porte_l_expression_en_texte(fichier):
    arbre = ast.parse((ROOT / fichier).read_text(encoding="utf-8"))
    docstrings = {id(n.body[0].value) for n in ast.walk(arbre)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    fautives = [n.lineno for n in ast.walk(arbre) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and MOTIF in n.value and id(n) not in docstrings]
    assert fautives == [], "%s : expression en texte lignes %s" % (fichier, fautives)
