"""Non-regression : le lien d'une tuile du dashboard suit sa DECLARATION.

Defaut mesure le 2026-08-26 par le recensement du cablage (mode navigateur, session
owner) : sur les 28 elements du dashboard, deux pointaient dans le vide —
`/ui_playground/` et `/feed/`, tous deux 404. Les declarations etaient pourtant justes
(`SERVICES["ui_playground"]["target"] == "/ui/playground"`,
`SERVICES["feed"]["target"] == "/forge/feed"`) : c'est le RENDU qui construisait le lien
depuis la CLE du dictionnaire. La forme `/{slug}/` marchait par accident partout ou la
cle egale la route — FastAPI redirige `/launcher/` vers `/launcher` — et cassait des que
les deux differaient. Une convention qui tient par la grace d'une redirection n'est pas
un cablage.
"""

from __future__ import annotations

import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[2]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from app.web_hub.dashboard_html import href_de, slugs_montes  # noqa: E402


def test_une_surface_montee_en_proxy_garde_son_chemin_gouverne():
    """CORRECTION de la premiere version de ce test, qui accusait `recon` : le portail
    MONTE un reverse-proxy authentifie sous `/recon` et `/graph` (app.py). Y substituer
    l'URL absolue du backend contournerait l'auth du portail. Ce qui est monte prime."""
    cfg = {"target": "http://127.0.0.1:7410"}
    assert href_de("recon", cfg, montees={"recon", "graph"}) == "/recon/"
    assert href_de("graph", {"target": "http://127.0.0.1:7474", "external": True},
                   montees={"recon", "graph"}) == "/graph/"


def test_les_montages_sont_lus_sur_lapplication_vivante():
    """Le lien ne doit pas dependre d'une seconde liste tenue a la main."""
    class _R:
        def __init__(self, path, app=None):
            self.path, self.app = path, app

    class _App:
        routes = [_R("/recon", object()), _R("/graph", object()),
                  _R("/dashboard"), _R("/api/vital/{name}", object())]

    assert slugs_montes(_App()) == {"recon", "graph"}


def test_une_surface_interne_suit_sa_route_declaree_pas_sa_cle():
    """Les deux cas exacts qui rendaient 404 le 2026-08-26."""
    assert href_de("ui_playground", {"target": "/ui/playground"}) == "/ui/playground"
    assert href_de("feed", {"target": "/forge/feed"}) == "/forge/feed"


def test_une_surface_dont_la_cle_egale_la_route_reste_juste():
    """Temoin : le correctif ne doit pas deplacer ce qui marchait — ici il retire en
    prime la redirection de slash que le lien imposait au navigateur."""
    assert href_de("launcher", {"target": "/launcher"}) == "/launcher"
    assert href_de("status", {"target": "/status"}) == "/status"


def test_une_surface_externe_garde_son_url_absolue():
    cfg = {"target": "http://127.0.0.1:7401", "external": True}
    assert href_de("deno", cfg) == "http://127.0.0.1:7401"


def test_un_organe_sans_route_propre_garde_la_forme_par_cle():
    """`internal` = pas de route a lire : c'est le seul cas ou la convention s'applique."""
    assert href_de("physiologie", {"target": "internal"}) == "/physiologie/"
    assert href_de("inconnue", {}) == "/inconnue/"


def test_le_registre_reel_du_portail_ne_porte_aucun_lien_invente():
    """Garde sur le REGISTRE, pas seulement sur la fonction : toute surface non externe
    est SOIT montee en proxy, SOIT porteuse d'une route absolue, SOIT `internal`. Sans
    ce garde, une entree ajoutee demain re-fabriquerait un `/{slug}/` qui n'existe pas —
    exactement les deux 404 mesures le 2026-08-26."""
    from app.web_hub.app import SERVICES, app

    montees = slugs_montes(app)
    fautives = [
        (slug, cfg.get("target"))
        for slug, cfg in SERVICES.items()
        # `coming_soon` ne rend AUCUN lien (carte desactivee) : le portail monte
        # `/recon` seulement si l'outil est installe et marque la tuile autrement.
        # Un garde qui l'accuserait crierait sur une surface qui ne promet rien —
        # premiere version de ce test, corrigee par la mesure (app.py:446-448).
        if not cfg.get("external")
        and not cfg.get("coming_soon")
        and slug not in montees
        and not str(cfg.get("target", "")).startswith("/")
        and cfg.get("target") != "internal"
    ]
    assert not fautives, "surfaces sans route declaree ni montage : %s" % fautives


def test_le_schema_openapi_se_genere_donc_docs_et_redoc_vivent():
    """Mesure 2026-08-26 (signalee par l'owner : « /docs ne repond pas »). Deux routes
    de mcp_lab declaraient `response_class=None` ; FastAPI leve alors « A response class
    is needed to generate OpenAPI » et /openapi.json rend 500 — donc /docs ET /redoc
    s'affichent VIDES, alors que les routes elles-memes repondaient 200. Le defaut etait
    invisible page par page : il ne se voit qu'en generant le schema."""
    from app.web_hub.app import app

    schema = app.openapi()          # leve si une route est mal declaree
    assert schema.get("paths"), "schema vide : /docs n'aurait rien a afficher"
    assert len(schema["paths"]) > 50, "schema anormalement pauvre : %d paths" % len(schema["paths"])


def test_aucune_route_du_portail_ne_declare_une_response_class_nulle():
    """Le garde en amont : `response_class=None` casse le schema ENTIER pour une seule
    route. On nomme la fautive plutot que de laisser un AssertionError opaque."""
    from fastapi.routing import APIRoute

    from app.web_hub.app import app

    fautives = [
        (r.path, sorted(r.methods), getattr(r.endpoint, "__name__", "?"))
        for r in app.routes
        if isinstance(r, APIRoute) and r.include_in_schema
        and getattr(getattr(r, "response_class", None), "value", getattr(r, "response_class", None)) is None
    ]
    assert not fautives, "routes sans response_class (elles tuent /openapi.json) : %s" % fautives


def test_aucune_tuile_du_portail_ne_pointe_vers_une_route_inexistante():
    """Le test d'effet : chaque lien interne rendu par le dashboard correspond a une
    route (ou un montage) REELLEMENT declaree par l'application. C'est ce controle qui
    manquait — `/ui_playground/` et `/feed/` vivaient dans le HTML sans exister nulle
    part ailleurs."""
    from app.web_hub.app import SERVICES, app

    montees = slugs_montes(app)
    connues = {getattr(r, "path", "") for r in app.routes} | {"/%s/" % s for s in montees}
    manquants = []
    for slug, cfg in SERVICES.items():
        if cfg.get("coming_soon"):
            continue
        lien = href_de(slug, cfg, montees)
        if not lien.startswith("/"):
            continue  # externe : hors du perimetre de l'application
        if lien.rstrip("/") not in {c.rstrip("/") for c in connues}:
            manquants.append((slug, lien))
    assert not manquants, "tuiles vers une route inexistante : %s" % manquants
