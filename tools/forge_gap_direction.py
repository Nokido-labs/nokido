#!/usr/bin/env python
"""forge_gap_direction.py — croise CE QUI CLOCHE avec CE QU'ON VEUT. Lecture seule.

LE MANQUE (mesure 2026-07-30)
    Les deux moities existaient et produisaient des donnees, sans jamais se parler :
      - connaissance de soi : `forge_organ_agents.regulation_gaps()` — 1598 modules
        audites, 15 organes en defaut, 12 morts silencieuses, 65 zones mortes ;
      - direction voulue : 199 faits au blackboard `architecture_rules`, dont 45 au
        format roadmap (`CURRENT:` `NEXT:` `BLOCKER:` `P0:` `P1:` `P2:`).
    Personne ne les CROISAIT. Resultat : des defauts mesures que rien ne priorise, et
    une roadmap que rien ne confronte au reel. Ce module est le JOIN manquant, pas une
    mesure de plus — exactement comme le levier RAM du meme jour, qui existait mais
    n'avait aucun candidat.

CE QU'IL REND, EN TROIS PAQUETS
    1. ALIGNE          — un defaut MESURE que la roadmap reclame. C'est le travail a
                         faire : il est justifie des deux cotes, avec sa preuve.
    2. HORS DIRECTION  — un defaut mesure que la roadmap n'evoque pas. Listé, jamais
                         pousse : differer consciemment vaut mieux que s'eparpiller.
    3. SANS MESURE     — une priorite de roadmap qu'AUCUN defaut ne soutient. Soit
                         elle est faite, soit personne ne la mesure. C'est le paquet
                         le plus utile : il attrape une roadmap qui a perdu contact.

CE QU'IL NE FAIT PAS
    Il ne propose JAMAIS de supprimer une `dead_zone`. RULES_SHARED : le capteur ne
    voit ni les taches planifiees ni les lanceurs de boot du profil owner, donc une
    zone morte est un signal a instruire, pas un permis d'effacer.

USAGE
    LAFORGE_PYTHON tools/forge_gap_direction.py
    LAFORGE_PYTHON tools/forge_gap_direction.py --json
    LAFORGE_PYTHON tools/forge_gap_direction.py --top 8
"""

from __future__ import annotations

__FORGE_COLOR__ = "cognition/gap-direction"

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Poids d'urgence. `silent_death` passe AVANT `dead_zone` : un service lance sans
# heartbeat meurt sans que personne ne le sache, alors qu'une zone morte est
# d'abord un doute sur le capteur (cf RULES_SHARED).
POIDS_NATURE = {"silent_death": 3, "dead_zone": 1}
# Une roadmap nomme souvent une CATEGORIE et non un module : « 27 modules lances
# SANS heartbeat surveille (mort silencieuse) » couvre les 12 morts silencieuses
# mesurees, meme si aucune n'y figure par son nom. Exiger le nom faisait tomber
# `nokido_hub.py` en hors-direction alors que la roadmap parlait precisement de lui
# (mesure 2026-07-30). L'appariement par nature est SEMANTIQUE, pas laxiste : il
# repose sur des expressions qui designent le defaut, pas sur une ressemblance.
EXPRESSIONS_NATURE = {
    "silent_death": ("mort silencieuse", "sans heartbeat", "heartbeat surveille",
                     "silent_death", "meurt sans", "mort sans"),
    "dead_zone": ("zone morte", "zones mortes", "dead_zone", "non classe",
                  "non classes", "__forge_color__"),
}
POIDS_PRIORITE = {"P0": 5, "BLOCKER": 5, "NEXT": 3, "CURRENT": 2, "P1": 2, "P2": 1}
PREFIXES = tuple(POIDS_PRIORITE)


def _gaps() -> dict:
    """Ce qui cloche, mesure. Rend {"etat": "ILLISIBLE"} plutot que zero silencieux."""
    try:
        from nokido_agent.app.forge_organ_agents import regulation_gaps

        g = regulation_gaps() or {}
    except Exception as e:  # noqa: BLE001
        return {"etat": "ILLISIBLE", "raison": f"{type(e).__name__}: {str(e)[:110]}"}
    if not g.get("ok"):
        return {"etat": "ILLISIBLE", "raison": "regulation_gaps a repondu ok=False"}
    return {"etat": "ok", "by_organ": g.get("by_organ") or {},
            "totaux": {k: g.get(k) for k in
                       ("modules_audited", "organs_with_gaps",
                        "silent_death_total", "dead_zone_total")}}


def _roadmap() -> dict:
    """Ce qu'on veut. Le format attendu par forge_ssot_maintainer est un PREFIXE :
    sans lui un fait n'entre pas dans la roadmap, et ce module ne l'inventera pas."""
    try:
        from nokido_agent.app import forge_swarm_blackboard as BB

        brut = BB.read_zone("architecture_rules")
    except Exception as e:  # noqa: BLE001
        return {"etat": "ILLISIBLE", "raison": f"{type(e).__name__}: {str(e)[:110]}"}
    faits = brut if isinstance(brut, list) else (
        (brut or {}).get("facts") or (brut or {}).get("entries") or [])
    items: list[dict] = []
    ecartes: list[str] = []
    for f in faits:
        texte = str(f.get("value") if isinstance(f, dict) else f)
        cle = str(f.get("key") if isinstance(f, dict) else "")
        haut = texte.upper()
        # La priorite est celle qui PREFIXE le fait, donc la plus a GAUCHE — pas la
        # premiere de ma propre liste. Mesure 2026-07-30 : cinq faits commencant par
        # `NEXT:` sortaient etiquetes `BLOCKER` parce que le mot apparaissait plus
        # loin dans le texte et que mon ordre de test primait sur la position.
        # Le corps ecrit DEUX formes : `CURRENT:` et `CURRENT 28-07:` (mot-clef,
        # qualificatif, deux-points). Exiger le deux-points COLLE rendait la seconde
        # invisible, et c'est alors un mot-clef situe PLUS LOIN dans le texte qui
        # gagnait. Mesure 2026-07-30 : 2 faits sur 45 mal etiquetes, dont un `CURRENT`
        # promu `BLOCKER` (fausse urgence) et surtout un `P0` de l'owner degrade en
        # `P2` -- donc trie en bas et ignore. Le second sens est le plus couteux :
        # gonfler une urgence se voit, en enterrer une ne se voit pas.
        # Un PREFIXE est en TETE. Trois formes payees le 2026-07-30 :
        #   `BLOCKER: ...`        -> retenu
        #   `CURRENT 28-07: ...`  -> retenu (mot-clef + qualificatif, forme reelle du corps ;
        #                            exiger le deux-points COLLE la rendait invisible et un
        #                            mot-clef situe plus loin gagnait a sa place)
        #   `RESOLU 26-07 (etait un BLOCKER depuis le 22-07)` -> ECARTE, c'est une MENTION
        # La deuxieme correction a ete faite en reaction a la premiere : avoir relache la
        # recherche a tout le texte fabriquait des urgences a partir de notes de clotures.
        # Precision AVANT couverture -- une etiquette inventee se propage en RAG et dans
        # l'atlas, ou plus rien ne la distingue d'une mesure.
        positions = []
        for p in PREFIXES:
            m = re.match(r"[\s\-*>#]{0,4}" + p + r"\b", haut)
            if m:
                positions.append((m.start(), p))
        prio = min(positions)[1] if positions else None
        if not prio:
            ecartes.append(cle or texte[:40])
            continue
        items.append({"cle": cle, "priorite": prio, "texte": texte})
    # Un filtre qui ecarte des donnees le DIT, sinon la couverture est surestimee en
    # silence : 154 faits de la zone ne portent aucune priorite en tete, ce sont des
    # notes, pas des items de roadmap.
    return {"etat": "ok", "items": items, "n_total": len(faits),
            "ecartes_sans_prefixe": len(ecartes)}


def _sujets(module: str) -> list[str]:
    """Formes sous lesquelles un module peut etre NOMME dans une roadmap."""
    base = re.sub(r"\.(py|ts|bat|ps1|js)$", "", module)
    out = {module, base}
    out.add(base.replace("forge_", ""))
    out.add(base.replace("_", " "))
    return [s for s in out if len(s) >= 5]


def croiser(gaps: dict, road: dict) -> dict:
    if gaps.get("etat") != "ok" or road.get("etat") != "ok":
        return {"etat": "ILLISIBLE",
                "gaps": gaps.get("raison"), "roadmap": road.get("raison")}
    items = road["items"]
    textes = [(i, i["texte"].lower()) for i in items]

    alignes: list[dict] = []
    hors: list[dict] = []
    reclames: set[str] = set()

    for organe, natures in gaps["by_organ"].items():
        for nature in ("silent_death", "dead_zone"):
            for module in (natures.get(nature) or []):
                # Preuve NOMMEE d'abord : la roadmap cite le module lui-meme.
                preuve, genre = None, None
                for item, bas in textes:
                    if any(s.lower() in bas for s in _sujets(module)):
                        preuve, genre = item, "nommee"
                        break
                # A defaut, preuve de CATEGORIE : la roadmap designe le DEFAUT et non
                # le module. Justification reelle, plus faible qu'un nom, plus forte
                # qu'une famille d'organe.
                if preuve is None:
                    for item, bas in textes:
                        if any(x in bas for x in EXPRESSIONS_NATURE[nature]):
                            preuve, genre = item, "categorie"
                            break
                # A defaut, preuve d'ORGANE — volontairement DEGRADEE et etiquetee.
                # Sans ce marquage, « non classe » matchait « 206 modules non classes »
                # et cinq modules differents citaient le meme fait generique comme
                # justification : une correspondance faible presentee comme forte.
                if preuve is None:
                    org = organe.lower()
                    if len(org) >= 8 and not org.startswith("non class"):
                        for item, bas in textes:
                            if org[:14] in bas:
                                preuve, genre = item, "organe"
                                break
                fiche = {"module": module, "organe": organe, "nature": nature,
                         "score": POIDS_NATURE[nature]}
                if preuve:
                    reclames.add(preuve["cle"])
                    # Une preuve d'organe ne vaut pas une preuve nommee : +1 fixe,
                    # sinon le poids de la priorite. Le tri s'en charge ensuite.
                    _bonus = {"nommee": POIDS_PRIORITE.get(preuve["priorite"], 1),
                              "categorie": max(1, POIDS_PRIORITE.get(preuve["priorite"], 1) - 1),
                              "organe": 1}
                    fiche["score"] += _bonus.get(genre or "organe", 1)
                    fiche["priorite"] = preuve["priorite"]
                    fiche["preuve"] = genre
                    fiche["preuve_roadmap"] = preuve["texte"][:170]
                    alignes.append(fiche)
                else:
                    hors.append(fiche)

    sans_mesure = [
        {"cle": i["cle"], "priorite": i["priorite"], "texte": i["texte"][:170]}
        for i in items if i["cle"] not in reclames
    ]
    # Preuve nommee AVANT preuve d'organe, a score egal : une justification qui cite
    # le module vaut plus qu'une qui cite sa famille.
    _rang = {"nommee": 0, "categorie": 1, "organe": 2}
    alignes.sort(key=lambda d: (_rang.get(d.get("preuve"), 3), -d["score"]))
    hors.sort(key=lambda d: -d["score"])
    sans_mesure.sort(key=lambda d: -POIDS_PRIORITE.get(d["priorite"], 0))
    return {"etat": "ok", "alignes": alignes, "hors_direction": hors,
            "sans_mesure": sans_mesure, "totaux": gaps["totaux"],
            "roadmap_items": len(items), "roadmap_faits_zone": road["n_total"]}


def point() -> dict:
    """Entree PUBLIQUE : l'ecart entre ce que le corps sait de lui et la direction voulue.

    Elle existe parce que ce module avait ZERO appelant (mesure 2026-07-30) : un
    outil que seul un client lance a la main n'est pas de l'auto-amelioration, c'est
    de l'amelioration par un client. Composer `_gaps()` et `_roadmap()` depuis le
    dehors obligeait a toucher des fonctions privees, ce qu'aucune boucle ne doit
    faire. Consommateur cable : `forge_autonomous_loops.pat_self_improvement`.
    """
    return croiser(_gaps(), _roadmap())


def main() -> int:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            print(f"[gap] reconfigure ignore: {type(e).__name__}", file=sys.stderr)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=6)
    args = ap.parse_args()

    r = croiser(_gaps(), _roadmap())
    if args.json:
        print(json.dumps(r, indent=1, ensure_ascii=False))
        return 0
    if r.get("etat") != "ok":
        print("[gap] ILLISIBLE — ce n'est PAS « aucun ecart » :")
        print(f"   gaps    : {r.get('gaps')}")
        print(f"   roadmap : {r.get('roadmap')}")
        return 1

    t = r["totaux"]
    print(f"[gap] {t.get('modules_audited')} modules audites | "
          f"{t.get('silent_death_total')} morts silencieuses | "
          f"{t.get('dead_zone_total')} zones mortes | "
          f"{r['roadmap_items']}/{r['roadmap_faits_zone']} faits au format roadmap")

    # La REPARTITION des preuves compte autant que le total : 77 « alignes » dont 75
    # par une seule phrase fourre-tout ne priorisent rien. Mesure 2026-07-30 : c'est
    # le premier constat de cet outil, et il porte sur la ROADMAP, pas sur le code.
    _par_preuve: dict[str, int] = {}
    for a in r["alignes"]:
        _par_preuve[a.get("preuve") or "?"] = _par_preuve.get(a.get("preuve") or "?", 0) + 1
    _nom = _par_preuve.get("nommee", 0)
    print(f"\n=== 1. ALIGNE — mesure ET reclame ({len(r['alignes'])}) : le travail ===")
    print(f"    preuves : {_par_preuve}")
    if len(r["alignes"]) and _nom * 4 < len(r["alignes"]):
        print(f"    LECTURE : seuls {_nom} defauts sont reclames NOMMEMENT ; les autres")
        print("    ne tiennent qu'a une formule generique, qui ne hierarchise rien.")
        print("    Le defaut est alors dans la ROADMAP, trop grossiere pour prioriser :")
        print("    un fait par sujet (prefixe CURRENT/NEXT/P0) la rendrait actionnable.")
    for a in r["alignes"][:args.top]:
        marque = {"nommee": "", "categorie": "  [preuve de CATEGORIE]",
                  "organe": "  [preuve d'ORGANE, faible]"}.get(a.get("preuve"), "")
        print(f"\n  [{a.get('priorite')}] {a['module']}  ({a['nature']}, "
              f"organe: {a['organe']}){marque}")
        print(f"     roadmap: {a['preuve_roadmap']}")
    if len(r["alignes"]) > args.top:
        print(f"\n  ... {len(r['alignes']) - args.top} autres (--top N)")

    print(f"\n=== 2. HORS DIRECTION ({len(r['hors_direction'])}) : differe CONSCIEMMENT ===")
    for h in r["hors_direction"][:5]:
        print(f"   {h['module']:<40} {h['nature']:<13} {h['organe'][:30]}")
    if len(r["hors_direction"]) > 5:
        print(f"   ... {len(r['hors_direction']) - 5} autres")

    print(f"\n=== 3. SANS MESURE ({len(r['sans_mesure'])}) : roadmap sans appui reel ===")
    print("    soit c'est fait, soit personne ne le mesure — a trancher, pas a garder")
    for s in r["sans_mesure"][:args.top]:
        print(f"   [{s['priorite']}] {s['texte']}")
    if len(r["sans_mesure"]) > args.top:
        print(f"   ... {len(r['sans_mesure']) - args.top} autres")
    print("\n  Rappel : une `dead_zone` ne s'efface JAMAIS sur ce signal — le capteur "
          "ne voit ni les taches planifiees ni les lanceurs de boot du profil owner.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
