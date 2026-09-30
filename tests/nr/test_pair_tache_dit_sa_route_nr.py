# -*- coding: utf-8 -*-
"""NR — la description de `soumettre_tache` dit la route REELLE de chaque genre.

Mesure 2026-09-29 : claude.ai a soumis une tache en 'deliberer' destinee a « Claude Code
local », sur la foi de la description (« tache pour un agent local »). Or
`forge_pair_quarantaine.approuver` envoie 'deliberer' au debat RecursiveMAS et renvoie la
capsule AU PAIR : le destinataire est ignore. Un contrat qui ment a un pair le fait mentir
a l'owner. Ce NR lit les deux bouts : la route dans le code, et ce que la description en dit.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _description_soumettre_tache() -> str:
    arbre = ast.parse((ROOT / "tools" / "forge_pair_mcp.py").read_text(encoding="utf-8"))
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call) and any(k.arg == "name" and getattr(k.value, "value", None) == "soumettre_tache"
                                           for k in n.keywords):
            for k in n.keywords:
                if k.arg == "description":
                    return ast.literal_eval(k.value)
    raise AssertionError("decorateur soumettre_tache ou sa description introuvable : ILLISIBLE, ni vrai ni faux")


def test_la_route_deliberer_du_code_est_celle_qu_on_croit():
    src = (ROOT / "tools" / "forge_pair_quarantaine.py").read_text(encoding="utf-8")
    assert 'genre == "deliberer"' in src and 'vers = "RECURSIVEMAS"' in src, (
        "la route 'deliberer' a change dans forge_pair_quarantaine : revoir la description")


def test_la_description_dit_que_deliberer_revient_au_pair():
    d = _description_soumettre_tache()
    assert "RecursiveMAS" in d and "RENVOYEE AU PAIR" in d and "IGNORE" in d, d
    assert "executer" in d and "destinataire" in d, d
