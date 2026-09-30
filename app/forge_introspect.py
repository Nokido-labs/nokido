#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""app/forge_introspect.py — UN verbe pour interroger le corps avant d'agir.

__FORGE_COLOR__ ci-dessous : SNC, pas qualite. Ce module n'ANALYSE rien de neuf :
il interroge des organes existants et rend une reponse bornee.

LE DEFAUT QU'IL CORRIGE (mesure 2026-08-31)
===========================================
Nokido porte 21 organes d'introspection — capacite, archeologie, atteignabilite,
carte du code, index d'enquetes. La sonde `sandbox/capability_consumers_probe.py`
a montre qu'ils ne sont PAS morts : 17 sur 21 ont un consommateur externe, et la
carte du code en a jusqu'a 11.

Le manque n'est donc ni un registre, ni un cablage module-a-module. C'est qu'il
n'existe AUCUN point d'entree commun : un agent devant un probleme devrait savoir
lequel des 21 appeler. Il n'en appelle donc aucun — mesure du meme jour, les
verbes d'introspection pesent 70 appels sur 16 447 resultats d'outils, soit
0,4 %. Une capacite qu'il faut savoir nommer pour l'atteindre n'est pas atteinte.

CE QU'IL FAIT, ET CE QU'IL NE FAIT PAS
======================================
Il rend, pour une question en langage naturel :
  - les symboles qu'elle nomme et qui EXISTENT vraiment dans le code ;
  - pour chacun : ou il est defini, si l'attribution de ses appelants est SURE
    (RESOLU / AMBIGU / ILLISIBLE, cf. forge_callgraph_jit), et combien
    d'appelants ;
  - si Nokido a DEJA enquete sur ce symptome (index d'enquetes).

Et surtout il DECLARE ce qu'il n'a PAS consulte, avec la raison. Une reponse
d'introspection qui tait ses angles morts se lit comme un panorama complet ;
c'est ainsi qu'on conclut « ca n'existe pas » sur un organe qu'on n'a pas
interroge.

BORNE : au plus 5 symboles, au plus 3 definitions chacun. La memoire totale est
enorme, seuls quelques elements doivent remonter — sinon on recree le probleme
qu'on corrige.
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "SNC/introspection"

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_ENQUETES = ROOT / "sandbox" / "enquetes_index.json"

MAX_SYMBOLES = 5
MAX_DEFS = 3
MAX_CANDIDATS = 12          # bornes le cout : chaque candidat coute un grep

# Mots trop communs pour designer un symbole : les retenir ferait grepper le
# depot entier pour rien.
_VIDES = {
    "pourquoi", "comment", "quand", "quel", "quelle", "quels", "quelles",
    "dans", "avec", "sans", "pour", "cette", "celui", "faire", "fait",
    "probleme", "erreur", "code", "fichier", "module", "nokido", "hub",
    "the", "with", "what", "why", "when", "this", "that", "from",
}
_RE_MOT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
# Trace de la consultation de l'index d'enquetes (voir `_enquetes`).
_META_ENQUETES: dict = {}


def _candidats(question: str) -> list[str]:
    """Mots de la question qui PEUVENT etre des symboles, les plus specifiques d'abord.

    Un `forge_*` passe devant : c'est le vocabulaire propre du corps, et le
    citer est un signal d'intention bien plus fort qu'un mot courant.
    """
    vus: list[str] = []
    for m in _RE_MOT.findall(question or ""):
        b = m.lower()
        if b in _VIDES or m in vus:
            continue
        vus.append(m)
    vus.sort(key=lambda s: (0 if s.startswith("forge_") else 1,
                            0 if "_" in s else 1, -len(s)))
    return vus[:MAX_CANDIDATS]


def _code(question: str, non_consulte: list, jit=None) -> list:
    """Ce que la carte du code sait des symboles nommes.

    `jit` est INJECTABLE a dessein : `forge_callgraph_jit` importe en top-level
    et `app.forge_callgraph_jit` sont DEUX objets module distincts. Un appelant
    qui configure l'un ne configure pas l'autre — piege paye deux fois le
    2026-08-31, la premiere sur des exceptions qui ne se rattrapaient pas.
    """
    if jit is None:
        try:
            sys.path.insert(0, str(ROOT))
            from nokido_agent.app import forge_callgraph_jit as jit  # noqa: PLC0415
        except ImportError as exc:
            non_consulte.append({"organe": "forge_callgraph_jit",
                                 "raison": "import impossible (%s)"
                                           % type(exc).__name__})
            return []
    ambiguite, callers, definitions = jit.ambiguite, jit.callers, jit.definitions
    trouves = []
    for mot in _candidats(question):
        if len(trouves) >= MAX_SYMBOLES:
            break
        try:
            defs = definitions(mot)
        except Exception as exc:  # noqa: BLE001
            non_consulte.append({"organe": "definitions(%s)" % mot,
                                 "raison": type(exc).__name__})
            continue
        if not defs:
            continue          # le mot n'est pas un symbole : on ne l'invente pas
        amb = ambiguite(mot)
        try:
            n_app = len(callers(mot))
        except Exception:  # noqa: BLE001
            n_app = -1        # -1 = NON MESURE, a ne pas lire comme zero
        trouves.append({
            "symbole": mot,
            "definitions": [{"file": d["file"], "classe": d["classe"],
                             "line": d["line"]} for d in defs[:MAX_DEFS]],
            "definitions_total": len(defs),
            "attribution": amb.get("etat"),
            "classes_portant_le_nom": amb.get("classes"),
            "appelants": n_app,
            "reserve": amb.get("note"),
        })
    return trouves


def _definition(source: str, nom: str) -> str:
    """Resume d'un module = 1re phrase de sa docstring, en-tete machine retire, par la regle UNIQUE
    de `forge_wiki_modules` (wiki, fiches RAG et introspect lisent de la meme facon).

    Mesure du 2026-09-29 : l'ancienne heuristique (« 1re ligne de plus de 25 caracteres dans les 12
    premieres ») rendait « DATE:2026-06-02 | VER:... » pour les 181 modules a en-tete machine, et une
    ligne de CODE pour un module sans docstring. Sans docstring, on le DIT.
    """
    try:
        from nokido_agent.tools.forge_wiki_modules import definition_du_module
    except ImportError:
        try:
            from forge_wiki_modules import definition_du_module
        except ImportError:
            return "(regle de lecture des docstrings ILLISIBLE)"
    return definition_du_module(source, nom) or "(sans docstring)"


def _modules(question: str, non_consulte: list, jit) -> list:
    """Les MODULES que la question nomme, et qui les consomme.

    LE DEFAUT CORRIGE (mesure 2026-08-31, le jour meme de la mise en service).
    `definitions()` cherche `def <nom>` : un nom de MODULE n'est jamais une
    definition de fonction, donc une question sur `forge_reachability_ledger`
    rendait ZERO symbole alors que le module existe et pese 300 lignes. Le verbe
    disait « rien trouve » la ou il fallait lire « je n'ai pas cherche ca ».

    On reutilise `_grep_files` de la carte du code plutot que de re-scanner :
    c'est ripgrep, c'est borne, et c'est deja la primitive de recherche du corps.
    """
    trouves: list = []
    racines = [Path(jit.ROOT) / r for r in getattr(jit, "_SCAN_ROOTS", ("app", "tools"))]
    for mot in _candidats(question):
        if len(trouves) >= MAX_SYMBOLES:
            break
        chemin = next((r / (mot + ".py") for r in racines
                       if (r / (mot + ".py")).exists()), None)
        if chemin is None:
            continue
        try:
            resume = _definition(chemin.read_text(encoding="utf-8", errors="replace"), mot + ".py")
        except OSError as exc:
            resume = "(docstring ILLISIBLE : %s)" % type(exc).__name__
        try:
            citants = [f for f in jit._grep_files(mot) if Path(f).stem != mot]
        except Exception as exc:  # noqa: BLE001
            non_consulte.append({"organe": "_grep_files(%s)" % mot,
                                 "raison": type(exc).__name__})
            citants = []
        # CITER N'EST PAS CONSOMMER. Faux positif mesure sur ce module meme :
        # `forge_introspect` nomme `forge_reachability_ledger` dans un
        # commentaire, et il ressortait comme consommateur. Un module cite en
        # prose passe alors pour utilise, et un organe muet parait vivant --
        # exactement l'inverse de ce que ce verbe doit rendre.
        _imp = re.compile(r"(?m)^\s*(?:from\s+%s\s+import|import\s+%s)\b"
                          % (re.escape(mot), re.escape(mot)))
        importeurs, mentions = [], []
        for f in citants[:20]:
            try:
                (importeurs if _imp.search(
                    Path(f).read_text(encoding="utf-8", errors="replace"))
                 else mentions).append(f)
            except OSError:
                mentions.append(f)   # illisible : compte comme mention, jamais import

        def _rel(f):
            return str(Path(f).relative_to(Path(jit.ROOT))).replace("\\", "/")

        trouves.append({
            "module": mot,
            "chemin": str(chemin.relative_to(Path(jit.ROOT))).replace("\\", "/"),
            "resume": resume,
            "importe_par": len(importeurs),
            "cite_sans_import": len(mentions),
            "exemples_import": [_rel(f) for f in importeurs[:4]],
            "exemples_mention": [_rel(f) for f in mentions[:3]],
        })
    if trouves:
        # La primitive ne balaie que `_SCAN_ROOTS` : les tests n'y sont pas.
        # Le taire ferait lire « 0 consommateur » comme « meme pas teste ».
        non_consulte.append({"organe": "tests/ pour les consommateurs de module",
                             "raison": "hors du perimetre de _grep_files (%s)"
                                       % (getattr(jit, "_SCAN_ROOTS", ()),)})
    return trouves


# Ordre de confiance. `INFIRME` reste VISIBLE mais ne remonte jamais en tete :
# une procedure dont le symptome est revenu est une information precieuse
# (« ne refais pas ca »), pas une piste a suivre.
_RANG_ETAT = {"PROUVE": 0, "CONSTATE": 1, "INFIRME": 2}


def _succes(question: str, non_consulte: list, oplog: Path | None) -> list:
    """Les procedures DEJA REUSSIES qui ressemblent a la question.

    POURQUOI ICI. `forge_success_oplog` enregistre depuis le 2026-08-31 les
    corrections passees (197 sur 400 commits examines), et `introspect` est le
    seul point d'entree des agents. Les deux existaient sans se connaitre : le
    verbe rendait le code et les enquetes, jamais ce qui avait DEJA marche.

    Un agent doit consommer l'intelligence accumulee AVANT d'en produire une
    nouvelle. C'est le seul endroit ou cette regle peut s'appliquer sans
    dependre de sa bonne volonte.

    L'etat epistemique PRIME sur le score lexical : une procedure PROUVE passe
    devant une CONSTATE mieux notee, parce qu'une mesure posterieure vaut mieux
    qu'une ressemblance de mots.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_success_oplog import LOG as _LOG_DEFAUT  # noqa: PLC0415
        from nokido_agent.tools.forge_success_oplog import chercher  # noqa: PLC0415
    except ImportError as exc:
        non_consulte.append({"organe": "forge_success_oplog",
                             "raison": "import impossible (%s)" % type(exc).__name__})
        return []
    chemin = Path(oplog) if oplog else _LOG_DEFAUT
    if not chemin.exists():
        # ABSENT n'est pas VIDE : sans journal, « aucune procedure connue » ne
        # veut rien dire. Le backfill est le remede, il faut donc le nommer.
        non_consulte.append({"organe": "forge_success_oplog",
                             "raison": "journal absent (%s) — alimenter via "
                                       "tools/forge_success_oplog.py --backfill"
                                       % chemin.name})
        return []
    try:
        trouves = chercher(question, limite=MAX_SYMBOLES * 2, log=chemin)
    except Exception as exc:  # noqa: BLE001
        non_consulte.append({"organe": "forge_success_oplog.chercher",
                             "raison": type(exc).__name__})
        return []
    for t in trouves:
        t["deconseille"] = (t.get("etat") == "INFIRME")
    trouves.sort(key=lambda t: (_RANG_ETAT.get(t.get("etat"), 1), -t.get("score", 0)))
    return trouves[:MAX_SYMBOLES]


def _perimetre(procedures: list) -> list:
    """Les fichiers de TOUTES les procedures trouvees, dedupliques, hors budget.

    Trois niveaux se mesurent (exposition / pertinence / reutilisation) et le
    deuxieme se lisait dans `procedures_connues` — donc APRES le rogneur. Un
    budget serre effacait la pertinence, et toute edition suivante devenait non
    jugeable. Le perimetre coute quelques chaines : il reste TOUJOURS.
    """
    vus: list = []
    for p in procedures or []:
        for f in p.get("fichiers") or []:
            if f not in vus:
                vus.append(f)
    return vus


def _voisinage(seeds: list, non_consulte: list, k: int = 4) -> dict:
    """Les modules structurellement PROCHES de ce que la question nomme.

    LE TROU COMBLE (question la plus ANCIENNE du chantier, mesuree par git).
    `forge_panorama_builder.scan_forge_modules` construit le vrai graphe
    d'imports par AST depuis le 2026-04-16. `forge_graph_ppr.ppr` porte un
    Personalized PageRank dont la docstring dit mot pour mot « sur graphe de
    code » — ecrit le 2026-05-05. Les deux moities existaient depuis QUATRE MOIS
    et n'avaient jamais ete reliees : le PageRank servait le graphe RAG, pas le
    code. Il n'y avait donc aucun classement par question sur la carte du code.

    DEUX SENS, parce qu'un agent a besoin des deux : `aval` = ce dont le sujet
    depend, `amont` = ce qui depend de lui (donc ce qu'une modification casse).
    Un classement qui n'aurait que l'un des deux repondrait a la moitie de
    « quels modules sont concernes ».

    Cout mesure : 2,26 s pour 556 noeuds et 1108 aretes. Assez peu pour etre
    recalcule a CHAQUE appel — donc pas de cache, donc pas de carte figee (la
    carte du corps est deja restee 5,4 jours en arriere pour cette raison).
    """
    if not seeds:
        # Un dict vide SANS motif se lit « rien de proche », alors qu'il dit
        # « je n'avais pas de point de depart ». Trois etats, jamais deux.
        non_consulte.append({"organe": "voisinage structurel",
                             "raison": "aucun module ni symbole nomme par la "
                                       "question : pas de graine de depart"})
        return {}
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_graph_ppr import ppr, top_k  # noqa: PLC0415
        from nokido_agent.app.forge_panorama_builder import scan_forge_modules  # noqa: PLC0415
    except ImportError as exc:
        non_consulte.append({"organe": "panorama_builder / graph_ppr",
                             "raison": "import impossible (%s)" % type(exc).__name__})
        return {}
    try:
        brut = scan_forge_modules()
    except Exception as exc:  # noqa: BLE001
        non_consulte.append({"organe": "scan_forge_modules",
                             "raison": type(exc).__name__})
        return {}
    aval = {n: sorted(v) for n, v in brut.items()}
    amont: dict = {n: [] for n in aval}
    for n, cibles in aval.items():
        for c in cibles:
            if c in amont:
                amont[c].append(n)

    presents = [s for s in seeds if s in aval]
    if not presents:
        # Le sujet n'est pas un module du graphe : le DIRE plutot que rendre {}.
        non_consulte.append({"organe": "voisinage structurel",
                             "raison": "aucun symbole de la question n'est un "
                                       "module du graphe d'imports"})
        return {"graphe": {"noeuds": len(aval), "aretes": sum(len(v) for v in aval.values())},
                "seeds": [], "amont": [], "aval": []}

    def _classer(g: dict) -> list:
        """Ne rend QUE des modules reellement atteints.

        Sans le filtre sur le score, un noeud PENDANT (un module qui n'importe
        aucun `forge_*`) renvoie toute la masse a la graine : tous les autres
        restent a 0.0 et `top_k` sort alors les quatre PREMIERS DANS L'ORDRE
        ALPHABETIQUE, avec l'air d'un classement. Mesure du 2026-08-31 sur
        `forge_callgraph_jit` : `forge_4096d_encoder`, `forge_access_switches`…
        Un classement de zeros est du bruit deguise en reponse.
        """
        cumul: dict = {}
        for s in presents:
            for nom, score in ppr(g, s).items():
                cumul[nom] = cumul.get(nom, 0.0) + score
        return [{"module": n, "score": round(sc, 4)}
                for n, sc in top_k(cumul, k + len(presents))
                if n not in presents and sc > 1e-9][:k]

    return {"graphe": {"noeuds": len(aval),
                       "aretes": sum(len(v) for v in aval.values())},
            "seeds": presents,
            "aval": _classer(aval), "amont": _classer(amont)}


def _enquetes(question: str, non_consulte: list, index_path: Path) -> list:
    """Nokido a-t-il DEJA enquete sur ce symptome ?

    L'index existe et il est consulte par le hook de session ; il n'etait
    simplement pas joignable depuis un verbe d'introspection.
    """
    # Vider AVANT tout retour anticipe : sinon la trace du dernier appel survit
    # et un index NON consulte se rapporterait comme consulte.
    _META_ENQUETES.clear()
    if not index_path.exists():
        non_consulte.append({"organe": "forge_symptom_index",
                             "raison": "index absent (%s) — construire via "
                                       "tools/forge_symptom_index.py" % index_path.name})
        return []
    try:
        idx = json.loads(index_path.read_text(encoding="utf-8"))
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_symptom_index import demander
    except Exception as exc:  # noqa: BLE001
        non_consulte.append({"organe": "forge_symptom_index",
                             "raison": "%s: %s" % (type(exc).__name__, str(exc)[:60])})
        return []
    sortie = []
    termes = _candidats(question)[:3]
    for mot in termes:
        try:
            for r in demander(mot, idx, limite=2) or []:
                sortie.append({"terme": mot, "session": r.get("session"),
                               "date": r.get("date"), "pieges": r.get("pieges")})
        except Exception as exc:  # noqa: BLE001
            non_consulte.append({"organe": "demander(%s)" % mot,
                                 "raison": type(exc).__name__})
    # « Consulte sans correspondance » et « pas consulte » rendent la MEME liste
    # vide. Sans cette trace, une reponse vide se lit comme une absence d'enquete
    # anterieure — le defaut exact que ce module doit empecher, applique a sa
    # propre sortie.
    _META_ENQUETES.update({"index": index_path.name, "termes_cherches": termes,
                           "correspondances": len(sortie)})
    return sortie[:MAX_SYMBOLES]


def introspect(query: str, budget_tokens: int = 2000,
               index_enquetes: Path | None = None, jit=None,
               oplog: Path | None = None) -> dict:
    """Interroge le corps avant d'agir. Rend une reponse BORNEE et HONNETE."""
    non_consulte: list = []
    code = _code(query, non_consulte, jit=jit)
    _j = jit
    if _j is None:
        try:
            sys.path.insert(0, str(ROOT))
            from nokido_agent.app import forge_callgraph_jit as _j  # noqa: PLC0415
        except ImportError:
            _j = None
    modules = _modules(query, non_consulte, _j) if _j is not None else []
    enquetes = _enquetes(query, non_consulte, index_enquetes or INDEX_ENQUETES)
    procedures = _succes(query, non_consulte, oplog)
    # Graines : les modules nommes, plus ceux qui DEFINISSENT les symboles
    # trouves — un symbole designe son module aussi surement que son nom.
    graines = [m["module"] for m in modules]
    for s in code:
        for d in s.get("definitions", []):
            tige = Path(d["file"]).stem
            if tige not in graines:
                graines.append(tige)
    voisinage = _voisinage(graines[:5], non_consulte)

    # Organes volontairement hors du v1 : les NOMMER, sinon leur absence se lit
    # comme une reponse complete.
    non_consulte.append({"organe": "forge_capability_contracts / "
                                   "forge_reachability_ledger",
                         "raison": "hors v1 : reserves aux questions de SERVICE, "
                                   "pas de symbole"})

    res = {
        "question": query,
        "symboles_trouves": code,
        "modules_trouves": modules,
        "voisinage_structurel": voisinage,
        # En TETE du resultat : c'est ce qu'un agent doit lire en premier.
        "procedures_connues": procedures,
        # PERIMETRE COMPLET, jamais rogne. Ce que le budget retire de
        # l'AFFICHAGE ne doit pas disparaitre de la MESURE : c'est exactement la
        # que se fabriquait `editions_jugeables = 0` (mesure du 2026-08-31).
        "fichiers_procedures": _perimetre(procedures),
        "enquetes_anterieures": enquetes,
        "enquetes_consultation": dict(_META_ENQUETES) or {"index": "non consulte"},
        "non_consulte": non_consulte,
    }
    # Le budget est une PROMESSE : la tenir, et dire quand on tronque.
    estime = len(json.dumps(res, ensure_ascii=False)) // 4
    res["budget"] = {"demande": budget_tokens, "estime": estime,
                     "tronque": False, "retire": {}}
    # ORDRE DE SACRIFICE, du plus contextuel au plus decisif. `enquetes_anterieures`
    # y entre le 2026-08-31 : elle en etait ABSENTE, donc une section INTRONQUABLE
    # et de taille variable affamait celle que le commentaire d'origine pretendait
    # proteger. Mesure : meme question, meme budget 500, 5 procedures rendues a un
    # appel et 0 a un autre — seule la taille des enquetes avait change, et aucun
    # champ ne disait laquelle des sections avait saute.
    _ORDRE = ("voisinage_structurel", "enquetes_anterieures", "symboles_trouves",
              "modules_trouves", "procedures_connues")
    while estime > budget_tokens and any(res[s] for s in _ORDRE):
        for sec in _ORDRE:
            if not res[sec]:
                continue
            if isinstance(res[sec], dict):
                res[sec] = {}
            else:
                res[sec].pop()
            # DIRE ce qui a saute : `[]` par manque de place et `[]` par absence
            # de resultat sont deux etats, indiscernables sans ce compteur.
            res["budget"]["retire"][sec] = res["budget"]["retire"].get(sec, 0) + 1
            break
        res["budget"]["tronque"] = True
        estime = len(json.dumps(res, ensure_ascii=False)) // 4
    res["budget"]["estime"] = estime
    if procedures:
        prouvees = [p for p in procedures if p.get("etat") == "PROUVE"]
        res["recommandation"] = (
            "%d procedure(s) deja appliquee(s) sur un symptome proche%s. Les "
            "INSPECTER avant d'en concevoir une nouvelle." %
            (len(procedures),
             ", dont %d PROUVE(s)" % len(prouvees) if prouvees else
             " — toutes a l'etat CONSTATE, donc a revalider"))
    if not code and not modules and not enquetes and not procedures:
        res["verdict"] = ("ni symbole ni module de la question n'existe dans "
                          "app/ ou tools/, aucune enquete anterieure et aucune "
                          "procedure connue — ce n'est PAS une preuve "
                          "d'absence, voir non_consulte")
    return res


# ── trace de consultation : la matiere du garde a venir ─────────────────────
# On MESURE d'abord, on refusera ensuite. Un garde pose avant de connaitre son
# taux de fausse alerte se fait desarmer au premier cri a faux — piege consigne
# le 2026-08-01 sur ce meme site `handle_governed_edit`.
TRACE = ROOT / "sandbox" / "introspect_trace.json"
TTL_CONSULTATION_S = 1800.0          # 30 min : la duree d'une tache, pas d'une session


def _lire_trace() -> dict:
    try:
        return json.loads(TRACE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}                     # muet-ok : trace absente = aucun historique


# ── la SERIE : sans elle, cet instrument ne peut pas dire s'il s'ameliore ────
#
# DEFAUT MESURE LE 2026-09-18, en repondant a la question de l'owner « est-ce que
# l'auto-amelioration a enfin servi a quelque chose ? ».
#
# `introspect_trace.json` ne porte que des CUMULS et une seule date (`derniere`).
# Un cumul ne peut pas repondre a « est-ce que ca s'ameliore » : il dilue toujours
# le present dans le passe. Pour comparer, il a fallu aller chercher A LA MAIN le
# chiffre du 2026-09-13 dans une fiche memoire -- 13,2 % contre 19,7 % cumules,
# soit 46,8 % sur la periode, un ecart que l'instrument etait incapable de montrer.
#
# L'autre source, `rag_chunks WHERE domain='mcp_result'`, ne peut pas non plus :
# ses 16 447 lignes ont `created_at` a NULL, et 16 334 d'entre elles viennent du
# daemon POST_COMMIT -- ce sont des commits indexes, pas des appels d'outil. D'ou
# le `delta_appels: 0` de `bilan()`, qui ne signifie pas « rien n'a bouge » mais
# « je compare deux nombres qui ne portent aucune date ».
#
# On pose donc UNE ligne par jour et par agent, en append : les cumuls du moment,
# horodates. Les deltas entre deux lignes donnent le taux MARGINAL, seul capable
# de montrer une tendance. Un instantane quotidien suffit (365 lignes par an et
# par agent) -- journaliser chaque evenement couterait 3 583 lignes pour la meme
# information.
#
# Cet ecrivain ne LEVE JAMAIS et n'est jamais dans un chemin critique : un
# instrument qui casse ce qu'il mesure est pire que pas d'instrument.
SERIE = ROOT / "sandbox" / "introspect_serie.jsonl"


def _dernier_jour_serie() -> str:
    """Date du dernier instantane, ou '' si la serie est vide OU ILLISIBLE.

    Les deux cas rendent '' et provoquent une ecriture : ecrire un instantane de
    trop est sans consequence, en manquer un fait un trou dans la tendance.
    """
    try:
        if not SERIE.exists():
            return ""
        lignes = SERIE.read_text(encoding="utf-8").strip().split("\n")
        return json.loads(lignes[-1]).get("jour", "") if lignes and lignes[-1] else ""
    except (OSError, ValueError, IndexError):
        return ""


def _poser_instantane(data: dict) -> None:
    """Un instantane par JOUR : appele a chaque ecriture, il n'ecrit qu'au changement de date."""
    jour = time.strftime("%Y-%m-%d")
    if _dernier_jour_serie() == jour:
        return
    try:
        lignes = []
        for agent, e in sorted(data.items()):
            if not isinstance(e, dict):
                continue
            avec = int(e.get("editions_avec") or 0)
            sans = int(e.get("editions_sans") or 0)
            lignes.append(json.dumps({
                "jour": jour, "ts": time.time(), "agent": agent,
                "consultations": int(e.get("consultations") or 0),
                "editions_avec": avec, "editions_sans": sans,
                "editions": avec + sans,
                "reutilisations": int(e.get("reutilisations") or 0),
                "divergences": int(e.get("divergences") or 0),
            }, ensure_ascii=False))
        if lignes:
            SERIE.parent.mkdir(parents=True, exist_ok=True)
            with SERIE.open("a", encoding="utf-8") as f:
                f.write("\n".join(lignes) + "\n")
    except (OSError, ValueError, TypeError) as exc:  # noqa: BLE001
        print("[introspect] serie non ecrite (%s)" % type(exc).__name__, flush=True)


def _ecrire_trace(data: dict) -> None:
    """Ecriture atomique : une trace a moitie ecrite ferait croire a zero
    consultation, donc avertir un agent qui avait fait son travail."""
    try:
        TRACE.parent.mkdir(parents=True, exist_ok=True)
        tmp = TRACE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(TRACE)
    except OSError as exc:  # noqa: BLE001
        print("[introspect] trace non ecrite (%s)" % type(exc).__name__, flush=True)
    # APRES la trace, jamais avant : la serie est un confort de mesure, la trace
    # est ce dont le garde depend.
    _poser_instantane(data)


def noter_consultation(agent: str, question: str = "", resultat=None) -> None:
    """Retient AUSSI les fichiers des procedures proposees.

    LE MAILLON MANQUANT (question ouverte depuis le 2026-07-30). Consulter n'est
    pas reutiliser. Sans memoire de CE QUI A ETE PROPOSE, on ne peut pas
    distinguer :
        probleme -> introspect -> ancienne solution -> l'agent l'IGNORE -> reinvente
    de :
        probleme -> introspect -> ancienne solution -> l'agent la REUTILISE
    Dans les deux cas le compteur de consultations monte. Seul le rapprochement
    avec les fichiers reellement ecrits ensuite les separe.
    """
    d = _lire_trace()
    e = d.setdefault(str(agent or "INCONNU").upper(), {})
    e["derniere"] = time.time()
    e["question"] = str(question)[:160]
    e["consultations"] = int(e.get("consultations") or 0) + 1
    proposes: list = []
    if isinstance(resultat, dict):
        # Le perimetre HORS BUDGET d'abord : `procedures_connues` a pu etre vide
        # par le rogneur, `fichiers_procedures` ne l'est jamais.
        for f in resultat.get("fichiers_procedures") or []:
            if f not in proposes:
                proposes.append(f)
        for p in resultat.get("procedures_connues") or []:
            for f in p.get("fichiers") or []:
                if f not in proposes:
                    proposes.append(f)
    e["fichiers_proposes"] = proposes[:40]
    _ecrire_trace(d)


def consultation_recente(agent: str, ttl: float = TTL_CONSULTATION_S) -> dict:
    """(vu, age). TROIS etats : consultee / jamais / trop ancienne."""
    e = _lire_trace().get(str(agent or "INCONNU").upper()) or {}
    derniere = float(e.get("derniere") or 0)
    if not derniere:
        return {"vu": False, "etat": "JAMAIS", "age_s": None}
    age = time.time() - derniere
    return {"vu": age <= ttl, "etat": "RECENTE" if age <= ttl else "PERIMEE",
            "age_s": round(age, 1), "question": e.get("question", "")}


def noter_edition(agent: str, avec_consultation: bool, chemin: str = "") -> None:
    """Compteurs du garde, ET le troisieme niveau : la REUTILISATION.

    Trois niveaux, jamais confondus :
      EXPOSITION    `introspect` est-il appele ?          -> consultations
      PERTINENCE    trouve-t-il une piste exploitable ?   -> fichiers_proposes
      REUTILISATION l'agent ecrit-il DANS cette piste ?   -> ici

    Une ecriture qui tombe dans un fichier propose est un indice FORT de
    reutilisation, pas une preuve : l'agent a pu y ecrire pour une autre raison.
    On compte donc `reutilisations` et `divergences` sans jamais les presenter
    comme un verdict.
    """
    d = _lire_trace()
    e = d.setdefault(str(agent or "INCONNU").upper(), {})
    cle = "editions_avec" if avec_consultation else "editions_sans"
    e[cle] = int(e.get(cle) or 0) + 1
    if avec_consultation and chemin:
        norm = str(chemin).replace("\\", "/")
        proposes = e.get("fichiers_proposes") or []
        touche = any(norm.endswith(p) or p.endswith(norm) for p in proposes)
        if proposes:
            e["reutilisations" if touche else "divergences"] = int(
                e.get("reutilisations" if touche else "divergences") or 0) + 1
    _ecrire_trace(d)


def taux_consultation() -> dict:
    """Le denominateur du garde : combien d'editions ont ete precedees d'une
    consultation. C'est ce chiffre qui autorisera (ou non) a passer au refus."""
    d = _lire_trace()
    avec = sum(int(v.get("editions_avec") or 0) for v in d.values())
    sans = sum(int(v.get("editions_sans") or 0) for v in d.values())
    total = avec + sans
    reut = sum(int(v.get("reutilisations") or 0) for v in d.values())
    div = sum(int(v.get("divergences") or 0) for v in d.values())
    juges = reut + div
    return {"editions": total, "avec_consultation": avec, "sans": sans,
            "taux_pct": round(100.0 * avec / total, 1) if total else None,
            "consultations": sum(int(v.get("consultations") or 0) for v in d.values()),
            # NIVEAU 3. `juges` est le DENOMINATEUR : une edition faite apres une
            # consultation qui n'a RIEN propose n'est ni une reutilisation ni une
            # divergence, elle n'est pas jugeable. La compter fausserait le taux.
            "reutilisations": reut, "divergences": div, "editions_jugeables": juges,
            "taux_reutilisation_pct": round(100.0 * reut / juges, 1) if juges else None,
            "agents": sorted(d)}


# ── mesurer ce que la reutilisation evite ───────────────────────────────────
# POINT ZERO fige le 2026-08-31, juste apres l'exposition du verbe et AVANT
# qu'un agent ait pu l'appeler. Miroir du fait `introspect_point_zero_20260831`
# au tableau noir. Les valeurs sont ecrites ICI pour que la mesure soit
# rejouable sans dependre d'un service : un indicateur qui exige que le hub
# tourne ne sera jamais relance le jour ou le hub est en panne.
POINT_ZERO = {"date": "2026-08-31", "appels": 70, "total": 16447}
_MATCH_INTROSPECTION = ("get_file_skeleton OR get_function_dependencies OR "
                        "forge_deep_explore OR deep_explore OR introspect")
BASE_DB = ROOT / "RAG" / "embeddings.db"


def _compter_appels(db: Path | None = None) -> dict:
    """(appels d'introspection, total des resultats d'outils) ou l'echec DIT.

    Rendre (0, 0) sur une base illisible ferait lire « aucun appel » la ou il
    faut lire « je n'ai pas pu compter » — le defaut que tout ce module combat.
    """
    chemin = db or BASE_DB
    if not chemin.exists():
        return {"lisible": False, "raison": "base absente (%s)" % chemin.name}
    try:
        import sqlite3  # noqa: PLC0415

        con = sqlite3.connect("file:%s?mode=ro" % chemin, uri=True, timeout=5)
        try:
            appels = con.execute(
                "SELECT COUNT(*) FROM rag_fts WHERE rag_fts MATCH ? "
                "AND domain='mcp_result'", (_MATCH_INTROSPECTION,)).fetchone()[0]
            total = con.execute(
                "SELECT COUNT(*) FROM rag_chunks WHERE domain='mcp_result'"
            ).fetchone()[0]
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        return {"lisible": False, "raison": "%s: %s" % (type(exc).__name__,
                                                        str(exc)[:80])}
    return {"lisible": True, "appels": int(appels), "total": int(total)}


def tendance(jours: int = 7, serie: Path | None = None) -> dict:
    """Taux MARGINAL de consultation sur les N derniers jours, depuis la serie.

    C'est la reponse a « est-ce que ca s'ameliore », que les cumuls ne peuvent pas
    donner. On compare deux instantanes : ce qui s'est passe ENTRE eux.

    Trois etats, jamais deux. `PAS_ASSEZ_DE_POINTS` (moins de deux instantanes) et
    `RIEN_A_MESURER` (aucune edition dans l'intervalle) ne se replient PAS sur
    « 0 % » : une tendance absente n'est pas une tendance nulle.
    """
    f = Path(serie) if serie else SERIE
    try:
        brut = f.read_text(encoding="utf-8").strip()
    except OSError as exc:  # noqa: BLE001 — ILLISIBLE n'est pas VIDE, on le DIT
        return {"mesure": "INCONNU",
                "raison": "serie illisible (%s)" % type(exc).__name__}
    points: list[dict] = []
    illisibles = 0
    for ligne in brut.split("\n"):
        if not ligne.strip():
            continue
        try:
            points.append(json.loads(ligne))
        except ValueError:
            illisibles += 1          # compte, pas ignore en silence
    if len(points) < 2:
        return {"mesure": "PAS_ASSEZ_DE_POINTS", "n_points": len(points),
                "lignes_illisibles": illisibles,
                "raison": "il faut au moins deux instantanes pour une tendance ; "
                          "la serie commence le jour de sa pose"}
    borne = time.time() - jours * 86400
    fenetre = [p for p in points if float(p.get("ts") or 0) >= borne] or points[-2:]
    par_agent: dict = {}
    for p in fenetre:
        par_agent.setdefault(p.get("agent", "?"), []).append(p)
    out: dict = {"mesure": "OK", "jours": jours, "n_points": len(points),
                 "lignes_illisibles": illisibles, "agents": {}}
    for agent, pts in par_agent.items():
        if len(pts) < 2:
            out["agents"][agent] = {"mesure": "PAS_ASSEZ_DE_POINTS", "n": len(pts)}
            continue
        a, b = pts[0], pts[-1]
        d_ed = int(b.get("editions") or 0) - int(a.get("editions") or 0)
        d_av = int(b.get("editions_avec") or 0) - int(a.get("editions_avec") or 0)
        if d_ed <= 0:
            out["agents"][agent] = {"mesure": "RIEN_A_MESURER", "editions": d_ed,
                                    "du": a.get("jour"), "au": b.get("jour")}
            continue
        out["agents"][agent] = {
            "mesure": "OK", "du": a.get("jour"), "au": b.get("jour"),
            "editions": d_ed, "avec_consultation": d_av,
            "taux_marginal_pct": round(100.0 * d_av / d_ed, 1),
            # Le cumul est donne A COTE, jamais a la place : c'est lui qui
            # dilue le present dans le passe.
            "taux_cumule_pct": round(
                100.0 * int(b.get("editions_avec") or 0) / max(int(b.get("editions") or 0), 1), 1),
        }
    return out


def bilan(db: Path | None = None) -> dict:
    """Le verbe est-il ADOPTE ? Et la memoire sert-elle a quelque chose ?

    DEUX INDICATEURS, ET UNE PRECAUTION DE METHODE.

    1. ADOPTION — part de l'introspection dans les appels d'outils. Compare au
       point zero par le taux MARGINAL, sur les appels APPARUS DEPUIS, et non
       par le pourcentage cumule : un cumul sur 16 447 lignes bouge de facon
       glaciale et masquerait une adoption reelle pendant des semaines.
    2. REUTILISATION — part des editions precedees d'une consultation.

    TROIS ETATS, jamais deux : ADOPTE / EN HAUSSE / STAGNANT, plus
    NON MESURABLE quand la base est illisible ou qu'aucun appel nouveau n'a ete
    enregistre. Une stagnation prouverait que le probleme n'etait pas
    l'exposition — et il faudrait alors chercher ailleurs plutot que d'ajouter
    un organe de plus.
    """
    c = _compter_appels(db)
    base_pct = 100.0 * POINT_ZERO["appels"] / POINT_ZERO["total"]
    _t = taux_consultation()
    res = {"point_zero": dict(POINT_ZERO), "base_pct": round(base_pct, 2),
           "reutilisation": _t,
           # INDICATEUR VIVANT. Mesure du 2026-08-31 : le domaine `mcp_result`
           # n'a pas grandi d'une ligne malgre des dizaines d'appels d'outils
           # dans la journee — le denominateur historique n'a plus d'emetteur.
           # Un indicateur branche sur un signal que personne n'emet reste a
           # zero pour toujours et se lit « aucune adoption », ce qui est faux.
           # Le compteur de consultations, lui, est ecrit a chaque appel du
           # verbe depuis aujourd'hui : c'est le seul chiffre qui bouge.
           "adoption_live": {"consultations": _t.get("consultations", 0),
                             "source": "sandbox/introspect_trace.json",
                             "depuis": POINT_ZERO["date"]}}
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_success_oplog import entrees as _entrees  # noqa: PLC0415

        etats: dict = {}
        for e in _entrees():
            etats[e.get("etat", "?")] = etats.get(e.get("etat", "?"), 0) + 1
        res["memoire_procedurale"] = etats
    except Exception as exc:  # noqa: BLE001
        res["memoire_procedurale"] = {"illisible": type(exc).__name__}

    # LA TENDANCE, seule capable de dire si ca s'ameliore. Elle vient de la serie
    # datee, pas du domaine RAG dont les lignes n'ont pas de `created_at`.
    res["tendance_7j"] = tendance(7)

    if not c.get("lisible"):
        res.update({"verdict": "NON MESURABLE", "raison": c.get("raison")})
        return res
    d_appels = c["appels"] - POINT_ZERO["appels"]
    d_total = c["total"] - POINT_ZERO["total"]
    res.update({"maintenant": {"appels": c["appels"], "total": c["total"]},
                "delta_appels": d_appels, "delta_total": d_total})
    if d_total <= 0:
        res.update({"verdict": "NON MESURABLE",
                    "raison": "le domaine `mcp_result` n'a pas grandi depuis le "
                              "point zero : son emetteur est mort. Ce n'est PAS "
                              "une absence d'adoption — lire `adoption_live`, "
                              "seul compteur dont l'ecriture est prouvee."})
        return res
    marginal = 100.0 * max(d_appels, 0) / d_total
    res["taux_marginal_pct"] = round(marginal, 2)
    # Seuils DECLARES : 5x le taux de depart pour parler d'adoption, sinon
    # « en hausse » reste une variation qui peut n'etre que du bruit.
    if marginal >= 5 * base_pct:
        res["verdict"] = "ADOPTE"
    elif marginal > base_pct:
        res["verdict"] = "EN HAUSSE"
    else:
        res["verdict"] = "STAGNANT"
    return res


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Interroge le corps avant d'agir.")
    ap.add_argument("query", nargs="*")
    ap.add_argument("--budget", type=int, default=2000)
    ap.add_argument("--taux", action="store_true",
                    help="rend le taux d'editions precedees d'une consultation")
    ap.add_argument("--bilan", action="store_true",
                    help="adoption du verbe et reutilisation, contre le point zero")
    a = ap.parse_args()
    if a.bilan:
        print(json.dumps(bilan(), ensure_ascii=False, indent=1))
        return 0
    if a.taux:
        print(json.dumps(taux_consultation(), ensure_ascii=False, indent=1))
        return 0
    if not a.query:
        ap.print_help()
        return 2
    print(json.dumps(introspect(" ".join(a.query), a.budget),
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
