"""Matrice d'autorisation candidate : croise le STATIQUE, la SONDE et le RUNTIME.

__FORGE_COLOR__ = "immunitaire/matrice-autorisation"

Ce module ne DECIDE rien. Il assemble, pour chacune des 81 routes de `:8766`,
ce que trois observateurs INDEPENDANTS en disent, et propose une classe et une
capability -- en nommant a chaque fois la PREUVE sur laquelle la proposition
repose. Une proposition sans preuve nommee est une supposition qui prendra
l'autorite d'une mesure des qu'elle sera relue.

Les trois observateurs, et ce que chacun ne peut PAS voir :

- `forge_route_authz_audit.auditer()` -- statique : declaration des routes et
  appelants presents dans le depot. **Aveugle** a tout client externe, script
  hors depot, navigateur ou CLI : « aucun appelant trouve » n'est jamais
  « personne ne l'appelle ».
- la SONDE HTTP sans jeton -- comportement reel, mais **GET seulement** : les
  40 routes POST restent hors de sa portee, puisque les mesurer exigerait de
  declencher la mutation qu'on veut gouverner.
- `forge_authz_shadow.matrice()` -- runtime : appelants REELLEMENT observes,
  avec PID et processus. **Aveugle** a tout ce qui n'est pas passe pendant la
  fenetre : une route appelee une fois par jour n'y figure pas.

Aucun des trois ne suffit. Leur DESACCORD est l'information la plus utile : une
route que le statique dit sans appelant et que le runtime voit appelee 83 fois
designe un client hors depot, ce qu'aucun des deux ne dirait seul.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

SORTIE = ROOT / "sandbox" / "authz_matrice.json"

# Capability proposee d'apres le CHEMIN. Volontairement grossier et declare
# comme tel : c'est un point de depart pour la revue, jamais un verdict. Le
# premier segment porte le domaine, le verbe vient de la methode HTTP.
_DOMAINES = (
    ("/api/resource", "resource"), ("/api/services", "service"),
    ("/api/sandbox", "sandbox"), ("/api/rag", "rag"), ("/api/graph", "graph"),
    ("/api/hormones", "hormone"), ("/api/mcp", "mcp"), ("/api/watch", "watch"),
    ("/api/network", "network"), ("/api/swarm", "swarm"), ("/api/audit", "audit"),
    ("/api/agents", "agent"), ("/api/organs", "organ"), ("/api/loops", "loop"),
    ("/api/ring_buffer", "ring_buffer"), ("/api/push", "inbox"),
    ("/api/ingest", "ingest"), ("/ingest", "ingest"), ("/admin", "admin"),
    ("/mcp", "mcp"), ("/forge", "forge"), ("/nervous_system", "nervous_system"),
    ("/orchestrate", "orchestrate"), ("/mpc", "plan"), ("/ui", "ui"),
    ("/gui", "ui"), ("/inbox", "inbox"), ("/debug", "debug"), ("/health", "health"),
)


# EXCEPTIONS MESUREES au mapping chemin+methode. Finding M2M #3 : deriver la
# capability de la METHODE HTTP casse dans les deux sens -- un GET peut muter,
# un POST peut n'etre qu'une lecture au corps trop gros pour une URL.
#
# Chaque entree ici a ete etablie en LISANT le handler, et porte sa preuve.
# Sans cette exigence, la table deviendrait un endroit ou l'on corrige les
# classements qui derangent.
_CAPABILITY_MESUREE: Dict[str, tuple] = {
    "/api/rag/tokenize": (
        "rag.read",
        "handler lu (nokido_hub L3062) : compte des tokens via tiktoken sur un "
        "texte du corps, aucune I/O, aucune ecriture. POST uniquement parce "
        "qu'un texte de 50 000 caracteres ne tient pas dans une URL. "
        "`rag.write` etait un SUR-privilege.",
    ),
    "/mpc/plan": (
        "plan.write",
        "handler lu (nokido_hub L4265) : boucle MPC dont le contrat est "
        "d'EXECUTER des actions via `execute_fn`. Son implementation actuelle "
        "ne joint que /health et /rag/query -- deux lectures -- mais calibrer "
        "la capability sur l'implementation du JOUR la rendrait fausse des "
        "qu'une branche mutante s'ajoute, sans que personne ne le remarque. "
        "Reste `.write` : la capability suit le CONTRAT, pas l'etat du code.",
    ),
}


def _capability(route: str, methodes: List[str]) -> str:
    mesuree = _CAPABILITY_MESUREE.get(route)
    if mesuree:
        return mesuree[0]
    domaine = next((d for p, d in _DOMAINES if route.startswith(p)), None)
    if domaine is None:
        return "UNKNOWN (aucun domaine reconnu dans le chemin)"
    mute = any(m in methodes for m in ("POST", "PUT", "DELETE", "PATCH"))
    return "%s.%s" % (domaine, "write" if mute else "read")


def capability_preuve(route: str) -> str:
    """Pourquoi cette capability. Chaine vide = derivee du chemin, NON mesuree.

    La distinction compte : une capability derivee est une hypothese de travail,
    une capability mesuree a un handler lu derriere elle. Les afficher pareil
    ferait passer les 79 hypotheses pour des verdicts.
    """
    m = _CAPABILITY_MESUREE.get(route)
    return m[1] if m else ""


def _proposer(route: Dict[str, Any], sonde: str, vus: Dict[str, Any]) -> Dict[str, Any]:
    """Propose l'EXPOSITION et l'AUTHENTIFICATION separement, avec la preuve.

    Correction du 2026-09-02 (finding M2M #4) : cette fonction rendait une
    classe unique, et proposait `LOCAL` des qu'un appelant local avait ete
    OBSERVE. La localite devenait ainsi une autorisation par la porte de
    derriere. Desormais un appelant observe ne produit QUE
    `exposure=LOCAL_ONLY` -- l'authentification, elle, reste `UNKNOWN` tant
    qu'aucune identite de service n'a ete delivree.

        etre observe != etre identifie != etre autorise
    """
    from nokido_agent.app import forge_authz_shadow as az

    chemin = route["route"]
    appelants_depot = route.get("appelants_dans_le_depot") or []
    observes = sorted((vus or {}).get("appelants", {}))

    d = az.DECLARE.get(chemin)
    if d:
        return {"exposure_proposee": d["exposure"],
                "authentication_proposee": d["authentication"],
                "preuve": "DECLAREE explicitement avec motif",
                "action": "aucune -- deja tranchee"}
    if sonde == "REFUSEE_AUTH":
        return {"exposure_proposee": "LOCAL_ONLY",
                "authentication_proposee": "REQUIRED",
                "preuve": "SONDE : refuse deja en 401 sans jeton",
                "action": "enteriner REQUIRED : la protection existe deja"}
    if observes:
        return {"exposure_proposee": "LOCAL_ONLY",
                "authentication_proposee": "UNKNOWN",
                "preuve": "RUNTIME : appelants observes %s -- PROVENANCE, pas "
                          "identite" % observes,
                "action": "delivrer une identite de service a ces appelants puis "
                          "trancher REQUIRED. Ne PAS autoriser sur la localite : "
                          "un PID se reutilise et un nom de process s'usurpe"}
    if appelants_depot:
        return {"exposure_proposee": "LOCAL_ONLY",
                "authentication_proposee": "UNKNOWN",
                "preuve": "STATIQUE : appelants dans le depot %s"
                          % [a for a in appelants_depot][:3],
                "action": "confirmer en runtime avant de trancher : le depot "
                          "montre qui PEUT appeler, pas qui appelle"}
    return {"exposure_proposee": "UNKNOWN",
            "authentication_proposee": "UNKNOWN",
            "preuve": "AUCUNE : ni appelant au depot, ni appel observe, "
                      "et la sonde ne tranche pas",
            "action": "NE PAS autoriser. Chercher un client hors depot (UI, CLI, "
                      "navigateur) avant toute decision"}


def construire() -> Dict[str, Any]:
    from nokido_agent.app import forge_authz_shadow as az
    from nokido_agent.tools.forge_route_authz_audit import auditer, classer_sonde, prober

    inv = auditer(avec_appelants=True)
    routes = inv["routes"]
    mesures = prober(routes)
    runtime = az.matrice()

    lignes: List[Dict[str, Any]] = []
    for r in routes:
        chemin = r["route"]
        sonde = classer_sonde(mesures[chemin]) if chemin in mesures else "NON_SONDEE"
        vus = runtime["routes"].get(chemin)
        prop = _proposer(r, sonde, vus)
        lignes.append({
            "route": chemin,
            "methodes": r["methodes"],
            "classe_statique": r["classe"],
            "garde_detectee": r["garde_detectee"],
            "sonde": sonde,
            "appels_observes": (vus or {}).get("n", 0),
            "appelants_observes": sorted((vus or {}).get("appelants", {})),
            "appelants_depot": r.get("appelants_dans_le_depot") or [],
            "capability_proposee": _capability(chemin, r["methodes"]),
            "capability_mesuree": bool(capability_preuve(chemin)),
            "capability_preuve": capability_preuve(chemin),
            **prop,
        })

    # Le DESACCORD entre observateurs est le signal le plus utile : il designe
    # ce qu'aucune source ne pouvait dire seule.
    desaccords = [
        x for x in lignes
        if x["appels_observes"] and not x["appelants_depot"]
    ]
    return {
        "routes": lignes,
        "total": len(lignes),
        "par_exposition": {
            c: sum(1 for x in lignes if x["exposure_proposee"] == c)
            for c in ("PUBLIC", "LOCAL_ONLY", "UNKNOWN")
        },
        "par_authentification": {
            c: sum(1 for x in lignes if x["authentication_proposee"] == c)
            for c in ("NONE", "REQUIRED", "UNKNOWN")
        },
        "non_sondees": sum(1 for x in lignes if x["sonde"] == "NON_SONDEE"),
        "capabilites_mesurees": sum(1 for x in lignes if x["capability_mesuree"]),
        "capabilites_derivees": sum(1 for x in lignes if not x["capability_mesuree"]),
        "fenetre_runtime": {"appels_lus": runtime.get("lues", 0),
                            "raison": runtime.get("raison", "")},
        "desaccord_statique_runtime": [x["route"] for x in desaccords],
        "avertissement": (
            "Aucune ligne n'est une DECISION. Les 40 routes non sondees restent "
            "UNKNOWN et surtout pas PROTECTED ; « aucun appelant trouve » ne veut "
            "pas dire « personne ne l'appelle » ; et une route absente de la "
            "fenetre runtime n'est pas une route morte."
        ),
    }


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="ecrit sandbox/authz_matrice.json")
    ap.add_argument("--classe", help="ne montrer qu'une classe proposee")
    a = ap.parse_args(argv)

    m = construire()
    print("routes                 : %d" % m["total"])
    print("EXPOSITION (transport) : %s" % m["par_exposition"])
    print("AUTHENTIFICATION       : %s" % m["par_authentification"])
    print("  -> les deux axes sont SEPARES : LOCAL_ONLY ne vaut pas TRUSTED,")
    print("     et un appelant observe n'est ni identifie ni autorise.")
    print("non sondees (POST/parm): %d  -> UNKNOWN, jamais PROTECTED" % m["non_sondees"])
    print("capabilites            : %d mesurees (handler lu) / %d derivees du chemin"
          % (m["capabilites_mesurees"], m["capabilites_derivees"]))
    print("  -> une capability derivee est une HYPOTHESE, pas un verdict.")
    print("fenetre runtime        : %d appels lus %s"
          % (m["fenetre_runtime"]["appels_lus"], m["fenetre_runtime"]["raison"]))
    if m["desaccord_statique_runtime"]:
        print("\nDESACCORD statique/runtime (appelees SANS appelant au depot) :")
        for r in m["desaccord_statique_runtime"]:
            print("   %s  <- client HORS DEPOT (UI, CLI, navigateur, autre machine)" % r)

    print("\n%-32s %-11s %-9s %-13s %5s  %s"
          % ("ROUTE", "EXPOSITION", "AUTH", "SONDE", "VUS", "CAPABILITY"))
    for x in sorted(m["routes"], key=lambda z: (z["authentication_proposee"],
                                                z["exposure_proposee"], z["route"])):
        if a.classe and a.classe not in (x["exposure_proposee"],
                                         x["authentication_proposee"]):
            continue
        print("%-32s %-11s %-9s %-13s %5d  %s"
              % (x["route"][:32], x["exposure_proposee"],
                 x["authentication_proposee"], x["sonde"],
                 x["appels_observes"], x["capability_proposee"]))
        print("%36s%s" % ("", x["preuve"][:100]))

    if a.json:
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\necrit : %s" % SORTIE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
