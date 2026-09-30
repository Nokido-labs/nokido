#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_temps_mort.py — DEFINITION CANONIQUE du temps mort d'un organe.

POURQUOI CE MODULE EXISTE (mesure du 2026-09-03)
================================================
Trois centres decidaient INDEPENDAMMENT de ce qu'est un organe mort, et 29 services
sur 36 recevaient des seuils differents selon qui les jugeait :

  supervisor.ts                      tiers fast/normal/slow -> 90 / 600 / 3600 s
  forge_organ_pulse                  max(600, intervalle x3), table codee en dur
  forge_sensor_fusion_probe          cadence x2, table relue par REGEX sur le code
                                     source de forge_organ_pulse

Les ecarts vont jusqu'a un facteur 108 -- `NokidoHebbian` etait juge mort a 600 s par
le superviseur quand la sentinelle lui accordait 64 800 s. C'est la cause CHIFFREE de
ses 765 relances. Et les ecarts s'INVERSENT : sur `NokidoSSoTMaintainer` et
`NokidoBiblioWorker`, c'est le superviseur qui est le plus laxiste, donc un organe
reellement mort y reste invisible plus longtemps qu'ailleurs.

Le diagnostic n'est donc pas « le superviseur est mal regle » mais AUCUN DES TROIS NE
SAIT CE QU'EST UN TEMPS MORT. Un organisme ne peut pas avoir plusieurs centres qui
definissent separement la mort d'un organe.

LE CONTRAT (arbitrage owner 2026-09-03)
=======================================
    services.toml   = VERITE      declare `cycle_s`, la duree du travail de l'organe
    ce module       = FORMULE     seuil_mort = max(PLANCHER_S, FACTEUR x cycle_s)
    generateur      = OUTIL       initialise les declarations, ne decide de rien
    test NR         = ARBITRE     verifie que les consommateurs CONVERGENT

`cycle_s` et non `cadence_s` : la cadence appartient au COEUR (`forge_cardiac_node`),
qui donne le rythme commun. Cette valeur-ci decrit tout autre chose -- combien de
temps l'organe met a faire son tour.

`heartbeat_tier` cesse d'etre un seuil de mort et redevient ce qu'il est : a quelle
FREQUENCE on regarde. Deux questions distinctes qu'un seul reglage confondait.

CE QUE CE MODULE NE FAIT PAS
============================
Il ne lit aucun etat vivant, n'interroge aucun service et ne decide d'aucune action.
Il repond a une question de contrat : « quel silence vaut mort, pour cet organe ». Qui
tue reste le superviseur ; qui qualifie reste la sentinelle.
"""
from __future__ import annotations

__FORGE_COLOR__ = "regulation/temps-mort"

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICES_TOML = ROOT / "proxy_deno" / "core" / "services.toml"

# PLANCHER ABSOLU -- et le mot compte. Ce n'est PAS un defaut : c'est la borne basse
# d'un seuil CALCULE. Un organe dont le cycle est connu et tres court ne descend pas
# sous 90 s, faute de quoi sa mort deviendrait detectable plus vite que le temps de
# reaction le plus court du corps. Un organe dont le cycle est INCONNU, lui, ne recoit
# aucun seuil de ce module : on ne lui en invente pas un.
#
#     cycle connu = 20 s    -> seuil = 90 s      (plancher)
#     cycle connu = 6 h     -> seuil = 18 h
#     cycle INCONNU         -> comportement historique, aucun seuil invente
#
# Confondre les deux ferait passer 24 services sur 36 de 600 s a 90 s d'un coup. La
# distinction est la seule chose qui separe ce module d'un incident.
PLANCHER_S = 90.0

# MARGE. Un organe n'est en retard qu'apres avoir MANQUE plusieurs battements : juger
# a un seul cycle ferait crier sur le moindre jitter. Trois est le choix des deux
# implementations les plus recentes ; l'ancienne marge x2 de `forge_sensor_fusion_probe`
# est abandonnee, non parce qu'elle etait fausse mais parce que DEUX marges valables
# valent moins qu'une seule partagee.
FACTEUR = 3.0

# Cycles CONNUS mais non encore declares au registre. Table de MIGRATION, vouee a
# disparaitre : chaque entree deplacee dans `services.toml` doit etre retiree d'ici.
# Elle existe pour que la bascule ne perde aucune connaissance acquise, pas pour
# devenir un second registre -- c'est exactement ce qu'etait `HB_INTERVAL_S`.
# MIGRATION DU 2026-09-03 : Hebbian, SkillCurator et LogRetention ont rejoint le
# registre (`cycle_s` declare dans services.toml, avec la preuve en commentaire) et
# sortent donc d'ici. Il ne reste que ce qui n'a pas encore de service declarant un
# heartbeat -- et le jour ou il en aura un, cette entree devra sortir aussi.
CYCLES_HERITES = {
    "NokidoMemoryConsolidator": 43200.0,
}


def seuil_mort(cycle_s, seuil_actuel=None) -> float:
    """La formule, et il n'y en a qu'une.

    UN CYCLE INCONNU NE CHANGE RIEN, et ce point a ete corrige sur mesure. La
    premiere version rendait le PLANCHER faute de cycle -- « le plus strict, donc
    celui qui ne cache pas une mort ». Le raisonnement est juste et la consequence
    etait desastreuse : 24 services sur 36 n'ont aucun cycle connu, ils seraient
    passes de 600 s a 90 s d'un coup, `NokidoMCP` -- le hub lui-meme -- inclus. La
    migration aurait declenche une vague de relances sur les deux tiers du corps.

    C'est la faute classique de l'armement d'un durcissement sur une base non
    mesuree. On ne durcit QUE ce qu'on connait : faute de cycle, on rend le seuil
    ACTUEL de l'organe (son tier), inchange, et le `rapport()` compte la dette au
    lieu de la faire payer au corps.

    Le PLANCHER, lui, borne les cycles CONNUS : il empeche qu'un cycle absurdement
    court rende une mort indetectable plus vite que le temps de reaction du corps.
    """
    if cycle_s is None:
        return PLANCHER_S if seuil_actuel is None else float(seuil_actuel)
    try:
        c = float(cycle_s)
    except (TypeError, ValueError):
        return PLANCHER_S if seuil_actuel is None else float(seuil_actuel)
    if c <= 0:
        return PLANCHER_S if seuil_actuel is None else float(seuil_actuel)
    return max(PLANCHER_S, FACTEUR * c)


def _blocs_services(texte: str):
    for bloc in texte.split("[[service]]")[1:]:
        m = re.search(r'name\s*=\s*"([^"]+)"', bloc)
        if m:
            yield m.group(1), bloc


def _champ_num(bloc: str, champ: str):
    """Valeur numerique d'un champ du bloc, ou None s'il est absent.

    UN SEUL lecteur pour tous les champs. La premiere version en avait ecrit un par
    champ -- deux fonctions identiques au nom pres, que le cliquet de duplication a
    (a juste titre) attrapees. Ecrire un module POUR dedupliquer une formule en y
    dupliquant son propre parseur est exactement le travers qu'il surveille.
    """
    m = re.search(r"^\s*%s\s*=\s*([0-9.]+)" % re.escape(champ), bloc, re.M)
    return float(m.group(1)) if m else None


def cycle_declare(bloc: str):
    """`cycle_s` tel qu'ECRIT dans le registre, ou None. Aucune deduction ici."""
    return _champ_num(bloc, "cycle_s")


def cycle_derive(bloc: str):
    """Cycle DEDUIT des arguments de lancement, quand l'organe l'y expose.

    C'est un secours de migration, pas une source : un argument de ligne de commande
    dit comment on lance un organe, pas ce qu'il est. Le registre doit finir par le
    declarer.
    """
    for motif in (r'"--interval"\s*,\s*"(\d+)"', r'"--watch"\s*,\s*"(\d+)"',
                  r'"--interval-s"\s*,\s*"(\d+)"'):
        m = re.search(motif, bloc)
        if m:
            return float(m.group(1))
    return None


def cycles(texte: str | None = None) -> dict:
    """{service: (cycle_s, source)} pour tout service declarant un heartbeat.

    TROIS SOURCES NOMMEES, jamais fondues : `declare` (le registre), `herite` (la
    table de migration), `derive` (les arguments de lancement). Et `None` quand
    aucune ne repond -- ce qui n'est pas « pas de cycle », mais « je ne sais pas »,
    et se traduit par le seuil le plus strict.
    """
    if texte is None:
        texte = SERVICES_TOML.read_text(encoding="utf-8", errors="replace")
    out: dict = {}
    for nom, bloc in _blocs_services(texte):
        if not re.search(r'^\s*heartbeat\s*=\s*"', bloc, re.M):
            continue
        if re.search(r"^\s*disabled\s*=\s*true", bloc, re.M):
            continue
        c = cycle_declare(bloc)
        if c is not None:
            out[nom] = (c, "declare")
            continue
        if nom in CYCLES_HERITES:
            out[nom] = (CYCLES_HERITES[nom], "herite")
            continue
        c = cycle_derive(bloc)
        out[nom] = (c, "derive") if c is not None else (None, "inconnu")
    return out


def seuils(texte: str | None = None, seuils_actuels: dict | None = None) -> dict:
    """{service: (seuil_s, cycle_s, source)} — ce que TOUS les consommateurs doivent
    lire, plutot que d'en recalculer chacun une version.

    `seuils_actuels` porte le seuil en vigueur par service (son tier). Il sert
    UNIQUEMENT aux cycles inconnus, pour que la migration ne durcisse personne a
    l'aveugle. Sans lui, ces services retombent sur le plancher -- ce qui est le bon
    defaut pour un appelant qui n'a pas de seuil courant a offrir, et le mauvais
    pour une bascule en production.
    """
    act = seuils_actuels or {}
    return {nom: (seuil_mort(c, act.get(nom)), c, src)
            for nom, (c, src) in cycles(texte).items()}


def max_declare(bloc: str):
    """`heartbeat_max_s` tel qu'ECRIT. C'est la valeur DERIVEE, materialisee dans le
    registre pour que le TypeScript la LISE au lieu de la recalculer -- sans quoi la
    formule existerait en deux exemplaires et divergerait, ce qui est precisement le
    defaut que ce module corrige."""
    return _champ_num(bloc, "heartbeat_max_s")


def temps_mort(service: str, seuil_actuel=None, texte: str | None = None) -> tuple:
    """(seuil_s, source) — L'API des consommateurs Python. Une seule autorite.

    Ordre : la valeur MATERIALISEE d'abord, car c'est celle que lit le TypeScript et
    qu'aucun consommateur ne doit voir differemment ; puis le cycle, dont elle
    derive ; puis rien du tout -- et `rien du tout` rend le seuil ACTUEL, jamais un
    seuil invente.
    """
    if texte is None:
        texte = SERVICES_TOML.read_text(encoding="utf-8", errors="replace")
    for nom, bloc in _blocs_services(texte):
        if nom != service:
            continue
        mx = max_declare(bloc)
        if mx is not None:
            return mx, "materialise"
        c = cycle_declare(bloc)
        if c is None and service in CYCLES_HERITES:
            c, src = CYCLES_HERITES[service], "herite"
        elif c is not None:
            src = "declare"
        else:
            c, src = cycle_derive(bloc), "derive"
        if c is not None:
            return seuil_mort(c), src
        break
    return (None if seuil_actuel is None else float(seuil_actuel)), "inconnu"


def incoherences(texte: str | None = None) -> list:
    """Violations du contrat, pour le test NR. Liste VIDE = contrat tenu.

    LE CONTRAT, et ses deux sens :

        cycle_s present  ->  heartbeat_max_s OBLIGATOIRE et egal a la formule
        cycle_s absent   ->  heartbeat_max_s ABSENT, comportement historique

    Le second sens est le plus important. Sans lui, quelqu'un ecrira dans six mois
    « pas de cycle connu ? va pour 90 secondes » -- et fera passer 24 services sur
    36 de 600 s a 90 s. Une valeur derivee qu'on peut modifier SEULE n'est plus une
    valeur derivee, c'est une seconde configuration.
    """
    if texte is None:
        texte = SERVICES_TOML.read_text(encoding="utf-8", errors="replace")
    out = []
    for nom, bloc in _blocs_services(texte):
        if not re.search(r'^\s*heartbeat\s*=\s*"', bloc, re.M):
            continue
        c, mx = cycle_declare(bloc), max_declare(bloc)
        if c is not None and mx is None:
            out.append((nom, "cycle_s declare SANS heartbeat_max_s — la valeur "
                             "derivee manque, le TypeScript n'a rien a lire"))
        elif c is None and mx is not None:
            out.append((nom, "heartbeat_max_s SANS cycle_s — une valeur derivee "
                             "sans son antecedent est une seconde configuration"))
        elif c is not None and mx is not None:
            attendu = seuil_mort(c)
            if abs(mx - attendu) > 1e-6:
                out.append((nom, "heartbeat_max_s=%s mais la formule donne %s "
                                 "(cycle_s=%s) — les deux ont diverge"
                            % (mx, attendu, c)))
    return out


def rapport(texte: str | None = None) -> dict:
    """Denominateur de la migration : combien d'organes ont un cycle DECLARE, herite,
    derive ou inconnu. Sans ce compte, « tout va bien » ne se distingue pas de « je
    n'ai rien pu lire »."""
    par_source: dict = {}
    for _nom, (_c, src) in cycles(texte).items():
        par_source[src] = par_source.get(src, 0) + 1
    return par_source


if __name__ == "__main__":
    import json

    d = seuils()
    print(json.dumps({"sources": rapport(),
                      "seuils": {k: {"seuil_s": v[0], "cycle_s": v[1], "source": v[2]}
                                 for k, v in sorted(d.items())}},
                     ensure_ascii=False, indent=2))
