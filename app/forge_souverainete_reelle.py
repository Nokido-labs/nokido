# -*- coding: utf-8 -*-
"""Souverainete MESUREE : quelle part du travail a ete faite en local, reellement.

La declaration d'organe est plus bas, au niveau module -- PAS ici : le census lit une
regex ancree en debut de ligne, et une docstring qui cite `__FORGE_COLOR__` se fait
prendre pour la declaration (piege consigne dans RULES_SHARED). Un seul defaut, celui
qui s'execute.

POURQUOI CE MODULE (demande owner, 2026-09-18)
-----------------------------------------------
*« La partie souverainete devrait representer le reel des actions effectuees pour
afficher leur niveau de souverainete reel [...] et afficher le pourcentage selon le
fonctionnement reel de Nokido. »*

Ce qui etait affiche jusqu'ici : `PREF.get("power", 68)`, une valeur que l'utilisateur
REGLE lui-meme avec un curseur, rendue ensuite comme « 68% local » a cote d'un badge de
provenance. C'est une PREFERENCE presentee comme une mesure -- precisement ce que ce
depot appelle un chiffre decoratif.

Ce que ce module mesure, et sur quoi : la table `token_usage`, ecrite par
`forge_token_monitor.log_call` a chaque appel de modele. 23 118 appels du 2026-04-27 au
2026-09-18 au moment de l'ecriture. La premiere mesure, tous temps confondus :

    paid_api            16 239   70,2 %
    free (cloud)         4 019   17,4 %
    LOCAL                1 042    4,5 %
    subscription_quota     917    4,0 %
    non classes            910    3,9 %

Soit **4,5 % de local**, la ou le curseur affichait 68 %.

TROIS REGLES QUI TIENNENT CE MODULE :

1. **L'indetermine ne rejoint jamais le sain.** 18 des 43 providers observes ne sont pas
   dans le catalogue de specs (`router`, `router_local`, `gpt4o_github`...). On ne les
   devine pas : ils sont comptes `indetermine` et le chiffre est EXPOSE. Classer par
   liste BLANCHE, jamais par liste noire.
2. **Le denominateur est toujours dit.** Un pourcentage sans son nombre d'appels ne
   permet pas de juger s'il veut dire quelque chose.
3. **La cible n'est pas la mesure.** Le curseur reste une intention ; ce module rend le
   REEL. L'ecart entre les deux est l'information utile, et il ne doit jamais etre
   masque en affichant l'un a la place de l'autre.

COUT. `SELECT provider, COUNT(*) ... GROUP BY provider` sur `token_usage` : **8 a 11 ms**
mesurees (23 118 lignes, index `idx_tu_ts` present). Le plan est un `SCAN` de cette table,
PAS de `rag_chunks` -- la nuance compte, ce depot a paye cinq balayages de la grosse
table. Un cache court evite de le refaire a chaque rafraichissement d'ecran.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional

__FORGE_COLOR__ = "immunitaire/souverainete"

# Classes de provenance. `local` est la seule qui compte comme souveraine.
LOCAL = "local"
_CLASSES = (LOCAL, "free", "subscription_quota", "paid_api", "indetermine")

# Fenetres proposees. La souverainete d'aujourd'hui informe plus que celle d'avril.
FENETRES = {"24h": 24, "7j": 24 * 7, "30j": 24 * 30, "total": None}

_CACHE: dict = {}
_CACHE_TTL_S = 20.0
_VERROU = threading.Lock()


def _importer(nom: str):
    """Importe un module du corps sous l'un OU l'autre de ses deux noms.

    Le meme module est atteignable comme `nokido_agent.app.X` dans le process du hub et
    comme `X` depuis `app/` : deux noms, deux entrees de `sys.modules`. Ne tenter qu'une
    forme ferait echouer ce module selon l'appelant, sans que rien ne le dise.
    """
    try:
        return __import__("nokido_agent.app." + nom, fromlist=[nom])
    except Exception:  # noqa: BLE001 — repli sur le nom direct, pas un echec
        return __import__(nom)


def _chemin_db():
    """Chemin de la base d'usage. REUTILISE celui du module de quota, jamais redecouvert.

    On lit la ou le PRODUCTEUR ecrit : `forge_token_monitor.log_call` alimente
    `token_usage` dans cette base, et `forge_provider_quota` l'y lit deja. Redecouvrir
    le chemin ouvrirait une seconde source de verite -- et ce depot a paye la confusion
    entre deux accesseurs de base le 2026-09-16.
    """
    return str(_importer("forge_provider_quota").DB)


def _classe_par_provider() -> dict:
    """{provider_du_journal: classe}. Liste BLANCHE : l'inconnu reste inconnu."""
    specs = _importer("forge_provider_specs").PROVIDER_SPECS
    direct = {nom: (sp or {}).get("tier") for nom, sp in specs.items()}
    return {k: v for k, v in direct.items() if v}


# ZONE D'OMBRE INSTRUITE (2026-09-18) — pour ne pas refaire l'enquete.
# Les 4,1 % d'indetermine sont domines par des META-PROVIDERS, pas par des fournisseurs
# manquants : `router` (481 appels) et `router_local` (51) sont des STRATEGIES de routage
# exposees comme providers par `forge_agent_proxy`, et le journal enregistre la strategie,
# pas le slot finalement retenu.
#   - `router_local` EST local : `RouterLocalProvider._force_local = True`, verifie par AST
#     — mais 51 appels sur 23 305, soit 0,2 %. Un parseur dans le chemin d'affichage ne se
#     justifie pas pour ce gain ; et l'inscrire au catalogue des CLES serait faux : il n'a
#     pas de secret a stocker.
#   - `router` ne peut PAS etre tranche depuis le journal : sa cascade peut finir en local
#     comme en cloud. Le classer serait une invention dans un sens ou dans l'autre.
# Ces noms sont donc rendus a l'ecran par `providers_non_classes`, et le pourcentage local
# est presente comme une BORNE BASSE. Le jour ou le journal portera le slot retenu (et non
# la strategie demandee), cette zone se fermera par une mesure, pas par une convention.


def _classer(provider: str, table: dict) -> str:
    """Classe un provider observe, ou rend `indetermine`.

    On tente le nom exact, puis la famille (`gpt4o_github` -> `github`). On NE tente
    PAS de deviner au-dela : inventer une classe fausserait la mesure dans le sens
    flatteur ou defavorable, sans qu'on sache lequel.
    """
    if provider in table:
        return table[provider]
    famille = provider.split("_")[0]
    for nom, tier in table.items():
        if nom == famille or nom.startswith(famille + "_") or provider.startswith(nom):
            return tier
    return "indetermine"


def parts(fenetre: str = "30j", db_path: Optional[str] = None) -> dict:
    """Part reelle de chaque classe de provenance sur la fenetre demandee.

    Rend toujours `denominateur`, `indetermine_pct` et `mesure` : un pourcentage sans
    son assise ne se juge pas, et une fenetre sans appel n'est pas « 0 % local », c'est
    « rien a mesurer ».
    """
    heures = FENETRES.get(fenetre, FENETRES["30j"])
    cle = (fenetre, db_path or "")
    with _VERROU:
        garde = _CACHE.get(cle)
        if garde and (time.time() - garde[0]) < _CACHE_TTL_S:
            return garde[1]

    chemin = db_path or _chemin_db()
    borne = None
    if heures:
        borne = time.strftime("%Y-%m-%d %H:%M:%S",
                              time.localtime(time.time() - heures * 3600))
    sql = ("SELECT provider, COUNT(*), COALESCE(SUM(total_tokens),0) "
           "FROM token_usage")
    args: tuple = ()
    if borne:
        sql += " WHERE ts >= ?"
        args = (borne,)
    sql += " GROUP BY provider"

    t0 = time.time()
    try:
        with sqlite3.connect(chemin, timeout=5) as con:
            lignes = con.execute(sql, args).fetchall()
    except Exception as exc:  # noqa: BLE001 — ILLISIBLE n'est pas « zero appel »
        return {
            "mesure": "INCONNU",
            "raison": "journal d'usage illisible (%s)" % type(exc).__name__,
            "fenetre": fenetre, "denominateur": 0, "classes": {}, "part_locale_pct": None,
        }

    table = {}
    try:
        table = _classe_par_provider()
    except Exception as exc:  # noqa: BLE001 — sans catalogue, TOUT devient indetermine
        table = {}
        raison_table = "catalogue de specs illisible (%s)" % type(exc).__name__
    else:
        raison_table = ""

    compte = {c: 0 for c in _CLASSES}
    jetons = {c: 0 for c in _CLASSES}
    inconnus = []
    for provider, n, tok in lignes:
        c = _classer(str(provider), table)
        if c not in compte:
            c = "indetermine"
        if c == "indetermine":
            inconnus.append((str(provider), int(n)))
        compte[c] += int(n or 0)
        jetons[c] += int(tok or 0)

    total = sum(compte.values())
    if not total:
        return {
            "mesure": "RIEN_A_MESURER",
            "raison": "aucun appel enregistre sur la fenetre %s" % fenetre,
            "fenetre": fenetre, "denominateur": 0, "classes": {}, "part_locale_pct": None,
            "duree_ms": round((time.time() - t0) * 1000, 1),
        }

    resultat = {
        "mesure": "OK",
        "fenetre": fenetre,
        "denominateur": total,
        "classes": {c: {"appels": compte[c], "tokens": jetons[c],
                        "pct": round(100.0 * compte[c] / total, 1)} for c in _CLASSES},
        # LE chiffre : la part reellement servie en local.
        "part_locale_pct": round(100.0 * compte[LOCAL] / total, 1),
        # Expose SEPAREMENT : une part d'indetermine elevee rend le reste fragile.
        "indetermine_pct": round(100.0 * compte["indetermine"] / total, 1),
        "providers_non_classes": sorted(inconnus, key=lambda x: -x[1])[:12],
        "duree_ms": round((time.time() - t0) * 1000, 1),
    }
    if raison_table:
        resultat["avertissement"] = raison_table
    with _VERROU:
        _CACHE[cle] = (time.time(), resultat)
    return resultat


def toutes_fenetres(db_path: Optional[str] = None) -> dict:
    """Les quatre fenetres d'un coup : une tendance se lit mal sur un seul point."""
    return {nom: parts(nom, db_path=db_path) for nom in FENETRES}
