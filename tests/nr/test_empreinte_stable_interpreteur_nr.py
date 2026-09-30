"""NR -- l'empreinte du corps (L2/L3 du wiki) ne depend pas de la version de Python.

Mesure 2026-09-29 : `forge_wiki_modules.empreinte_du_corps` hachait `ast.dump(...)`, dont le format
change en 3.13 (champs vides omis par defaut). Les empreintes vues ont ete ecrites sous 3.12 ; le hub
tourne sous 3.14 : 2419 modules sortaient SUSPECTE au lieu de 229. Sous 3.14, avec show_empty=True,
le comptage redevient identique (2192 / 229 / 30). L'empreinte temoin ci-dessous a ete mesuree sous
3.12.12 ; elle doit etre la meme sous tout interpreteur >= 3.12.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMOIN = ('import os\n\ndef f(x, y=None):\n    """doc"""\n    return [x] if y is None else {x: y}\n\n'
          'class C:\n    """doc"""\n    def m(self):\n        pass\n')
EMPREINTE_312 = "d1c51adc23edcaad"


def _wm():
    spec = importlib.util.spec_from_file_location("nr_wm_empreinte", ROOT / "tools" / "forge_wiki_modules.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_meme_source_meme_empreinte_que_sous_python_312():
    assert _wm().empreinte_du_corps(TEMOIN) == EMPREINTE_312


def test_reformuler_une_docstring_ne_change_pas_l_empreinte_changer_le_code_si():
    wm = _wm()
    assert wm.empreinte_du_corps(TEMOIN.replace('"""doc"""', '"""autre doc"""')) == EMPREINTE_312
    assert wm.empreinte_du_corps(TEMOIN.replace("return [x]", "return (x,)")) != EMPREINTE_312


def test_source_illisible_rend_none_jamais_vide():
    assert _wm().empreinte_du_corps("def (:") is None
