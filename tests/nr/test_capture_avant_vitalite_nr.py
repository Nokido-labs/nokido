"""NR 2026-09-09 — la CI capture son sha AVANT d'ecrire son registre de vitalite.

L'AUTO-SABOTAGE, mesure de bout en bout ce jour-la. `main()` appelait
`_ecrire_vitalite()` puis, cinquante lignes plus bas, `_inscrire_generation()` qui
refuse de capturer si un fichier SUIVI est modifie. Or `tests/nr/vitalite_gardes.json`
EST un fichier suivi : la CI salissait donc l'arbre qu'elle s'appretait a juger, et
se retirait a elle-meme le droit de capturer.

POURQUOI CE DEFAUT EST RESTE INVISIBLE SI LONGTEMPS. Dans l'arbre principal,
`tests/nr/` n'est pas inscriptible par les comptes sandbox : l'ecriture echouait, la
mesure partait dans `sandbox/vitalite_en_attente/` (non suivi), et l'arbre restait
propre par ACCIDENT. C'est une ACL qui masquait le bug, pas une conception. T0 l'a
rendu systematique : le worktree de reference vit sous `sandbox/`, donc `tests/nr/`
y EST inscriptible -- l'ecriture reussit, et la capture echoue a tous les coups.
Mesure : `M tests/nr/vitalite_gardes.json` dans le worktree a e20ab0182, 16 gates
verts, 8599 tests sans echec, et « 1 fichier(s) SUIVI(s) modifie(s) — pas de capture ».

L'ORDRE JUSTE DECOULE DU SENS. La generation date le CODE teste ; le registre de
vitalite date le RUN. On capture donc l'etat du code d'abord, on journalise
l'execution ensuite. Un instrument ne doit pas modifier ce qu'il mesure avant de
l'avoir mesure.

Zero service externe : lecture AST du depot, aucun run, aucun git.
"""

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SOURCE = RACINE / "tools" / "ci_local.py"

ECRITURE = "_ecrire_vitalite"
CAPTURE = "_inscrire_generation"
PORTEUSE = "_summary"   # et non `main` : mesure du 2026-09-09, les deux appels y vivent


def _appels_dans_la_porteuse() -> list:
    """Les noms de fonctions appelees dans `_summary()`, DANS L'ORDRE du source."""
    arbre = ast.parse(SOURCE.read_text(encoding="utf-8", errors="replace"))
    porteuse = next((n for n in ast.walk(arbre)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == PORTEUSE), None)
    assert porteuse is not None, "%s() introuvable dans %s" % (PORTEUSE, SOURCE)
    ordre = []
    for noeud in ast.walk(porteuse):
        if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name):
            ordre.append((noeud.lineno, noeud.func.id))
    return [nom for _ligne, nom in sorted(ordre)]


def test_les_deux_appels_existent_bien_dans_la_porteuse():
    """Contre-epreuve — et elle a SERVI le 2026-09-09.

    Ecrite en visant `main()`, elle a echoue en disant « ces appels n'y sont pas » :
    ils vivent dans `_summary()`. Sans elle, le test d'ordre aurait leve une
    ValueError obscure, ou pire, un jour, serait passe sur une liste vide.
    """
    appels = _appels_dans_la_porteuse()
    assert ECRITURE in appels, "%s n'est plus appele dans %s()" % (ECRITURE, PORTEUSE)
    assert CAPTURE in appels, "%s n'est plus appele dans %s()" % (CAPTURE, PORTEUSE)


def test_la_capture_precede_l_ecriture_du_registre():
    """L'invariant : ne pas salir l'arbre qu'on s'apprete a juger."""
    appels = _appels_dans_la_porteuse()
    i_capture = appels.index(CAPTURE)
    i_ecriture = appels.index(ECRITURE)
    assert i_capture < i_ecriture, (
        "%s (position %d) est appele APRES %s (position %d) : la CI ecrit "
        "tests/nr/vitalite_gardes.json -- un fichier SUIVI -- puis constate que "
        "l'arbre est sale et refuse de capturer son propre sha. Dans l'arbre "
        "principal une ACL masquait le defaut ; dans le worktree de reference il "
        "est systematique." % (CAPTURE, i_capture, ECRITURE, i_ecriture))
