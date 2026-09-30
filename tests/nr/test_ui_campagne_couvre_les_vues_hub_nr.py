"""NR -- la campagne ui-acceptance juge les vues de l'APPLICATION hub, pas seulement les pages du portail.

Mesure du 2026-09-24 : le dernier rapport (22/09, verdict CONFORME / PROVEN) couvre 20 routes du
portail. Aucune n'est `/design/ui_kits/hub/index.html` -- la page ou ATTERRIT le login, celle que
l'owner voit en premier. Ses six vues (Accueil, Intention longue, Federation, Maison, Memoire
persona, Souverainete) se choisissent par etat React (`setView`), sans URL : aucune route ne les
atteint. Or c'est la que vivaient les pannes des 17-18/09 (Federation : `null.length` au premier
rendu empechait la vue de se MONTER ; six vues hors de portee sur `window`). Elles n'etaient
gardees que par des NR STATIQUES sur le bundle ; a l'execution, personne ne les ouvrait.

Ce qui est garde :
  1. chaque entree du menu (`NAV` de hub-shell.ref.jsx) a sa route de campagne -- une vue
     ajoutee au menu sans etre ajoutee a la campagne fait rougir ce test ;
  2. une route de vue se reconnait et rend le LIBELLE du bouton a cliquer ; une route du
     portail n'en a pas ;
  3. l'ouverture d'une vue CLIQUE ce bouton sur la page (et le dit si le bouton manque :
     une vue qu'on n'a pas pu ouvrir n'a pas ete jugee) ;
  4. les pages UI servies par le HUB :8766 (owner : « l'UI est sur 7400 ET 8766 ») sont
     dans la campagne, et leur URL vise bien :8766 -- jamais le portail.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_ui_campaign as m  # noqa: E402

SHELL = RACINE / "design_handoff_nokido" / "ui_kits" / "hub" / "hub-shell.ref.jsx"


def _menu_du_hub() -> dict:
    src = SHELL.read_text(encoding="utf-8")
    bloc = src[src.index("const NAV = ["):]
    bloc = bloc[:bloc.index("];")]
    return dict(re.findall(r'id:\s*"([\w-]+)",\s*label:\s*"([^"]+)"', bloc))


def test_chaque_vue_du_menu_a_sa_route_de_campagne():
    menu = _menu_du_hub()
    assert len(menu) >= 6, "menu illisible : %r" % menu
    couvertes = {m.vue_hub(path) for path, _ in m.ROUTES} - {None}
    manquantes = {vid: lab for vid, lab in menu.items() if lab not in couvertes}
    assert not manquantes, "vues du hub jamais ouvertes par la campagne : %r" % manquantes


def test_pages_du_hub_8766_couvertes_et_resolues_vers_8766():
    routes = {p for p, _ in m.ROUTES}
    for page, _ in m.PAGES_8766:
        assert m.PREFIXE_8766 + page in routes, "page :8766 absente de la campagne : %s" % page
    assert {"/", "/forge/network", "/forge/rings", "/forge/watch"} <= {p for p, _ in m.PAGES_8766}
    assert m.url_de(m.PREFIXE_8766 + "/forge/rings") == m.HUB_BASE + "/forge/rings"
    assert m.url_de("/rag") == m.BASE + "/rag"
    assert m.HUB_BASE != m.BASE, "le hub :8766 et le portail :7400 ne doivent pas se confondre"
    assert ":" not in (m.PREFIXE_8766 + "/forge/rings").strip("/").replace("/", "_"), \
        "le nom de capture derive de la route ne doit pas porter « : » (invalide sous Windows)"


def test_route_de_vue_rend_le_libelle_et_route_portail_rien():
    menu = _menu_du_hub()
    routes_vues = [p for p, _ in m.ROUTES if m.vue_hub(p)]
    assert routes_vues and all(p.startswith(m.PAGE_HUB) for p in routes_vues)
    assert m.vue_hub("/dashboard") is None and m.vue_hub("/rag") is None
    assert set(m.vue_hub(p) for p in routes_vues) == set(menu.values())


class _Bouton:
    def __init__(self, journal, nom, present):
        self.journal, self.nom, self.present = journal, nom, present
        self.first = self

    async def count(self):
        return 1 if self.present else 0

    async def click(self, timeout=None):
        self.journal.append(self.nom)


class _Page:
    def __init__(self, presents):
        self.presents, self.cliques = presents, []

    def get_by_role(self, role, name=None, exact=None):
        assert role == "button"
        return _Bouton(self.cliques, name, name in self.presents)


def test_ouvrir_une_vue_clique_son_bouton_et_dit_l_echec():
    page = _Page({"Fédération"})
    ok = asyncio.run(m.ouvrir_vue_hub(page, m.PAGE_HUB + "#federation"))
    assert ok is True and page.cliques == ["Fédération"]
    page = _Page(set())
    ok = asyncio.run(m.ouvrir_vue_hub(page, m.PAGE_HUB + "#federation"))
    assert ok is False and page.cliques == [], "un bouton absent doit etre DIT, pas clique au hasard"
    assert asyncio.run(m.ouvrir_vue_hub(_Page(set()), "/rag")) is None, "route du portail : rien a ouvrir"
