# -*- coding: utf-8 -*-
"""NR — importer `tools/paste_clean.py` ne doit plus toucher `sys.stdout`.

Le module remplacait `sys.stdout` ET `sys.stderr` (quand leur encodage n'est pas utf-8)
a l'IMPORT, pour forcer l'UTF-8 quand il est lance en script. Importe par un test, il
enveloppait le fichier de CAPTURE de pytest dans un `TextIOWrapper` qui le fermait en
etant ramasse : `ValueError: I/O operation on closed file` dans `_pytest/capture.py`, et
une collecte tronquee sans autre message (mesures/audits/stabilite_ci.md, section 2.2 --
symptome que `ci.yml` imputait a pytest 9). Le remplacement vit desormais dans le point
d'entree (`if __name__ == "__main__":`) : le script le garde, l'import ne le fait plus.
"""
import ast
import importlib.util
import io
import logging
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
CHEMIN = RACINE / "tools" / "paste_clean.py"


def _fausse_sortie():
    # `.buffer` present ET encodage non utf-8 : declenche les deux formes de l'ancien
    # remplacement (`hasattr(sys.stdout, "buffer")` et `encoding != "utf-8"`).
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252")


def test_importer_le_module_laisse_stdout_et_stderr_intacts(monkeypatch):
    sortie, erreur = _fausse_sortie(), _fausse_sortie()
    monkeypatch.setattr(sys, "stdout", sortie)
    monkeypatch.setattr(sys, "stderr", erreur)
    # Un `logging.basicConfig(stream=sys.stderr)` a l'import accrocherait sinon un handler
    # a la fausse sortie pour la suite du processus : on restaure les handlers racine.
    monkeypatch.setattr(logging.root, "handlers", list(logging.root.handlers))
    spec = importlib.util.spec_from_file_location("_nr_stdout_paste_clean", CHEMIN)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as exc:  # dependance tierce absente : l'import ne se mesure pas
        pytest.skip("dependance absente a l'import : %s" % exc.name)
    assert sys.stdout is sortie, "importer paste_clean.py a remplace sys.stdout"
    assert sys.stderr is erreur, "importer paste_clean.py a remplace sys.stderr"


def _affectations_de_sortie_au_niveau_module(arbre):
    """Affectations de `<x>.stdout` / `<x>.stderr` executees a l'import : hors fonctions,
    hors classes, hors bloc `if __name__ == "__main__":`."""
    trouvees = []

    def _parcourir(instrs):
        for n in instrs:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(n, ast.If) and "__name__" in ast.unparse(n.test) and "__main__" in ast.unparse(n.test):
                continue
            for x in ast.walk(n):
                cibles = x.targets if isinstance(x, ast.Assign) else ([x.target] if isinstance(x, (ast.AnnAssign, ast.AugAssign)) else [])
                for c in cibles:
                    if isinstance(c, ast.Attribute) and c.attr in ("stdout", "stderr"):
                        trouvees.append(n.lineno)

    _parcourir(arbre.body)
    return trouvees


def test_aucun_remplacement_de_sortie_n_est_execute_a_l_import():
    arbre = ast.parse(CHEMIN.read_text(encoding="utf-8"))
    assert _affectations_de_sortie_au_niveau_module(arbre) == []


def test_le_point_d_entree_garde_le_remplacement():
    """Le script lance directement doit toujours forcer l'UTF-8 : on a DEPLACE, pas supprime."""
    arbre = ast.parse(CHEMIN.read_text(encoding="utf-8"))
    principal = [n for n in arbre.body if isinstance(n, ast.If)
                 and "__main__" in ast.unparse(n.test)]
    assert principal and any(
        isinstance(c, ast.Attribute) and c.attr == "stdout"
        for n in principal for x in ast.walk(n) if isinstance(x, ast.Assign) for c in x.targets)
