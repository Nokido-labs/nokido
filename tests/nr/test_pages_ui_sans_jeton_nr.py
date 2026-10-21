"""NR -- les pages /forge/debate, /forge/graph, /forge/recon ne servent AUCUN jeton.

Releve par la relecture claude.ai (19/10), confirme sur piece : un GET anonyme de
/forge/debate rendait 200 et 64 octets de plus que le gabarit -- le jeton CLAUDE (ou
le maitre) injecte dans `<meta name="laforge-bearer">`, sans authentification. Tout
processus local (comptes bac a sable compris) heritait ainsi du ring de CLAUDE.

Decision owner 19/10 : ne plus injecter. Le gabarit garde son placeholder, la route
le remplace par une chaine VIDE, et la page demande le jeton a l'ouverture
(sessionStorage, propre a l'onglet).
"""
from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
HUB = RACINE / "tools" / "nokido_hub.py"
PAGES = ("llm_debate.html", "graph_viz.html", "recon_demo.html")
PLACEHOLDER = "__LAFORGE_BEARER__"


def _remplacements_du_placeholder() -> list[tuple[int, ast.expr]]:
    arbre = ast.parse(HUB.read_text(encoding="utf-8"))
    vus = []
    for noeud in ast.walk(arbre):
        if (isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Attribute)
                and noeud.func.attr == "replace" and len(noeud.args) == 2
                and isinstance(noeud.args[0], ast.Constant)
                and noeud.args[0].value == PLACEHOLDER):
            vus.append((noeud.lineno, noeud.args[1]))
    return vus


def test_le_hub_remplace_bien_le_placeholder_quelque_part():
    # temoin positif : sans lui, un renommage du placeholder rendrait le test vert a vide
    assert _remplacements_du_placeholder(), "placeholder introuvable dans le hub : test aveugle"


def test_aucune_route_n_injecte_un_jeton_dans_le_html():
    fautifs = [ligne for ligne, valeur in _remplacements_du_placeholder()
               if not (isinstance(valeur, ast.Constant) and valeur.value == "")]
    assert not fautifs, f"jeton injecte dans une page servie sans auth (lignes {fautifs})"


def test_les_pages_demandent_le_jeton_a_l_ouverture():
    for nom in PAGES:
        texte = (RACINE / "app" / "web_hub" / nom).read_text(encoding="utf-8")
        assert PLACEHOLDER in texte, f"{nom} : gabarit sans placeholder"
        assert "sessionStorage" in texte, f"{nom} : aucune saisie du jeton -- page inutilisable"
