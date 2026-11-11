"""NR : forge_contexte_par_source --reinjections dit, nom par nom, ce que pese ce qui revient a chaque compaction.

Debat tokens T11 (5/11) : une part par source (`skill_listing` 15 %) ne dit pas quoi couper ; sans le poids de chaque
skill et de chaque fichier, une coupe se decide a l'aveugle.
"""
import importlib.util
import json
import pathlib

_CHEMIN = pathlib.Path(__file__).resolve().parents[2] / "tools" / "forge_contexte_par_source.py"
_spec = importlib.util.spec_from_file_location("fcps_reinjections_nr", _CHEMIN)
fcps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fcps)

LISTING = "- forge-a: description\nsuite de la description\n- plugin:skill: autre\n- anthropic-skills:pdf\n"


def _att(**champs):
    return {"type": "attachment", "attachment": champs}


def _lignes(entrees):
    return {(x["genre"], x["nom"]): x for x in fcps.poids_reinjections(entrees)}


def test_listing_decoupe_par_skill_suite_comprise():
    r = _lignes([_att(type="skill_listing", content=LISTING)] * 2)
    assert r[("skill_listing", "forge-a")]["occurrences"] == 2
    assert r[("skill_listing", "forge-a")]["car"] == 2 * len("- forge-a: description\nsuite de la description\n")
    assert ("skill_listing", "plugin:skill") in r and ("skill_listing", "anthropic-skills:pdf") in r


def test_fichiers_memoire_et_skills_invoquees_par_nom():
    r = _lignes([
        _att(type="instructions", files=[{"path": "A.md", "content": "x" * 50}]),
        _att(type="nested_memory", path="B.md", content="y" * 40),
        _att(type="file", filename="C.py", content={"type": "text"}),
        _att(type="invoked_skills", skills=[{"name": "s1", "content": "z" * 30}]),
    ])
    assert set(r) == {("instructions", "A.md"), ("nested_memory", "B.md"), ("file", "C.py"), ("invoked_skills", "s1")}
    assert r[("instructions", "A.md")]["car"] > 50


def test_le_drapeau_ecrit_le_rapport(tmp_path, capsys):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps(_att(type="skill_listing", content=LISTING)) + "\n", encoding="utf-8")
    sortie = tmp_path / "r.json"
    assert fcps.main([str(t), "--reinjections", "--sortie", str(sortie)]) == 0
    assert json.loads(sortie.read_text(encoding="utf-8"))["t.jsonl"][0]["genre"] == "skill_listing"
