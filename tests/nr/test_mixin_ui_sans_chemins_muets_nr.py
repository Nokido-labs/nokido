# -*- coding: utf-8 -*-
"""NR : forge_mixin_ui ne doit contenir aucun chemin d'erreur muet (lot L5, AGY, 2026-10-13).

Chaque bloc try/except qui avale une exception sans logger doit etre motive
par une mention '# muet-ok' explicite documentant pourquoi l'erreur est ignoree
(conforme a la doctrine de forge_git_gate._recidive_warn).
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_aucun_chemin_muet_dans_forge_mixin_ui():
    cible = ROOT / "app" / "forge_mixin_ui.py"
    assert cible.exists()
    src = cible.read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src, filename=str(cible))
    lignes = src.splitlines()

    muets = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.ExceptHandler):
            continue
        corps = noeud.body
        if len(corps) == 1 and isinstance(corps[0], (ast.Pass, ast.Continue)):
            a_lire = {noeud.lineno, corps[0].lineno}
            if any("muet-ok" in lignes[n - 1] for n in a_lire if 0 < n <= len(lignes)):
                continue
            muets.append(f"L{noeud.lineno}: {lignes[noeud.lineno - 1].strip()} -> {lignes[corps[0].lineno - 1].strip()}")

    assert not muets, (
        f"{len(muets)} chemin(s) d'erreur muet(s) detecte(s) dans forge_mixin_ui.py :\n"
        + "\n".join(muets)
    )
