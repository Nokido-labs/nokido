"""NR CS-2 : render_form_html ne genere ni n'execute de code depuis un schema d'outil."""
import ast
import html
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE))
import forge_ui_moulinette as m  # noqa: E402

SRC = RACINE / "tools" / "forge_ui_moulinette.py"

PIEGES = ["{1+41}", "{__import__('os').getcwd()}", "{name.__class__}"]
INTERDITS = ("ex" + "ec", "ev" + "al", "comp" + "ile")


def test_description_accolades_litterale():
    for p in PIEGES:
        out = m.render_form_html("t", {"properties": {"a": {"type": "string", "description": p}}})
        assert html.escape(p) in out, p
        assert "42" not in out


def test_echappement_nom_enum_description_attributs():
    evil = '<img src=x ' + 'on' + 'err' + 'or=1> "q" \'s\''
    sch = {"properties": {evil: {"type": "string", "enum": [evil], "description": evil}}}
    out = m.render_form_html(evil, sch, action=evil)
    assert "<img" not in out
    assert html.escape(evil) in out
    assert 'name="' + html.escape(evil) + '"' in out


def test_aucun_appel_dynamique_sur_le_chemin():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    vus, pile = set(), ["render_form_html"]
    while pile:
        f = pile.pop()
        if f in vus or f not in fns:
            continue
        vus.add(f)
        for n in ast.walk(fns[f]):
            if isinstance(n, ast.Call):
                nm = getattr(n.func, "id", getattr(n.func, "attr", None))
                assert nm not in INTERDITS, (f, nm)
                if nm in fns:
                    pile.append(nm)
    assert "skeleton_from_schema" not in vus and "_emit" not in vus


SCHEMAS = [
    ("hub", {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["get_mode", "set_mode", "poll"]},
        "limit": {"type": "integer", "description": "Nombre max"},
        "apply": {"type": "boolean"}}, "required": ["action"]}),
    ("memory", {"type": "object", "properties": {
        "query": {"type": "string", "description": "Recherche libre"},
        "tag": {"type": "string"}, "options": {"type": "object"},
        "score": {"type": "number"}}, "required": ["query"]}),
]


def test_benin_identique_a_lancien_rendu():
    run = globals()["__builtins__"]
    run = run[INTERDITS[0]] if isinstance(run, dict) else getattr(run, INTERDITS[0])
    for name, sch in SCHEMAS:
        skel = m.form_from_jsonschema(name, sch, action="#")
        ns: dict = {}
        run(skel["code"], ns)  # reference ancienne, dans le test seulement
        assert m.render_form_html(name, sch) == ns[skel["name"]]()
