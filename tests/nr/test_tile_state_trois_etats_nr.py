"""NR — une tuile morte DIT pourquoi : jamais construite, eteinte, ou opt-in.

MESURE DU 2026-09-20 sur `app/web_hub/dashboard_html.py` (code ACTUEL, verifie --
la fiche du 2026-08-06 avait 45 jours, son diagnostic tient toujours) :

    probe_service(cfg)  -> {"state": "live" | "offline" | "error", ...}   3 etats
    _service_down(cfg)  -> state in ("offline", "error")                  -> bool
    L144 is_coming_soon = bool(cfg.get("coming_soon")) or _service_down(cfg)

La sonde DISTINGUE deja trois etats, et DEUX couches successives les aplatissent
en un booleen. Resultat a l'ecran : une seule etiquette, « BIENTOT », pour des
situations qui n'ont rien a voir :

    jamais construit    vrai « bientot »
    deploye mais ETEINT graph 7474, netcfg 7500, llama 8090/8091, ollama, deno 7401
                        -> affiche « non deploye » alors qu'il suffirait de demarrer
    opt-in non installe recon : `coming_soon = not _RT_INSTALLED`, alors que la page
                        d'opt-in `/redteam` EXISTE (redteam_views.py)

C'est exactement `DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE != NOT_BUILT`, la
distinction que la constitution du depot impose -- appliquee partout SAUF a
l'interface. Et c'est la reponse a la question de l'owner (« pourquoi
l'auto-amelioration n'ameliore pas l'UI ? ») : elle ne peut pas reparer ce
qu'elle ne distingue pas.

DEUX RENDERERS DIVERGENT, mesure : `render_cards` ecrit « BIENTÔT » (L156) et
`render_modules` « BIENTOT » sans accent (L209). Deux chemins, deux libelles,
aucune source commune -- le motif « politique a N chemins » a l'etage du rendu.

PORTEE DITE : ce NR garde la QUALIFICATION de l'etat et son UNICITE entre les
deux renderers. Il ne teste ni le CSS, ni le HTML produit, ni la disponibilite
reelle d'un service (ce serait une sonde sur la MACHINE, pas sur le code).
"""
from __future__ import annotations

import pytest


def _module():
    for nom in ("nokido_agent.app.web_hub.dashboard_html", "app.web_hub.dashboard_html",
                "web_hub.dashboard_html", "dashboard_html"):
        try:
            mod = __import__(nom, fromlist=["render_cards"])
        except Exception:  # noqa: BLE001
            continue
        if hasattr(mod, "render_cards"):
            return mod
    pytest.skip("dashboard_html introuvable sous ses noms d'import")


def _sonde(monkeypatch, mod, etat):
    monkeypatch.setattr(mod, "probe_service",
                        lambda cfg: {"state": etat, "checked": True, "via": "tcp"},
                        raising=False)


def test_le_qualificateur_existe():
    """Garde l'instrument d'abord."""
    mod = _module()
    assert hasattr(mod, "tile_state"), (
        "aucun `tile_state()` : `probe_service` distingue live/offline/error et "
        "deux couches l'aplatissent en un booleen -- une tuile ETEINTE et une "
        "tuile JAMAIS CONSTRUITE s'affichent pareil")


def test_un_service_JOIGNABLE_est_vivant(monkeypatch):
    mod = _module()
    _sonde(monkeypatch, mod, "live")
    assert mod.tile_state({"title": "T", "port": 1234})["state"] == "live"


def test_un_service_DECLARE_mais_INJOIGNABLE_est_ETEINT_pas_bientot(monkeypatch):
    """LE COEUR. graph 7474, netcfg 7500, deno 7401 sont DEPLOYES et arretes.

    Les afficher « BIENTOT » dit a l'owner qu'il n'y a rien a lancer, alors que
    tout est la et qu'un demarrage suffit.
    """
    mod = _module()
    _sonde(monkeypatch, mod, "offline")
    e = mod.tile_state({"title": "Graph", "port": 7474})
    assert e["state"] == "eteint", f"un service deploye+arrete est classe {e['state']!r}"
    assert e.get("action"), "aucune action proposee pour un service qu'il suffit de lancer"


def test_une_sonde_EN_ERREUR_n_est_pas_un_service_ETEINT(monkeypatch):
    """`probe_service` distingue deja `offline` de `error` : ne pas les refondre.

    Un refus TCP et une pile reseau en erreur n'appellent pas la meme reponse.
    """
    mod = _module()
    _sonde(monkeypatch, mod, "error")
    assert mod.tile_state({"title": "X", "port": 9})["state"] == "erreur"


def test_un_OPT_IN_non_installe_pointe_vers_sa_page(monkeypatch):
    """recon est un FAUX MORT : `/redteam` (consentement + installeur) existe."""
    mod = _module()
    _sonde(monkeypatch, mod, "live")
    e = mod.tile_state({"title": "Recon", "coming_soon": True, "opt_in": "/redteam"})
    assert e["state"] == "opt_in"
    assert e.get("href") == "/redteam", (
        "une tuile opt-in n'offre pas le chemin d'activation qui EXISTE deja")


def test_un_vrai_JAMAIS_CONSTRUIT_reste_bientot(monkeypatch):
    """Le symetrique : on qualifie, on ne supprime pas l'etat « bientot »."""
    mod = _module()
    _sonde(monkeypatch, mod, "live")
    assert mod.tile_state({"title": "Futur", "coming_soon": True})["state"] == "bientot"


def test_une_ROUTE_INTERNE_reste_CLIQUABLE(monkeypatch):
    """⚠️ CE TEST EXISTE PARCE QUE J'AI ENCODE UNE REGRESSION DANS SA PREMIERE
    VERSION, et que seule la MESURE RUNTIME l'a rattrapee.

    Mesure sur les 18 tuiles reelles : 12 sont NON SONDABLES en TCP --
    `/vitals`, `/rbac`, `/launcher`, `/docs`, `/anatomy`, `/reports`... Ce sont
    des routes INTERNES, servies in-process par le webhub : elles n'ont pas de
    port et n'en auront jamais.

    Ma premiere version les classait `incertain` donc NON CLIQUABLES. Cela aurait
    rendu 12 tuiles sur 18 inertes -- bien PIRE que le defaut d'origine. Le cout
    des deux erreurs n'est jamais symetrique : rater une tuile morte laisse un
    bouton sans effet ; griser une tuile vivante supprime une capacite.

    `probe_service` rend `unknown` pour DEUX raisons distinctes qu'il ne separe
    pas : pas de port (route interne, legitime) et cible illisible. Le rendu doit
    les distinguer.
    """
    mod = _module()
    _sonde(monkeypatch, mod, "unknown")
    for cible in ("/vitals", "/launcher", "internal"):
        e = mod.tile_state({"title": "T", "target": cible})
        assert e.get("cliquable") is True, (
            f"la route interne {cible!r} a ete grisee ({e['state']!r}) -- "
            "12 tuiles sur 18 deviendraient inertes")
        assert e["state"] == "interne"


def test_une_cible_VRAIMENT_ILLISIBLE_reste_INCERTAINE(monkeypatch):
    """Le symetrique. Une cible qui n'est ni interne ni sondable n'est PAS saine.

    Le module porte deja la lecon du 2026-09-17 au niveau de la SONDE (« une
    absence de mesure n'est pas une preuve de sante ») ; elle n'avait jamais
    atteint le RENDU : `_service_down` ne teste que `("offline","error")`, donc
    `unknown` n'etait pas down et la tuile restait cliquable vers un `/{slug}/`
    fabrique -- 404 si le slug n'est pas monte.

    On ne ment pas dans l'autre sens non plus : `unknown` n'est pas `eteint`.
    """
    mod = _module()
    _sonde(monkeypatch, mod, "unknown")
    e = mod.tile_state({"title": "Bancal", "target": "http://exemple.invalide:99999"})
    assert e["state"] == "incertain"
    assert e["state"] != "live", "l'ILLISIBLE range du cote SAIN"
    assert e["state"] != "eteint", "une absence de mesure fabriquee en panne"


def test_un_service_LENT_est_DEGRADE_et_reste_cliquable(monkeypatch):
    """`degraded` = il repond, mais lentement. Le griser priverait d'un service
    qui marche ; le dire `live` cacherait une derive."""
    mod = _module()
    _sonde(monkeypatch, mod, "degraded")
    e = mod.tile_state({"title": "Lent", "target": "http://127.0.0.1:7400/"})
    assert e["state"] == "degrade"
    assert e.get("cliquable") is True, "un service lent mais vivant a ete grise"


def test_seul_un_service_MESURE_VIVANT_est_dit_live(monkeypatch):
    """Liste BLANCHE : n'est sain que ce qui est PROUVE sain."""
    mod = _module()
    for etat in ("offline", "error", "unknown", "degraded"):
        _sonde(monkeypatch, mod, etat)
        assert mod.tile_state({"title": "X", "target": "http://127.0.0.1:1/"})["state"] != "live", (
            f"l'etat de sonde {etat!r} est rendu comme `live`")


def test_les_18_tuiles_REELLES_ne_sont_pas_majoritairement_grisees(monkeypatch):
    """GARDE D'IMPACT, ne de la regression ci-dessus.

    Mesure du 2026-09-20 : 12 tuiles sur 18 sont non sondables (routes internes),
    4 live, 2 offline. Un qualificateur qui grise la majorite du dashboard a
    casse l'interface, quelle que soit la justesse de sa taxonomie.
    """
    mod = _module()
    _sonde(monkeypatch, mod, "unknown")
    internes = [{"title": s, "target": s} for s in
                ("/vitals", "/rbac", "/launcher", "/docs", "/anatomy", "/reports")]
    grisees = [c["target"] for c in internes if not mod.tile_state(c).get("cliquable")]
    assert not grisees, f"routes internes grisees a tort : {grisees}"


def test_les_DEUX_renderers_utilisent_le_MEME_qualificateur():
    """Mesure : `render_cards` ecrit « BIENTÔT », `render_modules` « BIENTOT ».

    Deux libelles pour un meme etat, c'est deux verites -- et la preuve qu'aucune
    source commune ne pilote le rendu.
    """
    import inspect
    mod = _module()
    for nom in ("render_cards", "render_modules"):
        src = inspect.getsource(getattr(mod, nom))
        assert "tile_state" in src, (
            f"{nom} ne passe pas par tile_state : les deux renderers peuvent "
            "diverger a nouveau des le prochain correctif")


def test_le_qualificateur_ne_CASSE_JAMAIS_le_rendu(monkeypatch):
    """Un dashboard qui leve n'affiche RIEN -- pire que des tuiles grises."""
    mod = _module()
    monkeypatch.setattr(mod, "probe_service",
                        lambda cfg: (_ for _ in ()).throw(RuntimeError("NR")),
                        raising=False)
    e = mod.tile_state({"title": "T", "port": 1})
    assert isinstance(e, dict) and e.get("state")
