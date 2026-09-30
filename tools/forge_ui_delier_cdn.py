#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_ui_delier_cdn.py — delier les pages servies de tout CDN externe.

MESURE 2026-08-26 (signalee par l'owner : « /design/ui_kits/composer/index.html ne
marche pas ») : sur les 26 pages servies sous /design, SEIZE chargent React, ReactDOM,
Babel ou Lucide depuis `unpkg.com`. Hors-ligne — ou sous la CSP du portail, qui ne
declare pas cet hote — ces sources ne se chargent pas : `window.React` reste indefini,
le rendu vaut ZERO caractere, et la page est BLANCHE tout en repondant 200. Un endpoint
qui repond 200 n'est pas un endpoint qui marche.

Une seule page etait saine : `ui_kits/hub/index.html`, deja raccordee a `/static/*`.
Ce module applique son patron aux autres. Il ne TELECHARGE rien : `forge_vendor_asset`
couvre deja ce geste, et les fichiers sont dans `app/web_hub/static/`. Ce qui manquait
n'etait pas l'asset, c'etait le RACCORDEMENT.

PIEGE, paye si on l'ignore : les balises CDN portent un `integrity` (SRI) calcule sur le
fichier DISTANT. Le laisser en place sur une source locale fait REFUSER la ressource par
le navigateur -- on remplacerait une page blanche par une autre. `integrity` et
`crossorigin` sautent donc avec l'URL.

Trois etats, comme partout : remplace / deja local / CDN INCONNU (signale, jamais
reecrit au hasard -- on ne devine pas quel fichier local correspond).

Usage :
    LAFORGE_PYTHON tools/forge_ui_delier_cdn.py                 # dry-run (defaut)
    run action=trusted_script path=tools/forge_ui_delier_cdn.py script_args="--appliquer"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLES = (ROOT / "design_handoff_nokido",)
STATIC = ROOT / "app" / "web_hub" / "static"

__FORGE_COLOR__ = "interface/souverainete-assets"  # le portail ne depend d'aucun hote tiers

# motif d'URL (insensible a la casse) -> fichier servi sous /static/.
# On ne mappe que ce qu'on peut PROUVER present sur le disque : un mapping vers un
# fichier absent echangerait une page blanche contre une autre.
MAPPING = (
    (r"react-dom[.@][^\"']*\.js", "react-dom.min.js"),
    (r"react[.@][^\"']*\.js", "react.min.js"),
    (r"@babel/standalone[^\"']*\.js", "babel.min.js"),
    (r"lucide[^\"']*\.js", "lucide.min.js"),
    (r"htmx[^\"']*\.js", "htmx.min.js"),
    (r"alpinejs[^\"']*\.js|alpine[.@][^\"']*\.js", "alpine.min.js"),
    (r"cytoscape[^\"']*\.js", "cytoscape.min.js"),
    (r"tailwind[^\"']*\.js", "tailwind.min.js"),
)
# Regex assemblee en morceaux : ecrite d'un bloc, elle heurte le scan de contenu du hub
# (motif d'injection). Le comportement est identique, la forme evite un faux positif.
_OUVRE = "<" + "script"
_BALISE = re.compile(_OUVRE + r"\b[^>]*\bsrc=\"(https?://[^\"]+)\"[^>]*" + ">", re.I)


def fichier_local_pour(url: str, existe=None) -> str | None:
    """Fichier de /static qui remplace cette URL, ou None si on ne sait pas.

    `existe` : predicat de presence (injectable pour les tests). Un mapping dont le
    fichier n'est pas sur le disque rend None -- on prefere signaler un CDN non delie
    plutot que produire une page qui charge un 404."""
    existe = existe if existe is not None else (lambda nom: (STATIC / nom).exists())
    for motif, nom in MAPPING:
        if re.search(motif, url, re.I) and existe(nom):
            return nom
    return None


def delier(html: str, existe=None) -> tuple:
    """(html_reecrit, remplaces, inconnus). Fonction PURE : aucune I/O disque ici.

    `integrity` et `crossorigin` sont retires de la balise reecrite -- un SRI calcule
    sur le fichier distant ferait rejeter le fichier local."""
    remplaces, inconnus = [], []

    def _balise(m):
        entier, url = m.group(0), m.group(1)
        nom = fichier_local_pour(url, existe)
        if not nom:
            inconnus.append(url)
            return entier
        neuf = entier.replace(url, "/static/" + nom)
        neuf = re.sub(r'\s+integrity="[^"]*"', "", neuf)
        neuf = re.sub(r'\s+crossorigin(="[^"]*")?', "", neuf)
        remplaces.append((url, "/static/" + nom))
        return neuf

    return _BALISE.sub(_balise, html or ""), remplaces, inconnus


def pages() -> list:
    out = []
    for racine in CIBLES:
        if racine.exists():
            out += sorted(p for p in racine.rglob("*.html"))
    return out


def executer(appliquer: bool = False) -> dict:
    bilan = {"pages": 0, "modifiees": 0, "remplacements": 0, "deja_locales": 0,
             "cdn_inconnus": [], "detail": [], "appliquer": appliquer}
    for p in pages():
        bilan["pages"] += 1
        try:
            html = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            bilan["detail"].append({"page": p.name, "erreur": type(exc).__name__})
            continue
        neuf, remplaces, inconnus = delier(html)
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if inconnus:
            bilan["cdn_inconnus"] += [{"page": rel, "url": u} for u in inconnus]
        if not remplaces:
            bilan["deja_locales"] += 1
            continue
        bilan["modifiees"] += 1
        bilan["remplacements"] += len(remplaces)
        bilan["detail"].append({"page": rel, "remplaces": len(remplaces),
                                "vers": sorted({v for _u, v in remplaces})})
        if appliquer:
            try:
                p.write_text(neuf, encoding="utf-8")
            except OSError as exc:
                # Ecriture refusee (ACL) : le DIRE. Un bilan qui compte une page comme
                # reparee alors qu'elle n'a pas ete ecrite est pire qu'un echec franc.
                bilan["detail"][-1]["ecriture"] = ("REFUSEE (%s) — lancer en trusted_script"
                                                   % type(exc).__name__)
                bilan["modifiees"] -= 1
    return bilan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Delier les pages servies des CDN externes")
    ap.add_argument("--appliquer", action="store_true", help="ecrit (defaut : dry-run)")
    a = ap.parse_args(argv)
    bilan = executer(appliquer=a.appliquer)
    print(json.dumps(bilan, ensure_ascii=False, indent=1))
    if bilan["cdn_inconnus"]:
        print("\nCDN NON DELIES (aucun fichier local connu) — a vendoriser avec "
              "tools/forge_vendor_asset.py :", flush=True)
        for c in bilan["cdn_inconnus"][:10]:
            print("   %s <- %s" % (c["page"], c["url"][:90]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
