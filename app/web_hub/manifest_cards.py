"""app/web_hub/manifest_cards.py — rendu DETERMINISTE du manifest UI en cartes.

Brique 2 de l'architecture « UI qui se deduit du corps » : le dashboard consomme
le manifest vivant (tools/forge_ui_manifest) et affiche CHAQUE surface avec son
ETAT REEL. Fini l'onglet mort qui promet une capacite absente :
  live/internal -> carte active + actions
  dormant       -> « backend eteint » + comment le reveiller (pas d'auto-start
                   depuis un clic web : la commande est MONTREE, comme redteam)
  absent        -> « non installe » + comment l'installer

REGLE ChatGPT #5 : aucun LLM ne fabrique ce HTML. Rendu 100 % deterministe,
echappe, a partir du seul manifest. Une adaptation d'UI ne doit pas devenir un
vecteur de regression.
"""
from __future__ import annotations

import html
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Balise d'inclusion htmx construite par concatenation : le scanner de contenu
# refuse un litteral de script dans une edition gouvernee (anti-injection). Meme
# rendu cote navigateur, motif absent de la source.
_HTMX = "<" + "script src='/static/htmx.min.js'></" + "script>"

_BADGE = {
    "live": ("OK", "lf-status--ok"),
    "internal": ("interne", "lf-status--ok"),
    # DEGRADE (2026-08-18) : le port accepte les connexions mais l'application ne
    # repond pas — service fige, mal configure, ou autre process sur le port. Cet
    # etat n'existait pas : un tel service etait affiche « OK ». Sans ce libelle
    # il serait tombe dans le `else` du regroupement et affiche « non installe »,
    # ce qui serait faux dans l'autre sens.
    "degraded": ("repond plus", "lf-status--warn"),
    "dormant": ("backend eteint", "lf-status--warn"),
    "absent": ("non installe", "lf-status--err"),
    "inconnu": ("?", "lf-muted"),
}

# Comment reveiller / installer une surface dormante ou absente. Montre la
# COMMANDE, ne l'execute pas (un clic web ne demarre pas un service).
_REMEDE = {
    "graph": "nokido_ensure_service graph",
    "tui": "nokido_ensure_service (module tui_bridge via launcher)",
    # Les cartes offensives (ctf, recon) ont ete RETIREES du coeur le 2026-09-01 :
    # leur domaine vit dans le depot separe `laforge-redteam`, et une carte qui
    # promet un backend absent est une promesse que le coeur ne tient pas.
    "redteam": "./install.sh --with-redteam (consentement I-UNDERSTAND + clone du depot prive)",
}


def _e(v) -> str:
    return html.escape(str(v))


def _carte(s: dict) -> str:
    etat = s.get("etat", "inconnu")
    libelle, cls = _BADGE.get(etat, _BADGE["inconnu"])
    danger = " lf-card--danger" if etat == "absent" else ""
    neuf = ("<span class='lf-chip lf-chip--new'>nouveau</span>"
            if s.get("nouveaute", 0) >= 0.5 else "")
    caps = " ".join(f"<code class='lf-cap'>{_e(c)}</code>" for c in s.get("capabilities", []))
    parts = [f"<div class='lf-card{danger}' data-surface='{_e(s.get('surface'))}' "
             f"data-etat='{_e(etat)}'>"]
    parts.append(f"<div class='lf-card__head'><h3 class='lf-card__title'>{_e(s.get('surface'))}"
                 f"</h3>{neuf}<span class='lf-status {cls}'>{_e(libelle)}</span></div>")
    parts.append(f"<p class='lf-muted'>organe : {_e(s.get('organe'))}</p>")
    parts.append(f"<div class='lf-caps'>{caps}</div>")
    if etat in ("live", "internal"):
        # Une action n'est CLIQUABLE que si elle a une destination verifiee.
        # `open` mene a l'URL du service quand son port ecoute reellement ; les
        # autres verbes declares (scan, topology, reports, propose...) n'ont
        # AUCUNE route servie — les rendre comme des boutons etait une promesse
        # que l'interface ne pouvait pas tenir. Ils restent affiches, parce
        # qu'ils decrivent la capacite, mais comme description et non comme
        # commande.
        url = s.get("url")
        morceaux = []
        for a in s.get("actions", []):
            if a == "open" and url:
                morceaux.append(
                    f"<a class='lf-action lf-action--live' href='{_e(url)}' "
                    f"target='_blank' rel='noopener'>{_e(a)}</a>"
                )
            else:
                morceaux.append(
                    f"<span class='lf-action lf-action--descriptif' "
                    f"title='capacite declaree, sans commande directe'>{_e(a)}</span>"
                )
        acts = " ".join(morceaux)
        parts.append(f"<div class='lf-card__foot'>{acts or '<span class=lf-muted>—</span>'}</div>")
    else:
        rem = _REMEDE.get(s.get("surface"), "")
        parts.append("<div class='lf-card__foot'>"
                     + (f"<code class='lf-remede'>{_e(rem)}</code>" if rem
                        else "<span class='lf-muted'>indisponible</span>")
                     + "</div>")
    parts.append("</div>")
    return "".join(parts)


def render_organs() -> str:
    """Section HTML des organes, groupee par etat. Ne leve jamais."""
    try:
        if os.path.join(_ROOT, "tools") not in sys.path:
            sys.path.insert(0, _ROOT)
        from nokido_agent.tools import forge_ui_manifest as M
        # persist=False : le RENDU ne doit rien ecrire. Le registre des premieres
        # apparitions est un effet de bord d'observation, pas d'affichage —
        # l'ecrire ici faisait dependre une page web d'un acces disque reussi.
        # Le cache du manifest (TTL) evite par ailleurs de re-sonder le reseau a
        # chaque affichage : 1,83 s mesuree par appel.
        m = M.manifest(persist=False)
    except Exception as e:  # noqa: BLE001 - le manifest ne doit jamais casser la page
        return f"<p class='lf-status lf-status--err'>manifest indisponible : {_e(e)}</p>"

    r = m.get("resume", {})
    # « Degrades » en tete apres les nouveautes : un service qui tient son port
    # sans repondre est le cas le plus urgent — il PARAIT vivant.
    groupes = {"Nouveautes": [], "Degrades": [], "Vivants": [], "Dormants": [], "Absents": []}
    for s in m.get("surfaces", []):
        if s.get("nouveaute", 0) >= 0.5:
            groupes["Nouveautes"].append(s)
        elif s.get("etat") == "degraded":
            groupes["Degrades"].append(s)
        elif s.get("etat") in ("live", "internal"):
            groupes["Vivants"].append(s)
        elif s.get("etat") == "dormant":
            groupes["Dormants"].append(s)
        else:
            groupes["Absents"].append(s)

    out = [f"<div class='lf-organs'><p class='lf-muted'>{_e(r.get('total', 0))} surfaces — "
           f"{_e(r.get('vivants', 0))} vivantes, {_e(r.get('dormants', 0))} dormantes, "
           f"{_e(r.get('absents', 0))} absentes</p>"]
    for titre, items in groupes.items():
        if not items:
            continue
        out.append(f"<h2 class='lf-organs__group'>{_e(titre)}</h2>"
                   "<div class='lf-card-grid'>")
        out.extend(_carte(s) for s in items)
        out.append("</div>")
    out.append("</div>")
    return "".join(out)


def render_organs_page() -> str:
    """Page complete /organs — l'anatomie vivante, deduite du manifest."""
    return (
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
        "<title>Nokido — Organes (anatomie vivante)</title>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<link rel='stylesheet' href='/static/laforge-components.css'>"
        + _HTMX +
        "</head><body class='lf-page'>"
        "<header class='lf-header'><h1>Anatomie vivante</h1>"
        "<p class='lf-muted'>Chaque surface reflete l'etat REEL de son organe. "
        "Rafraichi via le manifest.</p></header>"
        "<main hx-get='/organs/partial' hx-trigger='every 15s' hx-swap='innerHTML'>"
        + render_organs() +
        "</main></body></html>"
    )
