"""NR : le banc d'amelioration applique un bloc SEARCH dont le generateur a perdu l'indentation (owner 29/10).

Mesure du 29/10 : qwen2.5-coder 7B rend des blocs justes mais desindentes, sans la ligne vide du corps
(`import re\\nreturn ...` pour `    import re\\n\\n    return ...`) -> 2 NON_APPLICABLE sur 3. Repli tolerant : fenetre
UNIQUE dont les lignes non vides correspondent espaces ignores, remplacement reindente du meme decalage ; fenetre
ambigue = refus ; la correspondance exacte reste prioritaire ; le controle AST de l'outil existant s'applique toujours.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import forge_banc_amelioration as BA  # noqa: E402

SOURCE = 'def f(q):\n    """doc"""\n    import re\n\n    return " OR ".join(re.split(r"\\W+", q))\n\n\ndef g():\n    return 1\n'


def _exact(fp, s, r):
    t = fp.read_text(encoding="utf-8")
    if s not in t:
        return False, "search string not found in file"
    fp.write_text(t.replace(s, r, 1), encoding="utf-8")
    return True, t


def test_bloc_desindente_applique_et_reindente(tmp_path):
    fp = tmp_path / "m.py"
    fp.write_text(SOURCE, encoding="utf-8")
    ok, _ = BA._appliquer_tolerant(fp, 'import re\nreturn " OR ".join(re.split(r"\\W+", q))',
                                   'import re\nmots = re.split(r"\\W+", q)\nreturn " OR ".join(mots)', _exact)
    assert ok
    t = fp.read_text(encoding="utf-8")
    assert '    import re\n    mots = re.split(r"\\W+", q)\n    return " OR ".join(mots)\n' in t
    assert "def g():\n    return 1" in t
    compile(t, "m.py", "exec")


def test_correspondance_exacte_prioritaire(tmp_path):
    fp = tmp_path / "m.py"
    fp.write_text(SOURCE, encoding="utf-8")
    ok, _ = BA._appliquer_tolerant(fp, "def g():\n    return 1", "def g():\n    return 2", _exact)
    assert ok and "def g():\n    return 2" in fp.read_text(encoding="utf-8")


def test_fenetre_ambigue_refusee(tmp_path):
    fp = tmp_path / "m.py"
    fp.write_text("def a():\n    return 1\n\n\ndef b():\n    return 1\n", encoding="utf-8")
    ok, err = BA._appliquer_tolerant(fp, "return 1", "return 2", _exact)
    assert not ok and "ambigu" in err
    assert fp.read_text(encoding="utf-8").count("return 1") == 2


def test_rien_ne_correspond(tmp_path):
    fp = tmp_path / "m.py"
    fp.write_text(SOURCE, encoding="utf-8")
    ok, err = BA._appliquer_tolerant(fp, "x = 42", "x = 43", _exact)
    assert not ok and fp.read_text(encoding="utf-8") == SOURCE
