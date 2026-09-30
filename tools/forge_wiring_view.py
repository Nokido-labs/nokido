#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_wiring_view.py — VUE FEDEREE du cablage. N'INVENTE AUCUNE ARETE.

__FORGE_COLOR__ = "observabilite/trace : vue federee des instruments de cablage"

POURQUOI (2026-09-07). Nokido possede DEJA plusieurs instruments qui repondent chacun
a une tranche de la question « comment ce module est-il reellement atteint ? » :

    forge_module_census           organe            1665 modules, 0 non classe
    forge_body_regulation_audit   regulation        REGULE/CABLE/INVOQUE/ZONE_MORTE...
    forge_module_wiring           cablage           voies : import, citation,
                                                    declaration, point d'entree
    forge_signal_atlas            signal            emetteur -> consommateur

Ce qui manquait n'etait pas un instrument de plus -- c'etait une VUE. Mesure du jour,
deux d'entre eux se CONTREDISENT sur le meme module :

    regulation_audit : forge_roles_legacy  INVOQUE, cite par 2 fichiers
    module_wiring    : forge_roles_legacy  ORPHELIN, aucune voie

Un vote entre les deux effacerait l'information. L'ecart EST le renseignement.

## CE QUE CETTE VUE NE FAIT PAS, ET C'EST L'ESSENTIEL

  * elle ne LANCE aucun instrument -- `forge_body_regulation_audit` ingere meme sans
    argument (cache + RAG reecrits), on ne le declenche pas au passage ;
  * elle ne CREE aucune arete : chaque arete rendue provient telle quelle d'une source
    nommee, avec sa date d'observation ;
  * elle ne rend AUCUN verdict. Il n'existe volontairement aucune fonction qui
    arbitre un desaccord. Les heuristiques choisissent ou regarder ; seuls les
    instruments de certification decident de ce qui est vrai.

## TROIS TROUS, JAMAIS CONFONDUS

    ABSENT       la source a regarde, aucune arete
    ILLISIBLE    artefact manquant / illisible : on n'a PAS PU regarder
    NON_COUVERT  le module est hors du perimetre de cette source

Confondre les trois est la faute qui a coute la nuit du 2026-09-07 : « 0 importeur »
lu comme « mort » alors que le module etait INVOQUE par 14 fichiers.

## AUTORITE

Chaque arete porte `authority: false`. Une vue federee accelere l'exploration ; elle
ne certifie rien. Un selecteur incomplet peut reduire le TEMPS de recherche, jamais le
PERIMETRE DE VERITE.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

# Chaque source declare son artefact, son producteur (pour pouvoir DIRE quoi relancer
# quand il manque) et l'axe qu'elle couvre. On ne lit QUE des artefacts deja produits.
SOURCES: dict[str, dict] = {
    "module_wiring": {
        "artefact": "sandbox/module_wiring.json",
        "producteur": "tools/forge_module_wiring.py --orphelins",
        "axe": "cablage : import, citation, declaration, point d'entree",
    },
    "regulation": {
        "artefact": "sandbox/workspace/module_cards.json",
        "producteur": "tools/forge_body_regulation_audit.py (ATTENTION : ingere)",
        "axe": "regulation : REGULE / SUPERVISE / CABLE / INVOQUE / OUTIL / ZONE_MORTE",
    },
    "census": {
        "artefact": "sandbox/workspace/module_cards.json",
        "producteur": "tools/forge_module_census.py",
        "axe": "organe",
    },
}

# Un module que `module_wiring` dit ORPHELIN et que la regulation dit atteint : c'est
# le desaccord qu'on veut voir, pas trancher.
_ATTEINT = {"REGULE", "SUPERVISE", "CABLE", "INVOQUE", "OUTIL"}


def _cle(chemin: str) -> str:
    """Clef = CHEMIN relatif, jamais le nom de base.

    `app/Nokido.py` et `tools/nokido.py` sont deux modules distincts que le systeme de
    fichiers Windows confond ; keyer sur le basename les fusionnerait en silence
    (piege paye le 2026-09-06 sur le census)."""
    return str(chemin).replace("\\", "/").lstrip("./")


def _lire(rel: str) -> tuple:
    """(donnee, etat, motif, observe_le). Trois etats, jamais deux.

    Un artefact absent rend ILLISIBLE et NON une donnee vide : « je n'ai pas pu
    regarder » ne se lit jamais « il n'y a rien »."""
    p = RACINE / rel
    if not p.is_file():
        return None, "ILLISIBLE", "artefact absent : %s" % rel, None
    try:
        brut = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001 - l'echec est NOMME, jamais avale
        return None, "ILLISIBLE", "%s: %s" % (type(e).__name__, str(e)[:90]), None
    return brut, "LU", "", p.stat().st_mtime


def sources() -> dict:
    """Etat de chaque source : lue ou non, date, taille du perimetre."""
    out = {}
    cache: dict[str, tuple] = {}
    for nom, meta in SOURCES.items():
        rel = meta["artefact"]
        if rel not in cache:
            cache[rel] = _lire(rel)
        brut, etat, motif, ts = cache[rel]
        fiche = {"axe": meta["axe"], "artefact": rel, "producteur": meta["producteur"],
                 "etat": etat, "motif": motif, "observe_le": ts,
                 "age_jours": None if ts is None else round((time.time() - ts) / 86400.0, 2)}
        fiche["perimetre"] = len(_perimetre(nom, brut)) if brut is not None else None
        out[nom] = fiche
    return out


def _perimetre(nom: str, brut) -> dict:
    """{cle: fiche brute} pour une source. Aucune transformation de sens."""
    if brut is None:
        return {}
    if nom == "module_wiring":
        return {_cle(f.get("chemin", f.get("module", ""))): f
                for f in brut.get("fiches", []) if isinstance(f, dict)}
    if nom in ("regulation", "census"):
        return {_cle(k): v for k, v in brut.items() if isinstance(v, dict)}
    return {}


def couverture() -> dict:
    """Perimetre OBSERVE de chaque source : repertoires et extensions reellement vus.

    DERIVE de l'artefact, jamais declare a la main -- une couverture annoncee est une
    intention, pas une mesure. Sert a distinguer deux silences que rien ne separait :

        la source couvre cette couche, et n'a pas vu CE fichier   -> ABSENT
        la source ne couvre pas cette couche du tout              -> NON_COUVERT

    Payé le 2026-09-07 : j'ai conclu « Nokido ne cartographie pas le TypeScript » du
    seul fait que le census lit du `.py`. Or `forge_body_regulation_audit` scanne cinq
    repertoires et huit extensions, resout les imports JS/TS et PowerShell, et le dit
    lui-meme depuis juillet : « un capteur aveugle a 7 de ses 8 extensions accuse de
    mort ce qu'il ne sait pas lire ». Une observation LOCALE ne se generalise pas au
    systeme entier.
    """
    out = {}
    cache: dict[str, tuple] = {}
    for nom, meta in SOURCES.items():
        rel = meta["artefact"]
        if rel not in cache:
            cache[rel] = _lire(rel)
        brut, etat, motif, ts = cache[rel]
        if etat != "LU":
            out[nom] = {"etat": "ILLISIBLE", "motif": motif,
                        "dossiers": None, "extensions": None, "n": None}
            continue
        per = _perimetre(nom, brut)
        dossiers = sorted({k.split("/")[0] for k in per if "/" in k})
        exts = sorted({os.path.splitext(k)[1].lower() for k in per if os.path.splitext(k)[1]})
        out[nom] = {"etat": "LU", "motif": "", "dossiers": dossiers,
                    "extensions": exts, "n": len(per), "observe_le": ts}
    return out


def _couvre(cov: dict, cle: str) -> bool:
    """Cette source couvre-t-elle la COUCHE de ce fichier (dossier + extension) ?"""
    if cov.get("etat") != "LU":
        return False
    d = cle.split("/")[0] if "/" in cle else ""
    e = os.path.splitext(cle)[1].lower()
    return d in (cov.get("dossiers") or []) and e in (cov.get("extensions") or [])


def _aretes_de(nom: str, fiche: dict, observe_le) -> list:
    """Les aretes que CETTE source declare. Recopiees, jamais deduites."""
    a = []
    if nom == "module_wiring":
        for voie in fiche.get("voies") or []:
            a.append({"type": "voie", "detail": voie})
        if not a:
            a.append({"type": "aucune", "detail": "ORPHELIN selon cette source"})
    elif nom == "regulation":
        r = fiche.get("regulation")
        if r is None:
            return []          # pas d'arete DU TOUT : le champ manque, cf NON_COUVERT
        a.append({"type": "regulation", "detail": "%s — %s"
                  % (r, fiche.get("regulation_why", ""))})
    elif nom == "census":
        o = fiche.get("organ")
        if o is None:
            return []
        a.append({"type": "organe", "detail": str(o)})
    for x in a:
        x["source"] = nom
        x["observe_le"] = observe_le
        x["authority"] = False     # une vue federee ne certifie RIEN
    return a


def module(cible: str) -> dict:
    """Toutes les aretes connues d'un module, par source, avec provenance.

    Rend aussi, pour chaque source, POURQUOI elle ne dit rien : ABSENT (elle a
    regarde), ILLISIBLE (on n'a pas pu la lire) ou NON_COUVERT (hors perimetre)."""
    cible_n = _cle(cible)
    res = {"module": cible_n, "aretes": [], "silences": {}}
    cache: dict[str, tuple] = {}
    _couv: dict[str, dict] = {}
    for nom, meta in SOURCES.items():
        rel = meta["artefact"]
        if rel not in cache:
            cache[rel] = _lire(rel)
        brut, etat, motif, ts = cache[rel]
        if etat != "LU":
            res["silences"][nom] = {"etat": "ILLISIBLE", "motif": motif}
            continue
        per = _perimetre(nom, brut)
        fiche = per.get(cible_n)
        if fiche is None:
            fiche = next((v for k, v in per.items()
                          if os.path.basename(k) == os.path.basename(cible_n)), None)
        if fiche is None:
            # ABSENT et NON_COUVERT ne se confondent pas : la source a-t-elle seulement
            # les yeux pour cette couche ? Le perimetre est DERIVE de son artefact.
            cov = _couv.get(nom) or couverture().get(nom, {})
            _couv[nom] = cov
            if _couvre(cov, cible_n):
                res["silences"][nom] = {
                    "etat": "ABSENT",
                    "motif": "couche couverte (%s, %s) mais ce fichier n'y figure pas"
                             % ("/".join(cov.get("dossiers") or [])[:40],
                                " ".join(cov.get("extensions") or [])[:40])}
            else:
                res["silences"][nom] = {
                    "etat": "NON_COUVERT",
                    "motif": "cette source ne couvre pas la couche de %s" % cible_n}
            continue
        ar = _aretes_de(nom, fiche, ts)
        if not ar:
            res["silences"][nom] = {"etat": "NON_COUVERT",
                                    "motif": "fiche presente mais champ de cette source absent"}
        res["aretes"].extend(ar)
    return res


def certification(nom: str = "module_wiring") -> dict:
    """TRANSPORTE le statut declare par la source. Ne le RECALCULE jamais.

    Un statut qui se reconstitue a l'agregation ne veut plus rien dire : la vue
    n'a aucun moyen de savoir ce que la source sait d'elle-meme. Elle relaie, ou
    elle dit qu'elle ne sait pas.

    ⚠️ Chaque repli rend `authority: False`. **Une absence de declaration n'est pas
    une autorisation** -- c'est le meme piege que `routable` absent lu comme routable,
    et que `score absent` lu comme score nul.
    """
    src = SOURCES.get(nom)
    if not src:
        return {"statut": "ILLISIBLE", "authority": False,
                "motif": "source inconnue : %s" % nom}
    brut, etat, motif, ts = _lire(src["artefact"])
    if etat != "LU":
        return {"statut": "ILLISIBLE", "authority": False,
                "motif": motif, "observe_le": ts}
    c = (brut or {}).get("certification")
    if not isinstance(c, dict) or "statut" not in c:
        return {"statut": "ILLISIBLE", "authority": False, "observe_le": ts,
                "motif": "la source ne declare aucun statut de certification"}
    out = dict(c)
    out["observe_le"] = ts
    out["transporte_depuis"] = src["artefact"]
    return out


def _apparier(regul: dict, cle: str) -> tuple:
    """Retrouver dans une AUTRE source la fiche du MEME fichier. (fiche, comment).

    ⚠️ Le rapprochement par basename est le defaut meme qu'on vient de corriger dans
    `forge_module_wiring` le 2026-09-07 : `agents/core.py` et `netcfg/core.py` partagent
    un basename et sont deux organes distincts. Apparier deux sources par le nom, c'est
    reintroduire la fusion au moment de la JOINTURE, apres l'avoir chassee du capteur.

    Le chemin exact prime. Le basename n'est accepte QUE s'il designe UNE SEULE fiche
    en face ; sinon on ABSTIENT, en le disant. Une jointure ambigue ne se tranche pas
    au premier rencontre."""
    if cle in regul:
        return regul[cle], "chemin"
    b = os.path.basename(cle)
    cands = [k for k in regul if os.path.basename(k) == b]
    if len(cands) == 1:
        return regul[cands[0]], "basename unique"
    if len(cands) > 1:
        return None, "basename AMBIGU en face (%d fiches) : %s" % (
            len(cands), ", ".join(sorted(cands)[:4]))
    return None, "absent de cette source"


def abstentions() -> list:
    """Modules ou `module_wiring` REFUSE de temoigner (AMBIGU) alors que la regulation
    les dit atteints. Ce n'est PAS un desaccord : une source qui s'abstient ne contredit
    personne. Mais un silence qu'on ne compte pas se relit comme une absence d'arete --
    d'ou cette liste separee, plutot qu'un filtre muet dans `desaccords()`."""
    bw, ew, _mw, tw = _lire(SOURCES["module_wiring"]["artefact"])
    br, er, _mr, tr = _lire(SOURCES["regulation"]["artefact"])
    if ew != "LU" or er != "LU":
        return []
    wiring, regul = _perimetre("module_wiring", bw), _perimetre("regulation", br)
    out = []
    for cle, f in wiring.items():
        if f.get("etat") != "AMBIGU":
            continue
        g, comment = _apparier(regul, cle)
        out.append({
            "module": cle,
            "module_wiring": {"etat": "AMBIGU", "source": "module_wiring",
                              "ambiguite": f.get("ambiguite") or {},
                              # Trois etats : False = NON ROUTABLE, True = routable,
                              # None = la source ne le dit pas (artefact ancien). Sans
                              # ce report, un selecteur de capacite lisant la VUE ne
                              # verrait pas l'interdiction que l'artefact porte.
                              "routable": f.get("routable"),
                              "observe_le": tw, "authority": False},
            "regulation": ({"etat": str(g.get("regulation") or ""), "source": "regulation",
                            "observe_le": tr, "authority": False} if g else None),
            "appariement": comment,
            "arbitrage": None,
        })
    return sorted(out, key=lambda x: x["module"])


def desaccords() -> list:
    """Modules sur lesquels deux sources se contredisent. ON NE TRANCHE PAS.

    Le seul desaccord detectable aujourd'hui : `module_wiring` dit ORPHELIN pendant que
    la regulation dit atteint (CABLE/INVOQUE/...). Il est REEL -- mesure du 2026-09-07
    sur `forge_roles_legacy` -- et c'est exactement ce qu'une vue doit montrer.

    `AMBIGU` n'entre PAS ici : une source qui s'abstient ne contredit rien. Voir
    `abstentions()`, qui les compte au lieu de les taire."""
    bw, ew, _mw, tw = _lire(SOURCES["module_wiring"]["artefact"])
    br, er, _mr, tr = _lire(SOURCES["regulation"]["artefact"])
    if ew != "LU" or er != "LU":
        return []
    wiring, regul = _perimetre("module_wiring", bw), _perimetre("regulation", br)
    out = []
    for cle, f in wiring.items():
        if f.get("etat") != "ORPHELIN":
            continue
        g, _comment = _apparier(regul, cle)
        if not g:
            continue
        r = str(g.get("regulation") or "")
        if r.split(" (")[0] in _ATTEINT:
            out.append({
                "module": cle,
                "module_wiring": {"etat": "ORPHELIN", "voies": f.get("voies") or [],
                                  "routable": f.get("routable"),
                                  "source": "module_wiring", "observe_le": tw,
                                  "authority": False},
                "regulation": {"etat": r, "pourquoi": g.get("regulation_why", ""),
                               "source": "regulation", "observe_le": tr,
                               "authority": False},
                "arbitrage": None,   # VOLONTAIRE : la vue ne tranche pas
            })
    return sorted(out, key=lambda x: x["module"])


def pourquoi(liste=None) -> list:
    """Classe la NATURE d'un desaccord. Jamais son vainqueur.

    Mesure 2026-09-07 sur les 72 premiers desaccords :

        70  regulation « cite par N (hook/config/script), sans import »  -> PERIMETRE_D_ARETE
         2  regulation « importe par N module(s) »                       -> CONFLIT_A_INSTRUIRE

    Les 70 ne sont PAS un conflit : la regulation compte les citations dans les hooks,
    configs et scripts, que `module_wiring` ne scanne pas. Deux perimetres d'ARETE
    differents, pas deux verites contradictoires. Compter 72 conflits aurait remplace
    un bazar de modules par un bazar de conflits.

    Les 2 en sont un, et ils tombent en sens OPPOSES -- verifie a la main le meme jour :
    `forge_code_ast` a bien 2 importeurs reels (la regulation a raison, wiring les
    rate) ; `forge_hw` n'en a aucun (wiring a raison, la regulation est perimee ou
    fausse). Aucun instrument n'est autoritaire, et l'arbitre improvise -- une regex --
    n'est qu'un TROISIEME observateur.

    `qui_a_raison` reste None par construction.
    """
    if liste is None:
        liste = desaccords()
    _c = couverture()
    ages = {n: c.get("observe_le") for n, c in _c.items() if c.get("etat") == "LU"}
    ecart_h = None
    if ages.get("module_wiring") and ages.get("regulation"):
        ecart_h = round(abs(ages["module_wiring"] - ages["regulation"]) / 3600.0, 1)
    out = []
    for x in liste:
        p = (x["regulation"]["pourquoi"] or "").lower()
        if "hook/config/script" in p or "sans import" in p:
            nature, motif = ("PERIMETRE_D_ARETE",
                             "la regulation compte une arete (hook/config/script) que "
                             "l'autre source ne scanne pas : perimetres differents")
        elif "importe par" in p:
            nature, motif = ("CONFLIT_A_INSTRUIRE",
                             "les DEUX scannent les imports et se contredisent : "
                             "conflit reel, ou donnee perimee")
        else:
            nature, motif = ("INDETERMINE", "motif de la regulation non reconnu : %r" % p[:60])
        out.append({**x, "nature": nature, "motif": motif,
                    "ecart_artefacts_h": ecart_h,   # candidat STALE, pas une conclusion
                    "qui_a_raison": None})          # VOLONTAIRE
    return out


def _main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="vue federee du cablage — n'invente aucune arete")
    ap.add_argument("--module", help="tout ce que les sources disent de ce module")
    ap.add_argument("--desaccords", action="store_true", help="ou les sources se contredisent")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.module:
        d = module(a.module)
        if a.json:
            print(json.dumps(d, ensure_ascii=False, indent=2))
            return 0
        print("== %s ==" % d["module"])
        for x in d["aretes"]:
            print("  [%-12s] %-11s %s" % (x["source"], x["type"], str(x["detail"])[:96]))
        for nom, s in d["silences"].items():
            print("  [%-12s] %-11s %s" % (nom, s["etat"], s["motif"][:88]))
        if not d["aretes"]:
            print("  (aucune arete RENDUE — lire les silences ci-dessus avant de conclure)")
        return 0

    if a.desaccords:
        d = pourquoi()
        abst = abstentions()
        cert = certification()
        if a.json:
            print(json.dumps({"certification": cert, "desaccords": d,
                              "abstentions": abst}, ensure_ascii=False, indent=2))
            return 0
        print("module_wiring : %s (authority=%s) — %s"
              % (cert.get("statut"), cert.get("authority"),
                 str(cert.get("motif") or "")[:88]))
        if cert.get("interdit_pour"):
            print("   interdit pour : %s" % ", ".join(cert["interdit_pour"]))
        if abst:
            print("abstentions de module_wiring : %d module(s) AMBIGU -- il ne dit NI "
                  "atteint NI orphelin" % len(abst))
            _appar = {}
            for x in abst:
                _appar[x["appariement"].split(" (")[0]] = _appar.get(
                    x["appariement"].split(" (")[0], 0) + 1
            for k in sorted(_appar):
                print("   appariement %-22s %d" % (k, _appar[k]))
        import collections as _c
        print("desaccords entre sources : %d (aucun n'est arbitre)" % len(d))
        for nat, n in _c.Counter(x["nature"] for x in d).most_common():
            print("   %-22s %d" % (nat, n))
        if d and d[0].get("ecart_artefacts_h") is not None:
            print("   ecart entre artefacts : %.1f h (candidat STALE, pas une conclusion)"
                  % d[0]["ecart_artefacts_h"])
        for x in d:
            if x["nature"] != "PERIMETRE_D_ARETE":
                print("  %-40s %-20s wiring=%-9s regulation=%s"
                      % (x["module"], x["nature"], x["module_wiring"]["etat"],
                         x["regulation"]["etat"]))
        return 0

    cov = couverture()
    for nom, s in sources().items():
        print("%-14s %-10s perimetre=%-6s age=%-7s %s"
              % (nom, s["etat"], s["perimetre"], s["age_jours"], s["axe"][:52]))
        c = cov.get(nom, {})
        if c.get("etat") == "LU":
            print("               couche OBSERVEE : %s | %s"
                  % ("/".join(c["dossiers"])[:46], " ".join(c["extensions"])[:46]))
        if s["etat"] != "LU":
            print("               -> %s | produire par : %s" % (s["motif"], s["producteur"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
