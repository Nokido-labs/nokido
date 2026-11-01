"""NR : le prompt d'un banc d'amelioration n'envoie au generateur QUE les fonctions declarees (`fonctions`), pas le
fichier entier du perimetre (owner 29/10).

Mesure du 29/10 : le banc `rappel_lexical` envoyait app/forge_rag_engine.py entier (102 Ko, ~25 000 jetons) a
deepseek-coder:6.7b -> 0 bloc exploitable en 3 essais ; meme volume au-dela du plafond Groq gratuit (8 000 jetons/min).
Les segments rendus sont VERBATIM (ast.get_source_segment) : un bloc SEARCH copie du prompt retrouve le fichier.
Sans `fonctions`, le fichier entier reste envoye (comportement d'avant).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import forge_banc_amelioration as BA  # noqa: E402

SOURCE = '''import re

_MOTIFS = [r"a+", r"b+"]


def visee(x):
    """docstring visee"""
    return x + 1


def autre_tres_longue(y):
    return "CORPS_QUI_NE_DOIT_PAS_PARTIR" * y


class Moteur:
    def methode_visee(self):
        return 42

    def autre_methode(self):
        return "METHODE_QUI_NE_DOIT_PAS_PARTIR"
'''


def _banc(fonctions):
    b = {"perimetre": ["app/mod.py"], "juge": {"metrique": "metrique", "sens": "max"},
         "axes": [{"nom": "a", "description": "d"}]}
    if fonctions is not None:
        b["fonctions"] = fonctions
    return b


def _copie(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "mod.py").write_text(SOURCE, encoding="utf-8")
    return tmp_path


def test_seules_les_fonctions_declarees_partent(tmp_path):
    p = BA._prompt(_banc(["visee", "_MOTIFS", "methode_visee"]), _copie(tmp_path), 0)
    assert 'def visee(x):\n    """docstring visee"""\n    return x + 1' in p
    assert '_MOTIFS = [r"a+", r"b+"]' in p
    assert "def methode_visee(self):\n        return 42" in p
    assert "CORPS_QUI_NE_DOIT_PAS_PARTIR" not in p
    assert "METHODE_QUI_NE_DOIT_PAS_PARTIR" not in p


def test_sans_fonctions_le_fichier_entier_part(tmp_path):
    p = BA._prompt(_banc(None), _copie(tmp_path), 0)
    assert "CORPS_QUI_NE_DOIT_PAS_PARTIR" in p and "METHODE_QUI_NE_DOIT_PAS_PARTIR" in p


def test_fonction_introuvable_ne_vide_pas_le_prompt(tmp_path):
    p = BA._prompt(_banc(["inexistante"]), _copie(tmp_path), 0)
    assert "CORPS_QUI_NE_DOIT_PAS_PARTIR" in p
