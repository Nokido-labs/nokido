# -*- coding: utf-8 -*-
"""NR — une docstring de module n'est plus masquee par un `from __future__` place avant elle.

Mesure 2026-09-29 : 179 modules d'app/ + tools/ commencaient par
`from __future__ import annotations` PUIS leur docstring : `__doc__` valait None,
le wiki les comptait « sans docstring ». Correction = permutation prouvee par AST
(`tools/forge_docstring_masquee.py`). Ce NR tient les deux bouts : la permutation
est exacte et refuse ce qu'elle ne sait pas faire sans risque ; et le depot ne
gagne AUCUN nouveau module masque (cliquet sur `_socle_docstring_masquee.json`,
qui ne liste que les modules laisses a l'owner : critiques, juges, en travail).
"""
import ast
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("forge_docstring_masquee", ROOT / "tools" / "forge_docstring_masquee.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
SOCLE = Path(__file__).resolve().parent / "_socle_docstring_masquee.json"

MASQUEE = (
    "from __future__ import annotations\n"
    "\n"
    "# -*- coding: utf-8 -*-\n"
    '"""Titre du module.\n'
    "\n"
    'Detail."""\n'
    "__FORGE_COLOR__ = 'x/y'\n"
    "import os\n"
)


def test_la_docstring_masquee_est_detectee_et_python_ne_la_voit_pas():
    assert ast.get_docstring(ast.parse(MASQUEE)) is None
    d = M.diagnostiquer(MASQUEE)
    assert d["masquee"] and d["corrigeable"], d


def test_la_correction_rend_la_docstring_et_ne_change_que_l_ordre():
    nouveau, motif = M.demasquer(MASQUEE)
    assert nouveau is not None, motif
    assert ast.get_docstring(ast.parse(nouveau)).startswith("Titre du module.")
    compile(nouveau, "<nr>", "exec")          # `from __future__` reste legal apres une docstring
    avant, apres = ast.parse(MASQUEE).body, ast.parse(nouveau).body
    assert ast.dump(apres[0]) == ast.dump(avant[1]) and ast.dump(apres[1]) == ast.dump(avant[0])
    assert [ast.dump(n) for n in apres[2:]] == [ast.dump(n) for n in avant[2:]]
    assert nouveau.startswith("# -*- coding: utf-8 -*-\n"), "la tete du fichier ne commence pas par un blanc"
    assert M.diagnostiquer(nouveau)["masquee"] is False


def test_plusieurs_futures_passent_tous_apres_la_docstring():
    src = 'from __future__ import annotations\nfrom __future__ import division\n"""Doc."""\nx = 1\n'
    nouveau, motif = M.demasquer(src)
    assert nouveau == '"""Doc."""\nfrom __future__ import annotations\nfrom __future__ import division\nx = 1\n', motif


def test_une_ligne_partagee_n_est_pas_devinee():
    """Du code sur la ligne de la docstring : deplacer par lignes l'emporterait -- refus DIT."""
    src = 'from __future__ import annotations\n"""Doc."""; x = 1\n'
    d = M.diagnostiquer(src)
    assert d["masquee"] and not d["corrigeable"] and d["motif"]
    assert M.demasquer(src)[0] is None


def test_un_module_sain_ou_sans_docstring_n_est_pas_masque():
    assert M.diagnostiquer('"""Doc."""\nfrom __future__ import annotations\n')["masquee"] is False
    assert M.diagnostiquer("from __future__ import annotations\nx = 1\n")["masquee"] is False
    assert M.diagnostiquer("def (:\n")["motif"].startswith("ILLISIBLE")


def test_aucun_nouveau_module_masque_dans_le_depot():
    """Cliquet : un module masque hors socle est une regression (le trou revient)."""
    socle = set(json.loads(SOCLE.read_text(encoding="utf-8"))["modules"])
    trouves = M.masquees(ROOT)
    illisibles = sorted(r for r, d in trouves.items() if d["masquee"] is None)
    assert not illisibles, "illisibles, donc NON juges (pas sains par defaut) : %s" % illisibles
    nouveaux = sorted(set(trouves) - socle)
    assert not nouveaux, (
        "docstring de module masquee par un `from __future__` place AVANT elle "
        "(__doc__ = None) -- corriger par tools/forge_docstring_masquee.py : %s" % nouveaux)
