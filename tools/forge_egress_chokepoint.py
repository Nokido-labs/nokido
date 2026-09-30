#!/usr/bin/env python
"""forge_egress_chokepoint.py -- ou sort reellement une donnee vers un LLM ?

Mesure 2026-09-02 : la politique de partage (`forge_share_policy`) a ete branchee
dans `forge_swarm_router.route_subtask`, et `router_call` s'est revele atteint par
plusieurs AUTRES chemins. Un garde pose sur une artere n'est pas pose sur le coeur.

Ce module ne corrige rien : il CARTOGRAPHIE, pour qu'on puisse decider ou rendre le
preflight obligatoire. Pour chaque appel a `router_call`, il rend :

    fichier:ligne · fonction englobante · le preflight est-il consulte ici ?
    · et surtout : les informations NECESSAIRES A LA DECISION sont-elles
      disponibles a cet endroit (data_class, collaboration, audience, identite) ?

Cette derniere colonne est le point decisif : deplacer brutalement le preflight
dans `router_call` serait FAUX si les champs n'y arrivent jamais -- on obtiendrait
un garde qui refuse tout, ou pire, qui laisse passer sur des valeurs vides.

METHODE. AST, pas `findstr` : une recherche textuelle compte les commentaires, les
docstrings et les mentions dans la prose. Mesure du 2026-08-10 : une recherche par
nom de fonction avait rendu 18 appelants dont 17 faux. On croise donc l'appel AST
avec la presence d'un import du module qui definit la fonction.

Usage :  LAFORGE_PYTHON tools/forge_egress_chokepoint.py [--json]
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/cartographie-egress"

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZONES = ("app", "tools")
EXCLUS = ("_attic", "legacy", "node_modules", ".git")

CIBLE = "router_call"
MODULE_CIBLE = "forge_llm_router"

# Ce dont la decision de partage a besoin. Un appelant qui n'en dispose pas ne peut
# pas decider -- il ne peut que transmettre ce qu'on lui a donne.
CHAMPS_DECISION = ("data_class", "collaboration", "audience")
CHAMPS_IDENTITE = ("token", "agent", "agent_cible", "identity", "sender")

# JAMAIS sous pytest : reconfigurer le flux de CAPTURE le referme pour les tests
# suivants du meme worker xdist (mesure 2026-09-04).
if "pytest" not in sys.modules:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001  # muet-ok : confort console
            pass


def _fichiers():
    for zone in ZONES:
        for p in (ROOT / zone).rglob("*.py"):
            if any(x in p.parts for x in EXCLUS):
                continue
            yield p


def _englobante(arbre, ligne):
    """Fonction contenant `ligne`, et la liste de SES parametres."""
    meilleure = None
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fin = getattr(n, "end_lineno", n.lineno)
            if n.lineno <= ligne <= fin:
                if meilleure is None or n.lineno > meilleure.lineno:
                    meilleure = n
    if meilleure is None:
        return "<module>", [], False
    a = meilleure.args
    noms = [x.arg for x in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)]
    return meilleure.name, noms, bool(a.kwarg)


def cartographier() -> list:
    lignes = []
    for p in _fichiers():
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            arbre = ast.parse(src)
        except (OSError, SyntaxError) as e:
            # ILLISIBLE : troisieme etat. Un fichier non analyse n'est pas un
            # fichier sans appel -- le dire, sinon la couverture est surestimee.
            lignes.append({"fichier": str(p.relative_to(ROOT)).replace("\\", "/"),
                           "etat": "ILLISIBLE", "detail": str(e)[:120]})
            continue
        importe = MODULE_CIBLE in src
        consulte_politique = "forge_share_policy" in src
        for n in ast.walk(arbre):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            nom = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if nom != CIBLE:
                continue
            fonction, params, a_kwargs = _englobante(arbre, n.lineno)
            if fonction == CIBLE:      # la definition elle-meme
                continue
            # INVARIANT ARCHITECTURAL : l'appel transporte-t-il un contexte declare ?
            # C'est la seule facon de rendre l'oubli VISIBLE : un champ perdu dans
            # `**kwargs` ne se voit ni a la lecture ni au test.
            porte_contexte = any(k.arg == "context" for k in n.keywords if k.arg)
            lignes.append({
                "fichier": str(p.relative_to(ROOT)).replace("\\", "/"),
                "ligne": n.lineno,
                "fonction": fonction,
                "etat": "APPEL" if importe else "APPEL_SANS_IMPORT",
                "preflight_dans_le_fichier": consulte_politique,
                "porte_contexte": porte_contexte,
                "champs_decision": [c for c in CHAMPS_DECISION if c in params],
                "champs_identite": [c for c in CHAMPS_IDENTITE if c in params],
                "kwargs_ouverts": a_kwargs,
            })
    return lignes


def rapport(lignes: list) -> dict:
    appels = [l for l in lignes if l.get("etat", "").startswith("APPEL")]
    illisibles = [l for l in lignes if l.get("etat") == "ILLISIBLE"]
    gardes = [l for l in appels if l["preflight_dans_le_fichier"]]
    avec_ctx = [l for l in appels if l.get("porte_contexte")]
    return {
        "appels": len(appels),
        "gardes": len(gardes),
        "non_gardes": len(appels) - len(gardes),
        "avec_contexte": len(avec_ctx),
        "sans_contexte": [
            "%s:%s (%s)" % (l["fichier"], l["ligne"], l["fonction"])
            for l in appels if not l.get("porte_contexte")],
        "illisibles": len(illisibles),
        "detail": lignes,
        # Un appelant qui ne recoit AUCUN champ de decision ne peut pas decider :
        # il faudrait que la decision soit prise plus haut, ou qu'un contexte
        # obligatoire descende jusqu'a lui.
        "sans_aucun_champ_de_decision": [
            "%s:%s (%s)" % (l["fichier"], l["ligne"], l["fonction"])
            for l in appels if not l["champs_decision"]],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = rapport(cartographier())
    if a.json:
        print(json.dumps(r, indent=1, ensure_ascii=False))
        return 0
    print("appels a %s() : %d | gardes : %d | NON gardes : %d | AVEC contexte : %d/%d "
          "| fichiers illisibles : %d"
          % (CIBLE, r["appels"], r["gardes"], r["non_gardes"],
             r["avec_contexte"], r["appels"], r["illisibles"]))
    print()
    for l in r["detail"]:
        if l.get("etat") == "ILLISIBLE":
            print("  ILLISIBLE  %s -- %s" % (l["fichier"], l["detail"]))
            continue
        print("  %-44s L%-5s %-26s ctx=%-5s garde=%-5s identite=%s%s"
              % (l["fichier"], l["ligne"], l["fonction"][:26],
                 l.get("porte_contexte"),
                 l["preflight_dans_le_fichier"],
                 ",".join(l["champs_identite"]) or "AUCUNE",
                 "  **kwargs" if l["kwargs_ouverts"] else ""))
    print()
    print("Appels SANS contexte (%d) -- objectif : 0 :" % len(r["sans_contexte"]))
    for s in r["sans_contexte"]:
        print("   ", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
