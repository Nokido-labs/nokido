# -*- coding: utf-8 -*-
"""Non-regression — /docs et /redoc ne dependent d'AUCUN hote tiers.

Symptome signale par l'owner le 2026-08-26 : « /docs ne repond pas ». La page repondait
**200** : FastAPI sert par defaut un squelette qui va chercher swagger-ui sur
cdn.jsdelivr.net. Hors-ligne, ou sous la CSP du portail qui ne declare pas cet hote, le
script ne charge jamais et la page reste BLANCHE. Meme famille que les 16 pages de
/design deliees le meme jour (`test_ui_delier_cdn_nr`) : **un endpoint qui repond 200
n'est pas un endpoint qui marche**, et c'est precisement ce que « pas de mode demo »
veut dire.

Deux gardes, parce qu'un seul ne suffit pas :
  1. les URL declarees pointent sous /static (regression = quelqu'un remet le defaut) ;
  2. les fichiers vises EXISTENT — sinon on remplace une page blanche par un 404, ce qui
     se relit comme repare.

Hermetique : le module est lu par AST, jamais importe (importer l'app monte les routes,
ouvre la base JTI et demarre des greffons — hors de propos pour ce contrat).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app" / "web_hub" / "app.py"
STATIC = ROOT / "app" / "web_hub" / "static"

_HOTES_TIERS = ("jsdelivr", "unpkg.com", "cdnjs", "fonts.googleapis", "fonts.gstatic")


@pytest.fixture(scope="module")
def arbre():
    if not APP.exists():
        pytest.skip("app/web_hub/app.py absent de cette copie")
    return ast.parse(APP.read_text(encoding="utf-8", errors="replace"), filename=str(APP))


def _constantes(arbre) -> dict:
    """Assignations de constantes au niveau module : {nom: valeur} pour les chaines."""
    out = {}
    for noeud in arbre.body:
        if isinstance(noeud, ast.Assign) and isinstance(noeud.value, ast.Constant) \
                and isinstance(noeud.value.value, str):
            for cible in noeud.targets:
                if isinstance(cible, ast.Name):
                    out[cible.id] = noeud.value.value
    return out


def _appel_fastapi(arbre):
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name) \
                and noeud.func.id == "FastAPI":
            return noeud
    return None


# ------------------------------------------- les pages par defaut sont desarmees

def test_les_pages_par_defaut_sont_desarmees(arbre):
    """LE test. docs_url/redoc_url laisses par defaut = dependance CDN silencieuse."""
    appel = _appel_fastapi(arbre)
    assert appel is not None, "aucun appel FastAPI(...) trouve"
    kw = {k.arg: k.value for k in appel.keywords}
    for nom in ("docs_url", "redoc_url"):
        assert nom in kw, (
            f"{nom} absent : FastAPI servira sa page par defaut, qui charge "
            "swagger-ui/ReDoc depuis un CDN — page blanche hors-ligne")
        assert isinstance(kw[nom], ast.Constant) and kw[nom].value is None, (
            f"{nom} doit valoir None (routes souveraines redeclarees apres /static)")


def test_les_routes_souveraines_sont_declarees(arbre):
    """Desarmer sans redeclarer donnerait deux 404 — pire que le defaut."""
    chemins = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Attribute) \
                and noeud.func.attr == "get" and noeud.args \
                and isinstance(noeud.args[0], ast.Constant):
            chemins.add(noeud.args[0].value)
    assert "/docs" in chemins and "/redoc" in chemins


# ------------------------------------------------ les URL pointent sous /static

@pytest.mark.parametrize("nom", ["_SWAGGER_JS", "_SWAGGER_CSS", "_REDOC_JS", "_FAVICON"])
def test_url_locale_et_non_distante(arbre, nom):
    cst = _constantes(arbre)
    assert nom in cst, f"{nom} introuvable au niveau module"
    valeur = cst[nom]
    assert valeur.startswith("/static/"), f"{nom} = {valeur!r} — doit etre servi localement"
    assert not any(h in valeur for h in _HOTES_TIERS)


# Plancher de taille par nature d'asset. Un seuil unique se trompe dans les deux sens :
# 993 octets est NORMAL pour un favicon SVG (faux positif paye a l'ecriture de ce test)
# et RUINEUX pour un bundle swagger de 1,5 Mo. Un garde qui crie a faux se fait desarmer.
_PLANCHER = {"_SWAGGER_JS": 200_000, "_REDOC_JS": 200_000,
             "_SWAGGER_CSS": 50_000, "_FAVICON": 100}


@pytest.mark.parametrize("nom", ["_SWAGGER_JS", "_SWAGGER_CSS", "_REDOC_JS", "_FAVICON"])
def test_le_fichier_vise_existe(arbre, nom):
    """Une URL locale qui pointe dans le vide echange la page blanche contre un 404."""
    if not STATIC.exists():
        pytest.skip("static absent de cette copie")
    cible = STATIC / _constantes(arbre)[nom].removeprefix("/static/")
    assert cible.exists(), (
        f"{cible.name} reference mais absent de /static — vendoriser avec "
        "tools/forge_vendor_asset.py")
    taille, plancher = cible.stat().st_size, _PLANCHER[nom]
    assert taille >= plancher, (
        f"{cible.name} : {taille} octets < {plancher} attendus — telechargement "
        "tronque ou page d'erreur enregistree a la place de l'asset")


def test_redoc_ne_va_pas_chercher_les_polices_google(arbre):
    """`with_google_fonts` vaut True par defaut : la page irait quand meme dehors."""
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name) \
                and noeud.func.id == "get_redoc_html":
            kw = {k.arg: k.value for k in noeud.keywords}
            assert "with_google_fonts" in kw, "with_google_fonts non declare (defaut True)"
            assert kw["with_google_fonts"].value is False
            return
    pytest.fail("appel get_redoc_html introuvable")
