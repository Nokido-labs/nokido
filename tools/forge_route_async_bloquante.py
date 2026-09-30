#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_route_async_bloquante.py — rendre au serveur ses fils d'execution.

MESURE 2026-08-26. Sur `app/web_hub/app.py`, **47 routes sur 62** sont declarees
`async def` sans contenir le moindre `await`. Elles font pourtant du travail
SYNCHRONE : lire un manifeste, sonder des services, rendre du HTML.

Ce que fait FastAPI (et c'est le point que l'on paie) :
- `async def`  -> la fonction s'execute DANS la boucle d'evenements. Tout appel
  bloquant y gele **le serveur entier**, pas seulement la requete en cours.
- `def`        -> FastAPI l'envoie dans un threadpool. Une requete lente n'empeche
  plus les autres d'etre servies.

Symptome vecu, et sa lecture faussee : en sondant les endpoints on voyait `/organs`
depasser 11 s, puis TOUTE la file derriere lui expirer -- y compris `/status` et `/`,
qui repondent en 2 ms a froid. On conclut « quarante endpoints morts » alors qu'UN
SEUL bloquait et que les autres attendaient leur tour. Le meme jour, l'owner
signalait « l'UI ne repond pas ».

Une fonction sans `await` n'a AUCUN benefice a etre `async` : la conversion ne retire
rien, elle rend au serveur sa capacite a servir en parallele.

PRUDENCE — ce qui n'est JAMAIS converti (chaque exclusion evite un vrai bug) :
- un corps contenant `await`, `async for`, `async with` : la route est legitimement async ;
- une mention d'`asyncio` : la fonction touche la boucle, on n'y touche pas ;
- `request.form()` / `.json()` / `.body()` / `.stream()` sans `await` : ce sont des
  coroutines. Sans `await` la route est DEJA cassee ; la convertir masquerait le
  defaut au lieu de le montrer. On la SIGNALE (« suspecte ») et on l'ecarte.

CE QUE CET OUTIL NE VOIT PAS — angle mort MESURE le 2026-08-26, le jour meme.
`/api/vitals/sse` appelait `all_vitals()` de facon SYNCHRONE (5 a 50 s) dans son
generateur, toutes les 5 s et une fois PAR CLIENT : il gelait le serveur exactement
comme les 47 routes. L'outil l'a classe « legitimement async » parce que la fonction
contient un `await asyncio.sleep(5)`. **Une route async peut donc etre bloquante meme
quand elle attend quelque part** : la presence d'un `await` prouve que la fonction
rend la main, pas qu'elle la rend ASSEZ SOUVENT.

Le critere « aucun await » reste juste — il ne rend aucun faux positif — mais il est
INCOMPLET. Le complement ne se cherche pas ici : il se lit dans le temps de reponse.
Une route qui bloque sous charge se voit en sondant SEQUENTIELLEMENT et en demandant
un endpoint trivial PENDANT qu'une route lourde travaille (cf. la mesure /organs vs
/health). Verifie apres correction : zero appel synchrone couteux restant dans un
corps async du portail.

Usage :
    LAFORGE_PYTHON tools/forge_route_async_bloquante.py            # rapport (defaut)
    run action=trusted_script path=tools/... script_args="--appliquer"
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLES = ("app/web_hub/app.py",)

__FORGE_COLOR__ = "interface/concurrence-service"  # le serveur doit pouvoir servir a plusieurs

_DECOS = {"get", "post", "put", "delete", "patch", "head", "options", "api_route"}
# `websocket` est HORS champ : une route websocket est asynchrone par nature.
_COROUTINES_REQUETE = ("request.form", "request.json", "request.body", "request.stream",
                       ".form()", ".json()", ".body()")


def _est_route(noeud) -> bool:
    for d in noeud.decorator_list:
        cible = d.func if isinstance(d, ast.Call) else d
        if isinstance(cible, ast.Attribute) and cible.attr in _DECOS:
            return True
    return False


def _attend_quelque_chose(noeud) -> bool:
    return any(isinstance(x, (ast.Await, ast.AsyncFor, ast.AsyncWith))
               for x in ast.walk(noeud))


def analyser(source: str, nom_fichier: str = "<source>") -> dict:
    """Classement PUR des routes. Aucune I/O.

    Rend {convertibles, deja_sync, async_legitimes, suspectes} — quatre etats, parce
    que « pas convertible » recouvre deux realites tres differentes : une route
    legitimement async, et une route deja cassee qu'il faut montrer."""
    arbre = ast.parse(source, filename=nom_fichier)
    out = {"convertibles": [], "deja_sync": [], "async_legitimes": [], "suspectes": []}
    lignes = source.splitlines()
    for n in ast.walk(arbre):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _est_route(n):
            continue
        if isinstance(n, ast.FunctionDef):
            out["deja_sync"].append({"nom": n.name, "ligne": n.lineno})
            continue
        if _attend_quelque_chose(n):
            out["async_legitimes"].append({"nom": n.name, "ligne": n.lineno})
            continue
        corps = "\n".join(lignes[n.lineno - 1:(n.end_lineno or n.lineno)])
        if "asyncio" in corps:
            out["async_legitimes"].append({"nom": n.name, "ligne": n.lineno,
                                           "motif": "touche la boucle (asyncio)"})
        elif any(m in corps for m in _COROUTINES_REQUETE):
            out["suspectes"].append({
                "nom": n.name, "ligne": n.lineno,
                "motif": "coroutine de requete appelee SANS await — route deja cassee, "
                         "a corriger a la main (la convertir masquerait le defaut)"})
        else:
            out["convertibles"].append({"nom": n.name, "ligne": n.lineno})
    return out


def convertir(source: str, noms: set) -> tuple:
    """Retire `async ` devant les `def` nommes. Rend (source, convertis).

    Ancre sur `async def <nom>(` : jamais une substitution large, qui toucherait des
    fonctions homonymes ou du texte de docstring."""
    convertis = []
    for nom in sorted(noms):
        motif = "async def %s(" % nom
        if motif in source:
            source = source.replace(motif, "def %s(" % nom, 1)
            convertis.append(nom)
    return source, convertis


def executer(appliquer: bool = False) -> dict:
    bilan = {"fichiers": 0, "convertis": 0, "detail": [], "appliquer": appliquer}
    for rel in CIBLES:
        p = ROOT / rel
        if not p.exists():
            bilan["detail"].append({"fichier": rel, "etat": "ABSENT"})
            continue
        bilan["fichiers"] += 1
        src = p.read_text(encoding="utf-8", errors="replace")
        vu = analyser(src, rel)
        entree = {"fichier": rel,
                  "convertibles": len(vu["convertibles"]),
                  "deja_sync": len(vu["deja_sync"]),
                  "async_legitimes": len(vu["async_legitimes"]),
                  "suspectes": vu["suspectes"]}
        if appliquer and vu["convertibles"]:
            neuf, faits = convertir(src, {r["nom"] for r in vu["convertibles"]})
            try:
                ast.parse(neuf, filename=rel)      # jamais ecrire un fichier casse
            except SyntaxError as exc:
                entree["ecriture"] = "REFUSEE : AST casse apres conversion (%s)" % exc
                bilan["detail"].append(entree)
                continue
            try:
                p.write_text(neuf, encoding="utf-8")
                entree["convertis"] = faits
                bilan["convertis"] += len(faits)
            except OSError as exc:
                entree["ecriture"] = ("REFUSEE (%s) — lancer en trusted_script"
                                      % type(exc).__name__)
        bilan["detail"].append(entree)
    return bilan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Routes async sans await = boucle bloquee")
    ap.add_argument("--appliquer", action="store_true", help="ecrit (defaut : rapport)")
    a = ap.parse_args(argv)
    bilan = executer(appliquer=a.appliquer)
    print(json.dumps(bilan, ensure_ascii=False, indent=1))
    for d in bilan["detail"]:
        for s in d.get("suspectes") or ():
            print("\n⚠ %s:%d %s — %s" % (d["fichier"], s["ligne"], s["nom"], s["motif"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
