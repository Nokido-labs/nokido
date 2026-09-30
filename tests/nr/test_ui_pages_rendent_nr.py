# -*- coding: utf-8 -*-
"""Non-regression — les pages du portail RENDENT, elles ne se contentent pas de repondre.

Reproche de l'owner, 2026-08-26, et il est juste : « si tu faisais de vrais tests NR sur
l'UI tu verrais que ça marche pas ». Les tests NR d'interface existants lisent du CODE
(AST, presence de chaines). Aucun ne CHARGE une page. Une page qui repond 200 en rendant
zero caractere leur est donc parfaitement invisible — c'est exactement ce qui est arrive
a 16 pages de /design pendant des semaines.

Ce fichier teste ce qu'un navigateur ferait des ressources declarees :
  1. la page repond ;
  2. **chacune de ses ressources locales repond aussi** — une balise de script dont la
     source est en 404 rend la page blanche SANS changer son code HTTP, et c'est LE
     defaut qui a ete paye ;
  3. aucune ressource ne vient d'un hote EXTERNE — hors-ligne, un CDN injoignable produit
     la meme page blanche, en repondant 200 ;
  4. la page porte du contenu, pas un squelette vide.

Il ne remplace PAS le contrat Playwright (`tools/forge_ui_campaign.py`), qui execute le
JS et clique. Il le complete la ou celui-ci ne tourne pas : sans navigateur, en CI, en
quelques secondes. Un gate qui ne s'execute presque jamais ne protege presque rien.

Hermetique : TestClient, auth desactivee comme dans `test_hub_web.py` (meme patron).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

# BUDGET DE TEMPS EXPLICITE (2026-09-02). Le gate lance la suite avec
# `--timeout=30`, applique PAR TEST. Ces cas-la traversent toute l'app FastAPI
# en HTTP pour chaque page et chacune de ses ressources : mesure isolee, le plus
# lourd prend 7,37 s (10 cas, 27,9 s au total). Confortable en apparence.
#
# En FIN de suite complete, le meme cas depasse 30 s -- environ quatre fois plus
# lent, l'app etant montee dans un interpreteur ou des milliers de modules sont
# deja charges. Mesure : DEUX runs consecutifs tues au meme endroit, et le
# processus meurt AVANT que pytest ecrive son JUnit. Consequence hors de
# proportion : la suite entiere devient SANS VERDICT -- 7 266 tests perdus
# parce qu'un seuil etait trop serre pour un seul fichier.
#
# Le test n'est ni casse ni bloque : il est LENT, et le seuil ne le disait pas.
# 180 s laisse ~24x la mesure isolee : assez pour absorber une fin de suite
# chargee, assez peu pour qu'un VRAI blocage (attente infinie sur une socket)
# soit toujours attrape au lieu de faire pendre la CI.
pytestmark = pytest.mark.timeout(180)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Hotes tiers : toute ressource servie depuis l'exterieur casse l'interface hors-ligne
# ET sous la CSP du portail. Mesure du 2026-08-26 : unpkg.com sur 16 pages.
_HOTES_TIERS = re.compile(r"https?://(?!127\.0\.0\.1|localhost)", re.I)
# Pages produites par un LLM : leur rendu depend d'un backend, elles ont leurs propres
# tests. Les charger ici rendrait ce gate lent ET dependant d'un service externe.
# `^/api/` : ce sont des endpoints JSON, ils ne declarent AUCUNE ressource a verifier —
# mais plusieurs sondent tout le corps (vitals, opsec, hub/*) et coutaient a eux seuls
# l'essentiel des 112 s mesurees. Un gate lent finit par etre retire ; celui-ci doit
# tourner a chaque commit. Les endpoints API ont leurs propres tests.
_HORS_CHAMP = re.compile(r"^/ui/auto/|^/api/|/sse$|/stream$")


@pytest.fixture(scope="module")
def client():
    """UN client pour tout le module, tenu par son gestionnaire de contexte.

    Deux pieges payes ici, dans cet ordre. D'abord `scope="module"` SANS `with` : le
    second test heritait d'une boucle d'evenements deja fermee (`RuntimeError: Event
    loop is closed`) — un echec du banc, pas de l'interface, qui se lit pourtant comme
    un defaut d'UI. Puis un client PAR test, qui reglait le probleme mais remontait le
    module dix fois : 150 s pour un gate cense tourner a chaque commit, donc un gate
    qu'on finit par retirer. Le `with` en scope module garde la boucle ouverte et ne
    monte l'application qu'une fois."""
    os.environ["LAFORGE_AUTH_ENABLED"] = "0"
    os.environ.setdefault("LAFORGE_ADMIN_TOKEN", "nr-baseline-dummy")
    for mod in list(sys.modules):
        if mod.startswith("app.web_hub"):
            del sys.modules[mod]
    fastapi_tc = pytest.importorskip("fastapi.testclient")
    from app.web_hub.app import app
    with fastapi_tc.TestClient(app) as c:
        yield c


def _pages_html(client) -> list:
    """Routes GET sans parametre qui rendent du HTML."""
    spec = client.get("/openapi.json")
    if spec.status_code != 200:
        pytest.skip("openapi indisponible (%s)" % spec.status_code)
    out = []
    for chemin, ops in (spec.json().get("paths") or {}).items():
        if "get" not in ops or "{" in chemin or _HORS_CHAMP.search(chemin):
            continue
        out.append(chemin)
    return out


def _ressources_locales(html: str) -> list:
    """Sources LOCALES declarees par la page (feuilles, scripts, images, polices)."""
    trouves = re.findall(r'(?:src|href)="([^"#?]+)"', html)
    return [u for u in trouves
            if u.startswith("/") and not u.startswith("//")
            and re.search(r"\.(js|css|svg|png|jpg|jpeg|webp|ico|woff2?)$", u, re.I)]


# ------------------------------- contre-epreuves de la distinction (erreur payee)

def test_un_lien_de_navigation_externe_nest_pas_une_ressource():
    """`/llm-dashboard` pointe vers les consoles providers : c'est sa raison d'etre.
    Les compter comme ressources faisait crier le garde sur une page parfaitement saine."""
    html = '<a href="https://aistudio.google.com/">Google AI Studio</a>'
    assert _ressources_chargees(html) == []


def test_une_source_externe_est_bien_vue():
    html = '<' + 'script src="https://cdn.exemple.test/x.js"></' + 'script>'
    assert _ressources_chargees(html) == ["https://cdn.exemple.test/x.js"]


def test_une_feuille_de_style_externe_est_vue():
    html = '<link rel="stylesheet" href="https://cdn.exemple.test/a.css">'
    assert _ressources_chargees(html) == ["https://cdn.exemple.test/a.css"]


def test_une_image_externe_est_vue():
    assert _ressources_chargees('<img src="https://x.test/i.png">') == ["https://x.test/i.png"]


# ------------------------------------------------------------ le gate sait mordre

def test_le_portail_se_monte(client):
    r = client.get("/health")
    assert r.status_code == 200, "le portail ne se monte pas : ce gate ne garderait rien"


def test_des_pages_sont_trouvees(client):
    pages = _pages_html(client)
    assert len(pages) >= 10, (
        "%d page(s) seulement — filtre trop strict, la couverture serait illusoire"
        % len(pages))


# ------------------------------------------------------ ce qu'un navigateur verrait

def _ressources_chargees(html: str) -> list:
    """URL que le navigateur va chercher TOUT SEUL au chargement.

    DISTINCTION ESSENTIELLE, apprise en criant a faux : un `<a href>` est un lien que
    l'utilisateur peut suivre, pas une ressource. `/llm-dashboard` pointe vers
    aistudio.google.com et artificialanalysis.ai — c'est sa RAISON D'ETRE (portail
    d'inscription aux providers), et aucun de ces liens n'a jamais rendu une page
    blanche. Ne comptent ici que les balises dont le navigateur charge la source sans
    qu'on clique : script, link, img, iframe, source."""
    trouves = []
    for balise in re.findall(r"<(?:script|link|img|iframe|source)\b[^>]*>", html, re.I):
        for u in re.findall(r'(?:src|href)="([^"]+)"', balise):
            trouves.append(u)
    return trouves


def test_aucune_ressource_chargee_ne_vient_dun_hote_externe(client):
    """LE defaut paye : hors-ligne, un CDN injoignable rend la page BLANCHE en 200.

    Ne juge QUE les ressources chargees automatiquement — les liens de navigation vers
    l'exterieur sont legitimes et n'ont rien a voir avec le rendu."""
    fautives = {}
    for chemin in _pages_html(client):
        r = client.get(chemin)
        if r.status_code != 200 or "html" not in (r.headers.get("content-type") or ""):
            continue
        externes = sorted({u for u in _ressources_chargees(r.text) if _HOTES_TIERS.match(u)})
        if externes:
            fautives[chemin] = externes[:3]
    assert not fautives, (
        "ressources CHARGEES depuis un hote TIERS (page blanche hors-ligne) : %s" % fautives)


def test_toutes_les_ressources_locales_repondent(client):
    """Une source en 404 ne change pas le code HTTP de la page : elle repond 200 et ne
    rend RIEN. Sans ce test, le defaut est invisible."""
    manquantes = {}
    vues = 0
    for chemin in _pages_html(client):
        r = client.get(chemin)
        if r.status_code != 200 or "html" not in (r.headers.get("content-type") or ""):
            continue
        for res in set(_ressources_locales(r.text)):
            vues += 1
            if client.get(res).status_code != 200:
                manquantes.setdefault(chemin, []).append(res)
    assert vues > 0, "aucune ressource inspectee — le gate ne prouve rien"
    assert not manquantes, "ressources introuvables (page cassee) : %s" % manquantes


def test_les_pages_html_portent_du_contenu(client):
    """Une page qui repond 200 avec un squelette vide est cassee, pas saine."""
    vides = {}
    for chemin in _pages_html(client):
        r = client.get(chemin)
        if r.status_code != 200 or "html" not in (r.headers.get("content-type") or ""):
            continue
        sans_balises = re.sub(r"<[^>]+>", " ", r.text)
        sans_balises = re.sub(r"\s+", " ", sans_balises).strip()
        if len(r.text) < 200 and len(sans_balises) < 40:
            vides[chemin] = len(r.text)
    assert not vides, "pages HTML quasi vides : %s" % vides


def test_aucune_page_ne_rend_une_erreur_serveur(client):
    """500 = defaut du portail lui-meme. 401/403/503 sont des reponses LEGITIMES
    (auth, service on-demand eteint) et ne sont pas comptees ici."""
    casses = {}
    for chemin in _pages_html(client):
        code = client.get(chemin).status_code
        if code >= 500 and code != 503:
            casses[chemin] = code
    assert not casses, "erreur serveur sur : %s" % casses
