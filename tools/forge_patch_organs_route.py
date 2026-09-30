#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_patch_organs_route.py — ajoute les routes /organs a web_hub/app.py.

app/web_hub/app.py est CRITICAL_FILE : governed_edit le refuse sans fenetre owner.
Ce patch git-tracke, lance en trusted_script avec l accord owner (brique 2 de
l UI qui se deduit du corps), ajoute DEUX routes GET en LECTURE SEULE :
  GET /organs          -> page anatomie vivante (manifest_cards.render_organs_page)
  GET /organs/partial  -> fragment HTMX rafraichi
Purement additif : aucune route existante n est touchee. Le gate AST du
pre-commit revalide au commit.

Idempotent : NOOP si /organs est deja cable. Verifie AST + octet apres ecriture.
"""
from __future__ import annotations

import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIBLE = os.path.join(ROOT, "app", "web_hub", "app.py")

ANCRE = (
    "    body, code, headers = route_diag_partial()\n"
    "    return HTMLResponse(body, status_code=code)\n"
)

AJOUT = (
    "    body, code, headers = route_diag_partial()\n"
    "    return HTMLResponse(body, status_code=code)\n"
    "\n"
    "\n"
    '@app.get("/organs", response_class=HTMLResponse)\n'
    "async def organs_page_route():\n"
    '    """Anatomie vivante : chaque surface UI avec son ETAT REEL, deduit du\n'
    "    manifest (brique 2 de l UI qui se deduit du corps). Fini l onglet mort.\"\"\"\n"
    "    from app.web_hub.manifest_cards import render_organs_page\n"
    "\n"
    "    return HTMLResponse(render_organs_page())\n"
    "\n"
    "\n"
    '@app.get("/organs/partial", response_class=HTMLResponse)\n'
    "async def organs_partial_route():\n"
    '    """Fragment HTMX rafraichi : la section des organes seule."""\n'
    "    from app.web_hub.manifest_cards import render_organs\n"
    "\n"
    "    return HTMLResponse(render_organs())\n"
)

SENTINELLE = '@app.get("/organs"'


def main() -> int:
    src = open(CIBLE, encoding="utf-8").read()

    if SENTINELLE in src:
        print("[patch] NOOP : routes /organs deja cablees")
        return 0
    if ANCRE not in src:
        print("ABORT: ancre diag_partial_route introuvable — le fichier a change, "
              "ne PAS patcher a l aveugle.")
        return 2
    if src.count(ANCRE) != 1:
        print(f"ABORT: ancre ambigue ({src.count(ANCRE)} occurrences)")
        return 2

    neuf = src.replace(ANCRE, AJOUT, 1)
    try:
        ast.parse(neuf)
    except SyntaxError as exc:
        print(f"ABORT: le resultat ne parse pas ({exc}) — rien ecrit")
        return 3

    open(CIBLE, "w", encoding="utf-8").write(neuf)
    if open(CIBLE, encoding="utf-8").read() != neuf:
        print("CRITIQUE: relecture != ecrit")
        return 4
    print(f"[patch] routes /organs cablees — {len(neuf)} octets, AST OK, relecture identique")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
