"""NR — enrichissement + recovery (Phases 2 & 5).

Ce qu'on protege : (1) le resume AST extrait vraiment fonctions/classes/doc ;
(2) le classement biomimetique reconnait les couches ; (3) le score priorise
DELETED-substantiel-documente-biomimetique ; (4) un plafond n'est jamais silencieux.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_le_resume_ast_extrait_symboles_et_doc():
    import forge_archaeology_enrich as E

    code = '"""Fait la regulation."""\nimport os\nclass A:\n    pass\ndef f():\n    return 1\n'
    r = E._resume_ast(code)
    assert r["parse"] and r["n_class"] == 1 and r["n_func"] == 1
    assert "regulation" in r["doc1"].lower()
    assert "A" in r["symboles"] and "f" in r["symboles"]


def test_un_fichier_non_parsable_ne_casse_pas():
    import forge_archaeology_enrich as E

    r = E._resume_ast("def f(:\n  pass")
    assert r["parse"] is False and r["loc"] >= 1


def test_les_couches_biomimetiques_sont_reconnues():
    import forge_archaeology_enrich as E

    assert "HOMEOSTASIS" in E._couches("forge_regulation.py", "evict services", [])
    assert "MEMORY" in E._couches("x.py", "rag recall", ["remember"])
    assert E._couches("banal.py", "un helper", ["util"]) == []


def test_le_score_priorise_deleted_riche_documente_biomimetique():
    import forge_archaeology_enrich as E

    riche = {"etat": "DELETED"}
    ast_riche = {"n_func": 8, "n_class": 2, "doc1": "regulation adaptative"}
    pauvre = {"etat": "REPLACED"}
    ast_pauvre = {"n_func": 0, "n_class": 0, "doc1": ""}
    s_riche = E._score_recovery(riche, ast_riche, ["HOMEOSTASIS", "LEARNING"])
    s_pauvre = E._score_recovery(pauvre, ast_pauvre, [])
    assert s_riche > s_pauvre
    assert 0.0 <= s_pauvre <= s_riche <= 1.0


def test_le_plafond_est_annonce(monkeypatch, tmp_path):
    """Un vestige au-dela du plafond est COMPTE (capes), jamais avale en silence."""
    import forge_archaeology_enrich as E

    arch = tmp_path / "a.json"
    mods = [{"depot": "r", "chemin": f"m{i}.py", "sha_suppr": "x", "etat": "DELETED"}
            for i in range(5)]
    arch.write_text('{"modules": ' + __import__("json").dumps(mods) + '}', encoding="utf-8")
    monkeypatch.setattr(E, "ARCH", str(arch))
    monkeypatch.setattr(E, "_contenu_avant_suppr", lambda repo, sha, ch: "def f():\n    pass\n")
    res = E.enrichir({"r": "/r"}, maxn=2)
    assert res["enrichis"] == 2 and res["capes"] == 3


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
