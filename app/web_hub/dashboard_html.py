"""app/web_hub/dashboard_html.py - Render du dashboard HTML."""

from __future__ import annotations

import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


_TEMPLATE_PATH = Path(__file__).parent / "dashboard.html"


def probe_service(cfg: dict, timeout: float = 0.25,
                  http_timeout: float = 0.8, slow_ms: float = 500.0) -> dict:
    """Etat MESURE d'une tuile (doctrine GUI live-only, owner 2026-08-21).

    Avec `healthcheck` declare (chemin HTTP, opt-in par tuile) : sonde HTTP -
    live (2xx/3xx sous slow_ms) / degraded (2xx/3xx lent) / error (4xx/5xx ou
    sonde plantee, raison portee) / offline (injoignable dans le budget - au
    dela, un service est operationnellement indiscernable d'un mort).
    Sans healthcheck : TCP seul, live/offline (degraded jamais fabrique
    depuis un delai TCP). Pas de port 127.0.0.1 -> checked=False, etat UNKNOWN
    et JAMAIS live (route in-process ou cible externe) : une absence de mesure
    n'est pas une preuve de sante. `via` dit COMMENT c'est mesure."""
    m = re.search(r"127\.0\.0\.1:(\d{2,5})", cfg.get("target", "") or "")
    if not m:
        # 2026-09-17 -- rendait "live". Une cible non sondable (route interne,
        # cible externe, port absent ou malforme) n'est PAS une preuve de
        # disponibilite : c'est une ABSENCE DE MESURE. Rendre "live" rangeait
        # l'ILLISIBLE du cote SAIN, ce que la constitution semantique interdit
        # (« on classe par liste BLANCHE »). Mesure du jour sur SERVICES :
        # 12 tuiles sur 18 annoncaient ainsi une sante que personne n'avait
        # verifiee. Garde : `test_probe_service_trois_etats_nr`.
        # NE PAS re-introduire un repli vers "live" quand l'affichage se
        # degradera : cette degradation EST la falsification precedente qui
        # disparait, pas un defaut a masquer. La connaissance manquante
        # s'ajoute ensuite par le raccord au superviseur (PROCESS_ALIVE).
        return {"state": "unknown", "checked": False, "probe_ms": None, "via": None}
    port = int(m.group(1))
    hc = cfg.get("healthcheck")
    if hc:
        t0 = time.monotonic()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}{hc}", method="GET")
            with urllib.request.urlopen(req, timeout=http_timeout) as r:
                r.read(64)
                code = getattr(r, "status", 200)
            ms = round((time.monotonic() - t0) * 1000, 1)
            return {"state": "degraded" if ms > slow_ms else "live",
                    "checked": True, "probe_ms": ms, "via": "http"} if code < 400 else \
                   {"state": "error", "checked": True, "probe_ms": ms,
                    "via": "http", "reason": f"HTTP {code}"}
        except urllib.error.HTTPError as e:
            ms = round((time.monotonic() - t0) * 1000, 1)
            return {"state": "error", "checked": True, "probe_ms": ms,
                    "via": "http", "reason": f"HTTP {e.code}"}
        except OSError:
            return {"state": "offline", "checked": True, "probe_ms": None, "via": "http"}
        except Exception as e:  # noqa: BLE001
            return {"state": "error", "checked": True, "probe_ms": None,
                    "via": "http", "reason": type(e).__name__}
    t0 = time.monotonic()
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout)
        s.close()
        return {"state": "live", "checked": True, "via": "tcp",
                "probe_ms": round((time.monotonic() - t0) * 1000, 1)}
    except OSError:
        # refus / timeout / pile reseau : le service n'est pas joignable
        return {"state": "offline", "checked": True, "probe_ms": None, "via": "tcp"}
    except Exception as e:  # noqa: BLE001
        return {"state": "error", "checked": True, "probe_ms": None,
                "via": "tcp", "reason": type(e).__name__}


def _service_down(cfg: dict) -> bool:
    """Gating dynamique : une tuile dont le service local est injoignable = grisée
    (coming_soon) -> jamais de lien mort cliquable. Delegue a probe_service.

    CONSERVE pour ses autres appelants. Le rendu, lui, passe par `tile_state` :
    ce booleen ecrase cinq etats en deux, et c'est precisement le defaut corrige.
    """
    return probe_service(cfg)["state"] in ("offline", "error")


def tile_state(cfg: dict) -> dict:
    """QUALIFIE une tuile. SIX etats, jamais un booleen.

    MESURE 2026-09-20. `probe_service` rend DEJA cinq etats -- `live`,
    `degraded`, `error`, `offline`, `unknown` -- puis `_service_down` les aplatit
    en booleen, puis `bool(cfg.get("coming_soon")) or _service_down(cfg)` les
    aplatit une SECONDE fois. A l'ecran il ne restait qu'une etiquette,
    « BIENTOT », pour des situations qui n'appellent pas la meme reponse :

        jamais construit     il n'y a rien a lancer
        deploye mais ETEINT  graph 7474, netcfg 7500, deno 7401 : tout est la,
                             il suffit de demarrer -- l'afficher « bientot » dit
                             a l'owner le CONTRAIRE de ce qu'il doit faire
        opt-in non installe  recon : `/redteam` (consentement + installeur) EXISTE
        sonde en ERREUR      une pile reseau qui leve n'est pas un refus TCP
        NON MESURE           `unknown` : ni sain ni malade -- et c'est le plus
                             couteux, voir ci-dessous

    ⚠️ LE CAS `unknown` EST CELUI QUI FAIT LES « BOUTONS QUI NE RENDENT RIEN ».
    `_service_down` ne teste que `("offline", "error")` : une tuile jamais
    mesuree n'est donc PAS down, elle s'affiche normale et CLIQUABLE, et
    `href_de` lui fabrique `/{slug}/`. Si le slug n'est pas monte -> 404. Le
    module porte deja la lecon du 2026-09-17 (« une absence de mesure n'est pas
    une preuve de sante », 12 tuiles sur 18 concernees) au niveau de la SONDE ;
    elle n'avait jamais atteint le RENDU.

    Liste BLANCHE : n'est `live` que ce qui est PROUVE live. Tout le reste porte
    son etat propre -- on ne range ni l'ILLISIBLE ni le LENT du cote sain, et on
    ne les confond pas non plus avec un service arrete (`UNKNOWN != NO`).

    Rend {state, label, titre, cliquable, href, action, probe}. `label` est la
    SOURCE UNIQUE du texte affiche : `render_cards` ecrivait « BIENTÔT » et
    `render_modules` « BIENTOT » -- deux libelles pour un meme etat, donc deux
    verites, et la preuve qu'aucune source commune ne pilotait le rendu.

    NE LEVE JAMAIS : un dashboard qui leve n'affiche RIEN, ce qui est pire que
    des tuiles grises. Garde : tests/nr/test_tile_state_trois_etats_nr.py
    """
    try:
        opt_in = cfg.get("opt_in")
        if cfg.get("coming_soon") and opt_in:
            # FAUX MORT : la capacite n'est pas absente, elle est non ACTIVEE.
            return {"state": "opt_in", "label": "ACTIVER", "titre": "Activation disponible",
                    "cliquable": True, "href": opt_in,
                    "action": "opt-in disponible", "probe": None}
        if cfg.get("coming_soon"):
            return {"state": "bientot", "label": "BIENTÔT", "titre": "Pas encore construit",
                    "cliquable": False, "href": None, "action": None, "probe": None}

        # ROUTE INTERNE AVANT TOUTE SONDE. `probe_service` rend `unknown` pour
        # DEUX raisons qu'il ne separe pas : pas de port 127.0.0.1 (route servie
        # in-process, parfaitement legitime) et cible illisible. Les confondre au
        # rendu grise 12 tuiles sur 18 -- `/vitals`, `/rbac`, `/launcher`,
        # `/docs`, `/anatomy`... -- c'est-a-dire l'essentiel du dashboard.
        #
        # ⚠️ Ma premiere version faisait exactement cela, et seule la MESURE
        # RUNTIME sur les 18 tuiles reelles l'a rattrapee : le NR encodait la
        # regression. Le cout des deux erreurs n'est jamais symetrique -- rater
        # une tuile morte laisse un bouton sans effet, griser une tuile vivante
        # SUPPRIME une capacite.
        cible = (cfg.get("target") or "").strip()
        if cible.startswith("/") or cible == "internal":
            return {"state": "interne", "label": "", "titre": "Route servie par le portail",
                    "cliquable": True, "href": None, "action": None, "probe": None}

        sonde = probe_service(cfg)
        etat = (sonde or {}).get("state")

        if etat == "live":
            return {"state": "live", "label": "", "titre": "",
                    "cliquable": True, "href": None, "action": None, "probe": sonde}
        if etat == "degraded":
            # Il REPOND, lentement. Le griser priverait d'un service qui marche ;
            # le dire `live` cacherait une derive.
            return {"state": "degrade", "label": "LENT",
                    "titre": "Répond lentement (%s ms)" % (sonde or {}).get("probe_ms", "?"),
                    "cliquable": True, "href": None,
                    "action": "surveiller la latence", "probe": sonde}
        if etat == "offline":
            return {"state": "eteint", "label": "ÉTEINT",
                    "titre": "Déployé mais arrêté — démarrer via /launcher",
                    "cliquable": False, "href": "/launcher",
                    "action": "démarrer via /launcher", "probe": sonde}
        if etat == "error":
            return {"state": "erreur", "label": "SONDE KO",
                    "titre": "Sonde en erreur (%s)" % (sonde or {}).get("reason", "?"),
                    "cliquable": False, "href": None,
                    "action": "sonde en erreur", "probe": sonde}
        # `unknown` et tout etat inattendu : INCERTAIN. Jamais `live` (ce serait
        # ranger l'illisible du cote sain), jamais `eteint` (ce serait fabriquer
        # une panne a partir d'une absence de mesure).
        return {"state": "incertain", "label": "NON MESURÉ",
                "titre": "Cible non sondable — disponibilité inconnue",
                "cliquable": False, "href": None,
                "action": "aucune mesure possible sur cette cible", "probe": sonde}
    except Exception:  # noqa: BLE001 - un dashboard qui leve n'affiche RIEN
        return {"state": "erreur", "label": "SONDE KO", "titre": "Qualification impossible",
                "cliquable": False, "href": None,
                "action": "qualification impossible", "probe": None}


def href_de(slug: str, cfg: dict, montees=()) -> str:
    """Lien d'une tuile, dans cet ordre : ce qui est MONTE, puis ce qui est DECLARE.

    MESURE 2026-08-26 (recensement du cablage, mode navigateur) : le dashboard servait
    `/ui_playground/` et `/feed/` -> 404. Les deux declarations etaient pourtant JUSTES
    (`/ui/playground`, `/forge/feed`) : c'est le RENDU qui fabriquait le lien depuis la
    CLE. La forme marchait par accident partout ou la cle egale la route -- FastAPI
    redirige `/launcher/` vers `/launcher` -- et cassait des que les deux differaient.

    Mais `/{slug}/` n'est pas toujours une invention : `app.mount("/recon", ...)` et
    `app.mount("/graph", ...)` montent un reverse-proxy AUTHENTIFIE sous la cle. Y
    substituer l'URL absolue du backend contournerait le garde d'auth du portail et
    ouvrirait une origine differente. `montees` porte donc les slugs REELLEMENT montes,
    lus sur l'application (`app.routes`), jamais re-declares a cote : un registre ne
    devient une autorite qu'apres avoir ete confronte au reel.

    Ordre : monte -> `/{slug}/` · externe -> URL absolue · route declaree -> cette route
    · `internal` ou rien a lire -> `/{slug}/`.
    """
    if slug in (montees or ()):
        return f"/{slug}/"
    if cfg.get("external"):
        return cfg.get("target", "")
    cible = cfg.get("target", "") or ""
    return cible if cible.startswith("/") else f"/{slug}/"


def slugs_montes(application) -> set:
    """Slugs servis par un montage de l'application (Starlette `Mount.path`).

    Lu sur l'objet vivant : si un montage disparait, le lien suit sans qu'une seconde
    liste ait a etre tenue a jour."""
    out = set()
    for route in getattr(application, "routes", []) or []:
        chemin = getattr(route, "path", "") or ""
        if chemin.startswith("/") and getattr(route, "app", None) is not None and chemin.count("/") == 1:
            out.add(chemin[1:])
    return out


def _montees_vivantes():
    """Montages de l'application SI elle est deja chargee — lecture de `sys.modules`,
    jamais un import : ce module est importe PAR `app.web_hub.app`, l'importer en retour
    fabriquerait un cycle. Application absente (test du module seul) -> ensemble vide,
    et le lien retombe sur la declaration. Trois etats, comme partout ailleurs : monte /
    declare / rien a lire."""
    module = sys.modules.get("app.web_hub.app")
    application = getattr(module, "app", None) if module is not None else None
    return slugs_montes(application) if application is not None else set()


def render_cards(services: dict, montees=None) -> str:
    """HTML des cartes (grille modules) — reutilise par dashboard.html ET le shell Hub Nokido PC."""
    montees = _montees_vivantes() if montees is None else montees
    cards = []
    for slug, cfg in services.items():
        feature_key = f"feature_{slug}"
        is_external = bool(cfg.get("external"))
        etat = tile_state(cfg)
        is_coming_soon = not etat["cliquable"]
        target_str = cfg.get("target", "")
        color_class = f"lf-icon-{cfg.get('color', 'purple')}"

        if is_coming_soon:
            card = f'''
        <div data-feature-key="{feature_key}" class="lf-card lf-card-disabled" title="{etat["titre"]}">
            <div class="lf-card-head">
                <div>
                    <div class="lf-icon {color_class}" style="opacity:.4">
                        <i data-lucide="{cfg["icon"]}" style="width:22px;height:22px"></i>
                    </div>
                    <h3 style="opacity:.5">{cfg["title"]}<span class="lf-ext-badge" style="background:var(--bg-3);color:var(--text-dim)">{etat["label"]}</span></h3>
                    <p style="opacity:.4">{cfg["desc"]}</p>
                </div>
                <div class="lf-status-dot"></div>
            </div>
            <div class="lf-card-target" style="opacity:.3">{etat["action"] or f"/{slug}/"}</div>
        </div>
        '''
        else:
            href = href_de(slug, cfg, montees)
            target_attr = ' target="_blank" rel="noopener"' if is_external and not href.startswith("/") else ""
            ext_badge = '<span class="lf-ext-badge">EXT</span>' if is_external else ""
            # Le libelle montre la route REELLEMENT servie : afficher « /slug/ -> cible »
            # annoncait un alias qui n'existait pas.
            bottom_label = target_str if is_external else href
            card = f'''
        <a href="{href}"{target_attr} data-feature-key="{feature_key}" class="lf-card">
            <div class="lf-card-head">
                <div>
                    <div class="lf-icon {color_class}">
                        <i data-lucide="{cfg["icon"]}" style="width:22px;height:22px"></i>
                    </div>
                    <h3>{cfg["title"]}{ext_badge}</h3>
                    <p>{cfg["desc"]}</p>
                </div>
                <div class="lf-status-dot" data-service="{slug}"></div>
            </div>
            <div class="lf-card-target">{bottom_label}</div>
        </a>
        '''
        cards.append(card)

    return "\n".join(cards)


_MODULE_ACCENT = {"purple": "--purple", "blue": "--blue", "cyan": "--cyan", "green": "--green",
                  "emerald": "--green", "yellow": "--yellow", "orange": "--orange",
                  "red": "--red", "pink": "--pink"}


def render_modules(services: dict, montees=None) -> str:
    """Tuiles `.lf-module` (DS canonique : accent par domaine, --dim si service down).
    Utilise les primitives de laforge-components.css. Pour le shell Hub Nokido PC."""
    montees = _montees_vivantes() if montees is None else montees
    out = []
    for slug, cfg in services.items():
        accent = _MODULE_ACCENT.get(cfg.get("color", "purple"), "--purple")
        etat = tile_state(cfg)
        down = not etat["cliquable"]
        is_ext = bool(cfg.get("external"))
        # Badge calcule AVANT le corps : un f-string imbrique avec guillemets
        # echappes est illisible, et c'est la ou les deux renderers avaient
        # diverge (« BIENTÔT » ici, « BIENTOT » la).
        badge = f'<span class="lf-module__soon">{etat["label"]}</span>' if etat["label"] else ""
        body = (
            '<span class="lf-module__accent"></span>'
            f'<div class="lf-module__head"><span class="lf-module__icon">'
            f'<i data-lucide="{cfg["icon"]}"></i></span>'
            f'{badge}</div>'
            f'<div class="lf-module__title">{cfg["title"]}</div>'
            f'<div class="lf-module__desc">{cfg["desc"]}</div>'
        )
        if down:
            out.append(f'<div class="lf-module lf-module--dim" style="--lf-accent:var({accent})">{body}</div>')
        else:
            href = href_de(slug, cfg, montees)
            tattr = ' target="_blank" rel="noopener"' if is_ext and not href.startswith("/") else ""
            out.append(
                f'<a href="{href}"{tattr} class="lf-module" '
                f'style="--lf-accent:var({accent});display:block;text-decoration:none">{body}</a>'
            )
    return "\n".join(out)


def render_dashboard(services: dict, version: str, montees=None) -> str:
    """Genere le HTML du dashboard en interpolant les services."""
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("__CARDS__", render_cards(services, montees)).replace("__VERSION__", version)


__all__ = ["render_dashboard", "render_cards", "render_modules", "href_de", "slugs_montes"]
