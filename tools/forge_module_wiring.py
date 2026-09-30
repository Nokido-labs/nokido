#!/usr/bin/env python3
"""forge_module_wiring.py — chaque module : DEFINI, BRANCHE, TESTE.

Ordre owner : verifier chaque module avec sa definition, son branchement et ses
tests. Les deux premiers points etaient couverts (wiki genere depuis les
docstrings, 4600+ tests NR) ; le BRANCHEMENT ne l'etait pas. Il n'etait
constate qu'au hasard des enquetes — et chaque fois il revelait quelque chose :
`pat_self_improvement` reference par 3 modules mais SUPPRIME, `phase1_janitor`
sans aucun appelant, `STATE_ENCODER` frappant 7 424 fois une porte fermee.

Un module non branche n'est pas forcement mort : il peut etre un point d'entree
(`__main__`), un service declare, une tache planifiee, ou un handler cite dans
un catalogue. C'est pourquoi ce scan cherche le branchement par CINQ voies
avant de conclure, et nomme celle qui a repondu.

Trois etats par module, jamais un booleen :
    BRANCHE      au moins une voie l'atteint (la voie est citee)
    ORPHELIN     aucune voie — candidat au code mort, a trancher a la main
    POINT_ENTREE lancable seul (`__main__`), donc legitimement sans importateur

Ce module ne SUPPRIME rien et ne propose rien : un orphelin peut etre un outil
d'astreinte lance a la main une fois par trimestre. Il rend la carte, l'humain
tranche.
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/audit : chaque module defini, branche, teste"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sandbox" / "module_wiring.json"
ZONES = ("app", "tools", "recon_silo")
IGNORES = {"_attic", "node_modules", "backups", "archive"}
# Fichiers non-Python qui LANCENT quelque chose : services, lanceurs, CI, taches.
# `*.json` en est EXCLU deliberement : `sandbox/workspace/organ_map_full.json`
# et les inventaires du meme genre CITENT tous les modules du depot sans en
# brancher aucun. Les inclure rendait le scan inutile — 1 788 modules, 1 788
# « branches », zero orphelin (mesure 2026-08-15). Un critere qui declare tout
# le monde sain ne mesure rien.
DECLARATIFS = ("*.toml", "*.bat", "*.cmd", "*.ps1", "*.yml", "*.yaml")


def modules() -> list[Path]:
    out = []
    for zone in ZONES:
        d = ROOT / zone
        if d.is_dir():
            out += [p for p in sorted(d.glob("**/*.py"))
                    if not (IGNORES & set(p.parts))]
    return out


def _texte_declaratif(journal: list = None) -> str:
    """Tout ce qui declare des lancements : services.toml, .bat, .ps1, .yml."""
    morceaux = []
    for zone in (".", "proxy_deno", ".github", "tools", "app", "config"):
        d = ROOT / zone
        if not d.is_dir():
            continue
        for motif in DECLARATIFS:
            for p in d.glob(f"**/{motif}"):
                if IGNORES & set(p.parts) or p.stat().st_size > 3_000_000:
                    continue
                try:
                    morceaux.append(p.read_text(encoding="utf-8", errors="replace"))
                except OSError as err:
                    # Un fichier declaratif qu'on ne PEUT PAS lire est un angle mort :
                    # le module qu'il cite sera declare ORPHELIN faute de preuve. Ce
                    # n'est pas "il ne cite rien", c'est "je n'ai pas pu regarder".
                    if journal is not None:
                        journal.append({"chemin": str(p), "phase": "declaratif",
                                        "motif": "%s: %s" % (type(err).__name__, err)})
                    continue
    return "\n".join(morceaux)


# Les deux paquets du depot. Un import QUALIFIE (`from app.forge_x import y`) doit
# compter pour `forge_x`, pas pour `app`.
# `_PAQUETS = {"app", "tools"}` RETIRE le 2026-09-07 : cette liste ecrite a la main
# servait a decider qu'un segment SUIVANT un paquet etait un module -- c'est elle qui
# creditait les segments intermediaires (45 fausses aretes). La resolution se fait
# desormais contre l'arborescence REELLE (`_index_pointes`). NR : test_module_wiring_
# imports_qualifies_nr.test_l_heuristique_des_paquets_a_ete_RETIREE.


# ── STATUT DE L'INSTRUMENT ────────────────────────────────────────────────────────
#
# Ecrit AVANT de pouvoir le revendiquer, pour qu'il ne soit pas redige a posteriori
# autour de ce qu'on a deja. Un capteur qui ne declare pas son propre statut est lu
# comme une autorite par le premier consommateur qui l'ouvre.
CONTRAT_CERTIFICATION = (
    "imports qualifies ET relatifs resolus au fichier VISE",
    "collisions conservees, jamais arbitrees",
    "NR inscrits a PURE_TESTS",
    "aucune classe de defaut connue non couverte",
    "CI complete verte",
    "artefact identifiable par sha",
)

# Deux classes de defaut MESUREES le 2026-09-07, disjointes -- et la seconde n'a
# AUCUN signal d'ambiguite, donc le garde de la premiere ne la couvre pas.
CLASSES_DE_DEFAUT = (
    "collision de basename -> fusion d'identites (temoin: app/agents/core.py, "
    "43 importeurs annonces, 0 reel ; signal AMBIGU disponible)",
    "clef de niveau PAQUET -> absorption massive d'aretes (temoin: app/web_hub/app.py, "
    "79 annonces dont 76 fabriquees = 96,2 % ; stem UNIQUE, donc AUCUN signal)",
)

CERTIFICATION = {
    "statut": "NON_CERTIFIANT",        # NON_CERTIFIANT | CERTIFIANT | ILLISIBLE
    # LITTERAL, jamais derive d'un score. `confidence` et `authority` sont
    # orthogonaux : aucune qualite de mesure ne transforme un instrument
    # d'exploration en instrument de decision.
    "authority": False,
    "utilisable_pour": ("exploration", "diagnostic", "suggestion", "hypothese"),
    "interdit_pour": ("autorisation", "routage", "publication d'une capacite"),
    "motif": "deux classes de defaut d'identite mesurees le 2026-09-07 ; la liste des "
             "classes connues n'est pas reputee close",
    "contrat": CONTRAT_CERTIFICATION,
    "classes_de_defaut_connues": CLASSES_DE_DEFAUT,
    # A COTE du statut, jamais dedans : une metrique n'ameliore pas une autorite.
    # Le bon KPI n'est pas « moins d'orphelins » mais « combien d'aretes inventees ou
    # effacees restent apres chaque correction ».
    "mesures": {
        "2026-09-07": {
            "false_edges": 112, "missing_edges": 126,
            "aretes_avant": 2601, "aretes_apres": 2615,
            "lecture": "238 aretes corrigees (9,1 %) pour un solde net de +14 (0,54 %) "
                       "-- le total etait presque aveugle",
        },
    },
}


def _index_pointes(mods) -> dict:
    """pointe pointee -> chemin canonique. Un PAQUET est designe par son `__init__.py`.

    `app.core.settings` vise `app/core/settings/__init__.py` : sans cette entree, un
    import de paquet ne se resout pas et retombe dans la resolution par nom, ou il
    devient une arete vers n'importe quel fichier portant ce nom."""
    idx = {}
    for p in mods:
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel.endswith("/__init__.py"):
            idx.setdefault(rel[: -len("/__init__.py")].replace("/", "."), rel)
        elif rel.endswith(".py"):
            idx.setdefault(rel[:-3].replace("/", "."), rel)
    return idx


def _resoudre_import(pointe: str, index: dict) -> tuple:
    """(genre, cible) -- trois issues, jamais deux. ID-03 du contrat d'identite.

    CE QUI A ETE PAYE (2026-09-07, deux passes). D'abord `pointe.split(".")[0]` :
    `from app.forge_code_ast import X` comptait pour « app », 44 aretes perdues.
    Le correctif d'alors creditait les segments qui SUIVENT un paquet du depot -- et
    creditait donc les segments INTERMEDIAIRES. Mesure : `from app.core.settings
    import X`, ecrit dans 45 fichiers, creditait un module nomme « core », resolu par
    nom vers `app/agents/core.py` -- un fichier d'un autre organe, qui publiait donc
    « importe par 43 module(s) » sans qu'aucun import ne le vise. Et la vraie cible,
    `app/core/settings/`, ne recevait RIEN. Fausse attribution ET attribution manquante.

    Un segment intermediaire est un REPERTOIRE, pas un module. PACKAGE != MODULE.

    La regle : une pointe POINTEE est deja une identite (un chemin) -- on la resout
    contre l'arborescence reelle, ou on ne la resout pas. Elle ne retombe JAMAIS dans
    la resolution par nom, sinon une arete non ambigue par construction redevient
    ambigue. Une pointe NUE est une clef de resolution : `import forge_x` designe un
    nom, et Nokido importe a plat, donc c'est le cas courant (99 % des aretes).

      chemin  la pointe designe un fichier du depot     -> attribuable, toujours
      nom     pointe nue                                -> attribuable si le nom est unique
      absent  pointe pointee hors depot (stdlib, tiers) -> AUCUNE arete
    """
    cible = index.get(pointe)
    if cible is not None:
        return ("chemin", cible)
    if "." not in pointe:
        return ("nom", pointe)
    return ("absent", pointe)


def _resoudre_relatif(rel_importeur: str, niveau: int, module, index: dict) -> tuple:
    """`from .mode_panel import X` -> (genre, cible). L'arete la PLUS determinee.

    CE QUI A ETE PAYE (2026-09-07, dans la passe ID-03 elle-meme). En ecartant les
    imports relatifs (`n.level > 0`) sans les remplacer, j'ai fait passer
    `app/collab_modes/mode_panel.py` de BRANCHE a ORPHELIN : son unique importeur,
    `dispatch.py`, le vise par `from .mode_panel`. Zero pointe ABSOLUE ne le nomme --
    l'ancien code l'attrapait par accident, en ignorant `n.level`.

    Or un import relatif ne depend d'AUCUN nom global : le paquet de l'importeur donne
    la base, le reste est un chemin. C'est la resolution la plus sure du fichier, et
    elle etait la seule preuve d'existence de cette arete.
    """
    parts = rel_importeur.split("/")[:-1]          # le paquet qui contient l'importeur
    if niveau > 1:
        parts = parts[: -(niveau - 1)] if niveau - 1 <= len(parts) else []
    if not parts:
        return ("absent", module or "")            # remonte au-dela de la racine
    pointe = ".".join(parts) + (("." + module) if module else "")
    cible = index.get(pointe)
    return ("chemin", cible) if cible is not None else ("absent", pointe)


def scanner() -> dict:
    mods = modules()
    # Ce que l'instrument N'A PAS PU LIRE. Trois etats, jamais deux : present, absent,
    # illisible. Sans cette liste, un denominateur muet surestime la couverture.
    illisibles = []
    # IDENTITE et RESOLUTION sont deux choses distinctes (2026-09-07).
    #
    # Avant : `par_nom.setdefault(p.stem, p)` -- un seul noeud par NOM DE BASE, le
    # premier rencontre, sans trace de la collision. Mesure : 2 415 fichiers pour
    # 1 961 noeuds, donc 454 fichiers sans identite propre. Et `app/agents/core.py`
    # publiait « importe par 43 module(s) » alors qu'AUCUN import qualifie ne le vise :
    # les 43 venaient d'`import core` nus, rattaches au gagnant du setdefault, pendant
    # que `app/netcfg/core.py` -- qui a un importeur reel -- n'avait aucun noeud.
    # Un graphe qui fusionne deux organes attribue une capacite au mauvais.
    #
    # ⚠️ La clef de RESOLUTION reste le nom : Python resout ses imports par nom, pas
    # par chemin. On garde donc les deux, separees, et on N'INVENTE PAS de vainqueur
    # quand un nom designe plusieurs fichiers -- l'attribution devient AMBIGUE et le
    # dit. Cf. `test_aucune_nouvelle_collision_de_nom` : les collisions de RACINE sont
    # deja gelees et mesurees (contenus divergents, jusqu'a x52) ; ici il s'agit du
    # graphe, pas de l'import.
    par_chemin: dict[str, Path] = {
        str(p.relative_to(ROOT)).replace("\\", "/"): p for p in mods}
    candidats: dict[str, list] = {}
    for p in mods:
        candidats.setdefault(p.stem, []).append(p)
    ambigus = {n for n, v in candidats.items() if len(v) > 1}
    par_nom: dict[str, Path] = {n: v[0] for n, v in candidats.items()}

    index_pointes = _index_pointes(mods)
    # DEUX registres, parce qu'il y a deux natures d'arete. Celui par CHEMIN porte des
    # aretes prouvees (ID-03) ; celui par NOM porte des aretes qui dependent de
    # l'unicite du nom. Les melanger, c'est reperdre la distinction qu'on vient de payer.
    importe_par_chemin: dict[str, set] = {rel: set() for rel in par_chemin}
    importe_par: dict[str, set] = {m: set() for m in par_nom}
    cite_par: dict[str, set] = {m: set() for m in par_nom}
    a_main: set = set()
    sans_doc: set = set()

    for p in mods:
        _rel_p = str(p.relative_to(ROOT)).replace("\\", "/")
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            arbre = ast.parse(src)
        except (OSError, SyntaxError) as err:
            # ILLISIBLE n'est pas ABSENT. Un module qui ne parse pas disparaissait du
            # graphe SANS TRACE : l'instrument charge de dire ce qui existe repondait
            # "il n'y a rien" la ou il fallait lire "je n'ai pas pu voir". On le compte
            # et on le NOMME -- un denominateur muet surestime la couverture.
            illisibles.append({"chemin": _rel_p,
                               "motif": "%s: %s" % (type(err).__name__, err)})
            continue
        # Proprietes PAR FICHIER : elles se clefent par CHEMIN, pas par nom. Deux
        # fichiers homonymes n'ont ni la meme docstring ni le meme point d'entree ;
        # les indexer par `stem` faisait deteindre l'un sur l'autre.
        _rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if not (ast.get_docstring(arbre) or "").strip():
            sans_doc.add(_rel)
        if "__main__" in src and "if __name__" in src:
            a_main.add(_rel)
        for n in ast.walk(arbre):
            pointes = []
            if isinstance(n, ast.Import):
                pointes = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                if n.level or 0:
                    genre, cible = _resoudre_relatif(
                        _rel, n.level, n.module, index_pointes)
                    if genre == "chemin" and cible != _rel:
                        importe_par_chemin[cible].add(_rel)
                    continue
                pointes = [n.module] if n.module else []
            for pointe in pointes:
                genre, cible = _resoudre_import(pointe, index_pointes)
                if genre == "chemin":
                    if cible != _rel:
                        importe_par_chemin[cible].add(_rel)
                elif genre == "nom" and cible in importe_par and cible != p.stem:
                    # L'IMPORTEUR aussi a une identite : `add(p.stem)` fusionnait trois
                    # importeurs homonymes en un seul, donc SOUS-comptait les aretes.
                    importe_par[cible].add(_rel)
        # Citation par NOM (handler passe en chaine, registre, dispatch
        # dynamique). On EXTRAIT les noms cites une fois, au lieu de tester les
        # 2 307 modules connus dans chaque fichier : la version naive faisait
        # 5,3 millions de recherches de sous-chaine et ne rendait jamais.
        for _m in re.finditer(r"\b([A-Za-z_]\w*)\.py\b", src):
            autre = _m.group(1)
            if autre != p.stem and autre in cite_par:
                cite_par[autre].add(_rel)

    declaratif = _texte_declaratif(illisibles)
    tests = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in (ROOT / "tests").glob("**/*.py")
    ) if (ROOT / "tests").is_dir() else ""

    _illisible_par_chemin = {x["chemin"]: x["motif"] for x in illisibles
                             if x.get("phase") != "declaratif"}
    fiches = []
    for rel, chemin in sorted(par_chemin.items()):
        nom = chemin.stem
        ambigu = nom in ambigus
        voies = []
        # Les aretes ci-dessous sont resolues par NOM. Quand le nom designe plusieurs
        # fichiers, on ne sait PAS auquel elles reviennent : on s'abstient au lieu de
        # les offrir au premier venu. C'est ce qui faisait publier « importe par 43
        # module(s) » sur `app/agents/core.py`, qui n'a aucun importeur qualifie.
        # ID-03 : une arete QUALIFIEE designe un CHEMIN, donc une identite. Elle est
        # attribuable meme quand le nom est ambigu -- c'est tout l'interet de separer
        # la clef de resolution de l'identite. Sans cette ligne, `app/netcfg/core.py`
        # perdrait son importeur REEL par la faute d'un homonyme dans un autre organe.
        _qual = importe_par_chemin.get(rel) or set()
        if _qual:
            voies.append(f"importe par {len(_qual)} module(s) (import qualifie)")
        if not ambigu:
            if importe_par[nom]:
                voies.append(f"importe par {len(importe_par[nom])} module(s)")
            if cite_par[nom]:
                voies.append(f"cite par {len(cite_par[nom])} module(s)")
            if f"{nom}.py" in declaratif or f'"{nom}"' in declaratif:
                voies.append("declare (service/lanceur/tache)")
        # Le point d'entree, lui, est une propriete DU FICHIER : toujours attribuable.
        if rel in a_main:
            voies.append("point d'entree __main__")
        if voies:
            etat = "BRANCHE"
        elif rel in _illisible_par_chemin:
            # Un fichier qu'on n'a PAS PU LIRE ressortait `ORPHELIN` -- soit une
            # affirmation POSITIVE (« il existe et rien ne l'atteint ») sur un fichier
            # dont on ignore tout. `UNKNOWN` n'est pas `NO` : il n'a produit aucune
            # arete parce qu'il n'a pas ete analyse, pas parce qu'il n'en a aucune.
            etat = "ILLISIBLE"
        elif ambigu:
            etat = "AMBIGU"          # ni branche ni orphelin : NON RESOLU
        else:
            etat = "ORPHELIN"
        if etat == "ORPHELIN" and rel in a_main:
            etat = "POINT_ENTREE"
        fiche = {
            "module": nom,
            "chemin": rel,
            "etat": etat,
            "voies": voies,
            "illisible": _illisible_par_chemin.get(rel),
            # Une identite ambigue est VISIBLE mais NON ROUTABLE : un selecteur de
            # capacite ne doit jamais choisir un module qu'on ne sait pas designer.
            # Le drapeau est EXPLICITE -- une absence se relit comme un oubli.
            "routable": not ambigu,
            "importateurs_qualifies": sorted(_qual)[:5],
            "importateurs": [] if ambigu else sorted(importe_par[nom])[:5],
            "defini": rel not in sans_doc,
            "teste": (f"{nom}." in tests) or (f"{nom}\b" in tests) or (nom in tests),
        }
        if ambigu:
            fiche["ambiguite"] = {
                "nom": nom,
                "candidats": sorted(
                    str(c.relative_to(ROOT)).replace("\\", "/") for c in candidats[nom]),
                "motif": "aretes resolues par nom : non attribuables a un fichier precis",
            }
        fiches.append(fiche)
    return {"total": len(fiches), "fiches": fiches,
            "noms_ambigus": sorted(ambigus),
            "illisibles": illisibles,
            # Le statut VOYAGE avec l'artefact. S'il reste dans le module, il se perd
            # des qu'un consommateur lit le json -- et le garde-fou disparait a
            # l'agregation, exactement comme `routable` l'aurait fait.
            "certification": CERTIFICATION}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--orphelins", action="store_true", help="ne lister que les orphelins")
    a = ap.parse_args()

    res = scanner()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0

    f = res["fiches"]
    par_etat: dict[str, int] = {}
    for x in f:
        par_etat[x["etat"]] = par_etat.get(x["etat"], 0) + 1
    definis = sum(1 for x in f if x["defini"])
    testes = sum(1 for x in f if x["teste"])
    print(f"[wiring] {res['total']} modules — " +
          " · ".join(f"{k}={v}" for k, v in sorted(par_etat.items())))
    print(f"[wiring] definis (docstring) : {definis} · cites par un test : {testes}\n")

    orphelins = [x for x in f if x["etat"] == "ORPHELIN"]
    print(f"[wiring] ORPHELINS ({len(orphelins)}) — aucune voie ne les atteint :")
    for x in orphelins[:60]:
        manques = []
        if not x["defini"]:
            manques.append("sans docstring")
        if not x["teste"]:
            manques.append("sans test")
        print(f"   {x['chemin']:58s} {', '.join(manques) or '-'}")
    if len(orphelins) > 60:
        print(f"   ... {len(orphelins) - 60} autres (--json pour tout)")
    if not a.orphelins:
        # Le trio complet manquant est le signal le plus fort : ni appele, ni
        # defini, ni teste — personne ne saurait dire ce que fait ce fichier.
        muets = [x for x in orphelins if not x["defini"] and not x["teste"]]
        print(f"\n[wiring] NI BRANCHE NI DEFINI NI TESTE : {len(muets)}")
        for x in muets[:25]:
            print(f"   {x['chemin']}")
    print(f"\n[wiring] -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
