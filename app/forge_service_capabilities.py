# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ : proprioception / SSoT (organe, READ-ONLY)

ORGANE : QUE PORTE CE SERVICE ? — la source qui manquait.

Trou constate le 2026-07-24, apres degat : rien dans Nokido ne disait quelle
CAPACITE un service porte. Consequence directe — une eviction jugee `safe` a
endormi NokidoQdrantServer, NokidoLlamaEmbed et NokidoLlamaReranker, soit les trois
piliers du RAG, parce que :
  - `forge_body_world_model.predict_impact` ne voit que les dependances DECLAREES
    de services.toml (ordre de demarrage), pas ce qu'un service SERT ;
  - le filtre « porteur de modele rechargeable » les autorisait, puisque ce sont
    tous des llama-server.
Deux heuristiques justes separement, fausses ensemble — faute d'une troisieme source.

C'est aussi le meme trou que le « keeper aveugle » de juillet : identifier par NOM
ou par PORT rate tout ce qui n'a pas ete prevu a l'ecriture.

PRINCIPE : une capacite se DECLARE, elle ne se devine pas. Le champ `capabilities`
de `services.toml` fait foi. La table de repli ci-dessous ne couvre que les organes
dont la perte est deja MESUREE comme couteuse — elle n'invente rien, elle consigne.

STRICTEMENT READ-ONLY.

CLI :
    LAFORGE_PYTHON app/forge_service_capabilities.py --list
    LAFORGE_PYTHON app/forge_service_capabilities.py --check NokidoLlamaEmbed
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICES_TOML = ROOT / "proxy_deno" / "core" / "services.toml"

# Capacites dont la perte casse une chaine fonctionnelle entiere. Chacune est ici
# parce qu'un incident l'a demontre, pas par precaution theorique.
CRITIQUES = {
    "embedding",      # sans elle : plus d'ingestion ni de recherche dense
    "dense_search",   # sans elle : le RAG retombe en BM25 seul
    "reranking",      # sans elle : la qualite de retrieval s'effondre
    "hub",            # sans lui : plus aucun outil
    "supervisor",     # sans lui : plus de cycle de vie
    "nervous_system", # sans lui : plus de bus evenementiel inter-organes
}

# REPLI, uniquement pour les organes dont la perte a ete MESUREE le 24-07.
# A vider a mesure que `capabilities` est renseigne dans services.toml.
_REPLI = {
    "NokidoLlamaEmbed":     ["embedding"],
    "NokidoQdrantServer":   ["dense_search"],
    "NokidoQdrantSidecar":  ["dense_search"],
    "NokidoLlamaReranker":  ["reranking"],
    "NokidoMCP":           ["hub"],
}

_CACHE: dict[str, list[str]] | None = None


def _declared() -> dict[str, list[str]]:
    """{service: [capacites]} lu dans services.toml (champ `capabilities`)."""
    out: dict[str, list[str]] = {}
    try:
        txt = SERVICES_TOML.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for bloc in txt.split("[[service]]")[1:]:
        m = re.search(r'name\s*=\s*"([^"]+)"', bloc)
        if not m:
            continue
        caps = re.search(r'^\s*capabilities\s*=\s*\[([^\]]*)\]', bloc, re.M)
        if caps:
            vals = [v.strip().strip('"\'') for v in caps.group(1).split(",")]
            out[m.group(1)] = [v for v in vals if v]
    return out


def capabilities_of(service: str) -> list[str]:
    """Capacites portees par un service. Declaration d'abord, repli ensuite."""
    global _CACHE
    if _CACHE is None:
        _CACHE = _declared()
    if service in _CACHE:
        return _CACHE[service]
    return list(_REPLI.get(service, []))


def is_critical(service: str) -> bool:
    """Ce service porte-t-il une capacite dont la perte casse une chaine ?"""
    return bool(set(capabilities_of(service)) & CRITIQUES)


def why_critical(service: str) -> str:
    """Phrase lisible pour un journal ou un refus — un garde muet ne s'explique pas."""
    caps = sorted(set(capabilities_of(service)) & CRITIQUES)
    if not caps:
        return ""
    return f"{service} porte {', '.join(caps)} — capacite critique, ne pas evincer"


# ─────────────────────── CONTRAT : intention + objectif ──────────────────────
# Pourquoi ce contrat existe (audit owner du 2026-08-25). Le vocabulaire d'intention
# du corps tenait en CINQ drapeaux (`docker/llama/lmstudio/rerank/embed.wanted`) pour
# 85 services declares, et ces drapeaux sont poses par le CONSOMMATEUR au moment ou il
# ECHOUE, avec un TTL de 900 s que rien ne renouvelle. Mesure du jour : `embed.wanted`
# perime depuis 27 min et les deux piliers RAG a l'arret. Autrement dit l'intention
# etait un signal de DETRESSE a posteriori, pas une declaration de DEPENDANCE — d'ou
# une regulation qui ne coupe pas « ce qui ne sert pas » mais « ce que le seuil RAM
# attrape au passage ».
#
# Un contrat repond a deux questions, et il doit etre EVALUABLE, sinon il ne vaut pas
# mieux que l'impression qu'il remplace :
#   intention : POURQUOI ce service tourne ;
#   objectif  : quelle SORTIE MESURABLE prouve qu'il tient son role, avec un seuil.
#
# CHOIX DE CONCEPTION : le contrat est DERIVE des declarations existantes quand elles
# suffisent, et n'a besoin d'etre ecrit a la main que la ou rien ne permet de le
# deduire. Ecrire 85 contrats a la main produirait 85 occasions de se tromper, et la
# plupart des services declarent DEJA de quoi le deduire (essential / capabilities /
# heartbeat). Le champ explicite reste prioritaire : il sert aux cas que la derivation
# ne couvre pas, et a resserrer un seuil trop permissif.
#
# GRAMMAIRE de `objectif` — volontairement minuscule, chaque terme mesurable :
#   hb<N     heartbeat plus jeune que N secondes
#   emis<N   derniere emission de l'organe dans la moelle afferente, en secondes
#   cpu>P    part CPU moyenne depuis le demarrage superieure a P pour cent
#   conn>N   au moins N connexions etablies
#   listen   ecoute au moins un port
#   actes>N  au moins N actes de regulation le visant sur 7 jours
#   aucun    AUCUNE sortie mesurable — a DECLARER, jamais a omettre
# Plusieurs termes se separent par `|` et valent OU : une seule preuve suffit.
#
# NATURE DE LA PREUVE — correction owner du 2026-08-25 : « le signal de vie devrait
# EMANER de l'organe ». La premiere version de ce contrat comptait `hb<` et `cpu>` de
# la meme facon, ce qui est faux et masque le defaut le plus interessant :
#   AFFERENT   le signal est EMIS par l'organe lui-meme (heartbeat, moelle des traces).
#              L'organe temoigne, et il peut dire CE QU'IL A FAIT.
#   PALPATION  le signal est INFERE du dehors (psutil, netstat). L'observateur prend
#              le pouls. Ca ne dit jamais que « ca consomme », jamais ce qui est fait.
# Un organe qui ne satisfait son contrat QUE par palpation n'est pas sain : il est
# DENERVE. Il ne doit pas echouer — il fonctionne — mais il doit etre NOMME, sinon la
# palpation lui delivre un satisfecit qui dispense de l'innerver. Mesure du jour :
# 40 services declares sur 85 n'ont aucun heartbeat, et la moelle afferente
# (`forge_trace_spine`) est sous contrat pour 11 producteurs mais n'ingere rien.
_NATURE = {"hb": "AFFERENT", "emis": "AFFERENT",
           "cpu": "PALPATION", "conn": "PALPATION", "listen": "PALPATION",
           "actes": "PALPATION"}   # `actes` = ce que la REGULATION dit de lui, pas lui
_TIERS_S = {"slow": 1800.0, "normal": 900.0, "fast": 300.0}


def nature_de(terme: str) -> str:
    """AFFERENT (l'organe emet) | PALPATION (on l'infere du dehors) | INCONNUE."""
    m = re.match(r"^\s*(hb|emis|cpu|conn|actes|listen)\b", terme or "")
    return _NATURE.get(m.group(1), "INCONNUE") if m else "INCONNUE"


def _blocs() -> dict:
    """Toutes les declarations utiles, par service. Lecture unique, tolerante."""
    out: dict[str, dict] = {}
    try:
        txt = SERVICES_TOML.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for bloc in txt.split("[[service]]")[1:]:
        m = re.search(r'name\s*=\s*"([^"]+)"', bloc)
        if not m:
            continue

        def _s(champ):
            g = re.search(r'^\s*%s\s*=\s*"([^"]*)"' % champ, bloc, re.M)
            return g.group(1) if g else None

        caps = re.search(r'^\s*capabilities\s*=\s*\[([^\]]*)\]', bloc, re.M)
        out[m.group(1)] = {
            "capabilities": [v.strip().strip('"\'') for v in caps.group(1).split(",")
                             if v.strip()] if caps else [],
            "essential": bool(re.search(r'^\s*essential\s*=\s*true', bloc, re.M)),
            "heartbeat": _s("heartbeat"),
            "heartbeat_tier": _s("heartbeat_tier"),
            "intention": _s("intention"),
            "objectif": _s("objectif"),
        }
    return out


def contrat_de(service: str) -> dict:
    """{intention, objectif, source} — source = declare | derive | ABSENT.

    `ABSENT` n'est pas un defaut de l'outil : c'est un service dont RIEN ne dit
    pourquoi il tourne. C'est precisement la liste a remplir a la main.
    """
    b = _blocs().get(service)
    if b is None:
        return {"intention": None, "objectif": None, "source": "ABSENT",
                "pourquoi": "service inconnu de services.toml"}
    if b["intention"] or b["objectif"]:
        return {"intention": b["intention"] or "declare",
                "objectif": b["objectif"] or "aucun", "source": "declare"}
    if b["essential"]:
        return {"intention": "essential", "objectif": "listen | conn>0 | cpu>0.05",
                "source": "derive"}
    if b["capabilities"]:
        return {"intention": "capability:" + ",".join(b["capabilities"]),
                "objectif": "cpu>0.05 | conn>0 | listen", "source": "derive"}
    if b["heartbeat"]:
        # Seuil DELIBEREMENT permissif : un contrat derive ne doit jamais accuser a
        # tort. Inventer une derive coute plus cher que d'en rater une — resserrer se
        # fait en declarant `objectif` explicitement.
        return {"intention": "daemon",
                "objectif": "hb<%d" % int(_TIERS_S.get(b["heartbeat_tier"] or "", 1800.0)),
                "source": "derive"}
    return {"intention": None, "objectif": None, "source": "ABSENT",
            "pourquoi": "ni essential, ni capabilities, ni heartbeat declares"}


def evaluer_objectif(objectif: str, mesures: dict) -> tuple:
    """(etat, detail, nature) avec etat ∈ atteint | manque | illisible | sans_objet.

    `nature` qualifie la PREUVE retenue : AFFERENT si l'organe a temoigne lui-meme,
    PALPATION si on l'a seulement inferee du dehors. Un `atteint` par palpation seule
    n'est pas un blanc-seing : c'est un organe qui fonctionne SANS INNERVATION, et le
    dire est le seul moyen que ca se repare un jour.

    `mesures` accepte hb_s, cpu_pct, conn, listen, actes — une valeur None y signifie
    ILLISIBLE et non zero. Un terme dont la mesure manque ne peut ni etre atteint ni
    etre manque : il rend `illisible`, et un objectif dont TOUS les termes sont
    illisibles n'autorise aucun verdict.
    """
    if not objectif or objectif.strip() == "aucun":
        return "sans_objet", "aucune sortie mesurable declaree", "INCONNUE"
    illisibles, echecs = [], []
    # Les termes AFFERENTS sont eprouves EN PREMIER : le temoignage de l'organe prime
    # sur la palpation, sans quoi l'ordre d'ecriture dans services.toml deciderait de
    # la nature de la preuve — un detail de redaction ne doit pas trancher ca.
    termes = [t.strip() for t in objectif.split("|") if t.strip()]
    termes.sort(key=lambda t: 0 if nature_de(t) == "AFFERENT" else 1)
    for terme in termes:
        nat = nature_de(terme)
        try:
            if terme == "listen":
                v = mesures.get("listen")
                if v is None:
                    illisibles.append(terme)
                elif v:
                    return "atteint", "ecoute un port", nat
                else:
                    echecs.append(terme)
                continue
            m = re.match(r"^(hb|emis|cpu|conn|actes)\s*([<>])\s*([0-9.]+)$", terme)
            if not m:
                illisibles.append(terme + " (grammaire inconnue)")
                continue
            cle = {"hb": "hb_s", "emis": "emis_s", "cpu": "cpu_pct",
                   "conn": "conn", "actes": "actes"}[m.group(1)]
            v = mesures.get(cle)
            if v is None:
                illisibles.append(terme)
                continue
            seuil = float(m.group(3))
            ok = (float(v) < seuil) if m.group(2) == "<" else (float(v) > seuil)
            if ok:
                return "atteint", "%s (mesure %.3g)" % (terme, float(v)), nat
            echecs.append("%s (mesure %.3g)" % (terme, float(v)))
        except Exception:  # noqa: BLE001 - muet-ok : terme compte en ILLISIBLE juste apres
            illisibles.append(terme)
    if echecs:
        return "manque", "aucun terme atteint : " + " ; ".join(echecs), "INCONNUE"
    return "illisible", "aucun terme mesurable : " + " ; ".join(illisibles), "INCONNUE"


def innerve(service: str) -> bool:
    """L'organe EMET-il un signal de vie, ou ne peut-on que le palper ?

    Un service sans aucun terme afferent dans son contrat est DENERVE : rien de ce
    qu'il produit ne remonte de lui-meme. Ce n'est pas une panne, c'est une absence
    de nerf — et c'est reparable en lui declarant un heartbeat ou en le raccordant a
    la moelle des traces.
    """
    obj = contrat_de(service).get("objectif") or ""
    return any(nature_de(t) == "AFFERENT" for t in obj.split("|"))


def contrats_manquants() -> list:
    """Services dont RIEN ne dit pourquoi ils tournent. La liste a remplir."""
    return sorted(s for s in _blocs() if contrat_de(s)["source"] == "ABSENT")


def audit() -> dict:
    """Etat de la declaration : ce qui est couvert, ce qui repose encore sur le repli."""
    decl = _declared()
    blocs = _blocs()
    src = {}
    for s in blocs:
        src.setdefault(contrat_de(s)["source"], []).append(s)
    return {
        "declares_dans_services_toml": sorted(decl),
        "encore_sur_repli": sorted(s for s in _REPLI if s not in decl),
        "capacites_critiques": sorted(CRITIQUES),
        "contrats": {k: len(v) for k, v in src.items()},
        "contrats_ABSENTS": sorted(src.get("ABSENT", [])),
    }


def _main() -> int:
    ap = argparse.ArgumentParser(description="Capacites portees par les services")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--check")
    a = ap.parse_args()
    if a.check:
        print(json.dumps({
            "service": a.check,
            "capabilities": capabilities_of(a.check),
            "critique": is_critical(a.check),
            "raison": why_critical(a.check),
        }, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(audit(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
