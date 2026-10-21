"""NR -- les vues /roadmap/arbre et /swarm/graphe sont LISIBLES et zoomables (retour owner 19/10).

Owner 19/10 : « les pages s'affichent bien mais le zoom ne marche pas bien et n'est pas bien fonctionnel, on ne peut
pas lire ». Cause lue dans app/web_hub/graph_viz.html : les ecouteurs des boutons + / - / ajuster n'etaient poses qu'a
la fin du chemin AST -- la vue injectee faisait `return` avant -> boutons morts ; disposition hierarchique gauche-droite :
les 140 items formaient UNE colonne, « ajuster » rendait les etiquettes minuscules (police 11). Contrat fige ici sur la
page (pas de navigateur dans la CI) : zoom branche pour toutes les vues, molette/clavier/navigation actifs, disposition
en forces figee apres stabilisation, items en boites lisibles, clic = zoom sur le noeud, recherche qui centre l'item.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = (ROOT / "app" / "web_hub" / "graph_viz.html").read_text(encoding="utf-8")


def _vue_injectee() -> str:
    debut = PAGE.index("const vueRoadmap")
    return PAGE[debut:PAGE.index("// 1) summary stats", debut)]


def test_les_boutons_de_zoom_sont_branches_avant_toute_vue():
    i_branche = PAGE.index("brancherZoom()")
    assert i_branche < PAGE.index("const vueRoadmap"), "le zoom doit etre branche avant le choix de la vue"
    assert "function brancherZoom" in PAGE


def test_la_vue_injectee_zoome_a_la_souris_au_clavier_et_par_boutons():
    v = _vue_injectee()
    for cle in ("zoomView: true", "dragView: true", "keyboard: true"):
        assert cle in v, cle
    # Owner 19/10 : « les boutons de zoom se chevauchent, deux couches » -- les fleches natives de vis
    # (navigationButtons) occupaient le meme coin que nos boutons + / - / ajuster : une seule couche.
    assert "navigationButtons: true" not in v and "zoom-controls" in PAGE


def test_disposition_en_forces_figee_apres_stabilisation():
    v = _vue_injectee()
    # Hierarchie seulement quand le graphe porte une chaine de dependances (arbre roadmap) ; jamais la colonne
    # unique gauche-droite de 140 items.
    assert 'direction: "LR"' not in v
    assert "stabilizationIterationsDone" in v and re.search(r"setOptions\(\{\s*physics:\s*false", v)


def test_items_lisibles_clic_zoom_et_recherche():
    v = _vue_injectee()
    assert re.search(r"size:\s*1[4-9]", v), "police des items >= 14"
    assert "widthConstraint" in v
    assert 'network.on("click"' in v and "network.focus(" in v
    assert 'id="recherche"' in PAGE and "chercherNoeud" in v
