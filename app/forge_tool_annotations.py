"""Annotations de comportement des tools MCP (spec 2026-07-28, champ `annotations`).

__FORGE_COLOR__ = "immunitaire/lisibilite-des-effets"

CE QUE CE MODULE EST -- ET CE QU'IL N'EST PAS
=============================================
Il DECLARE, pour chaque tool du catalogue, ce que l'appel fait a l'environnement :
lit-il seulement, peut-il detruire, peut-on le rejouer sans dommage, touche-t-il
un monde exterieur. C'est la reponse a une question que le catalogue ne repondait
pas : `run` et `read` s'y presentaient avec la meme neutralite.

**Ce n'est PAS un garde.** La spec MCP le dit d'elle-meme : les annotations sont
des INDICES, un client ne doit fonder aucune decision de securite dessus, parce
qu'elles sont declarees par le serveur et qu'un serveur peut mentir. Ici le
serveur est souverain, donc elles sont sinceres -- mais sinceres n'est pas
BLOQUANT. Ce qui bloque reste le videur (ring), `forge_tool_gate`, le firewall
d'egress et les guards d'action. Confondre les deux, ce serait ranger ce module
parmi les securites alors qu'il est une signaletique : exactement le motif
"ne jamais confondre l'existence d'un mecanisme avec son effet reel".

Ce que ce module APPORTE de verifiable, en revanche : une declaration explicite
peut etre CONTREDITE par une mesure. `incoherences()` croise chaque annotation
avec le ring exige par le meme tool -- un tool declare en lecture seule mais qui
exige le ring le plus haut est une contradiction a instruire, jamais a taire.
Une annotation sans ce croisement ne serait qu'une opinion de plus.

SEMANTIQUE (spec MCP, defauts inclus -- ils comptent)
-----------------------------------------------------
- `readOnlyHint`    (defaut false) : l'appel ne modifie pas son environnement.
- `destructiveHint` (defaut **true**) : l'appel peut detruire ou ecraser. N'a de
  sens que si `readOnlyHint` est false. Le defaut est le PIRE cas : un tool non
  annote est presume destructeur, ce qui est la bonne facon de se tromper.
- `idempotentHint`  (defaut false) : rejouer avec les memes arguments n'ajoute
  aucun effet. N'a de sens que si `readOnlyHint` est false.
- `openWorldHint`   (defaut true) : l'appel touche des entites exterieures
  (reseau, fournisseur tiers, depot distant). false = domaine ferme et local.

Convention interne : pour un tool en lecture seule, on n'ecrit ni
`destructiveHint` ni `idempotentHint` -- la spec les dit sans objet dans ce cas,
et les poser inviterait a les lire comme des faits.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "ANNOTATIONS",
    "annotation_de",
    "annoter",
    "couverture",
    "incoherences",
    "RING_SENSIBLE",
]

# Ring au-dela duquel un tool est repute sensible. Le videur rend 0 pour le plus
# privilegie : un tool exigeant 0 ou 1 touche au systeme.
RING_SENSIBLE = 1

# (readOnly, destructive, idempotent, openWorld, raison)
# `destructive` et `idempotent` valent None quand readOnly est True (sans objet).
_T = Tuple[bool, Optional[bool], Optional[bool], bool, str]

_TABLE: Dict[str, _T] = {
    # ---- lecture seule, domaine ferme -------------------------------------
    "blackboard_read_zone": (True, None, None, False, "lit une zone du blackboard"),
    "bundle": (True, None, None, False, "assemble un paquet de lecture"),
    "delegate_to_local_scout": (True, None, None, False, "recon locale, rend un digest"),
    "forge_deep_explore": (True, None, None, False, "recon locale deterministe, 0 ecriture"),
    "forge_list_dynamic_tools": (True, None, None, False, "enumere les tools dynamiques"),
    "forge_stats": (True, None, None, False, "compteurs du corps"),
    "get_file_skeleton": (True, None, None, False, "squelette AST d'un fichier"),
    "get_function_dependencies": (True, None, None, False, "graphe de dependances lu"),
    "graph_cve_propagate": (True, None, None, False, "propagation calculee, non persistee"),
    "graph_edge_score": (True, None, None, False, "score d'arete calcule"),
    "graph_ppr": (True, None, None, False, "PageRank personnalise, calcul pur"),
    "introspect": (True, None, None, False, "recherche lexicale dans le corps"),
    "md": (True, None, None, False, "lecture confinee de markdown"),
    "query_local_json": (True, None, None, False, "lecture d'un JSON local"),
    "read": (True, None, None, False, "lecture de fichier"),
    "read_function_body": (True, None, None, False, "lecture d'une fonction"),
    "search_local_file": (True, None, None, False, "recherche dans les fichiers locaux"),

    # ---- lecture seule, monde ouvert --------------------------------------
    "query_documentation": (True, None, None, True, "interroge de la doc, potentiellement distante"),
    "web_search": (True, None, None, True, "recherche web via SearXNG"),

    # ---- ecrit, non destructeur, rejouable ---------------------------------
    "agy_add_dir": (False, False, True, False, "ajoute un repertoire autorise a agy ; re-ajout sans effet"),
    "agy_config": (False, False, True, False, "lit ou pose une config agy ; meme valeur = meme etat"),
    "auto_test": (False, False, True, False, "execute la suite et ecrit un rapport, sans muter le code"),
    "blackboard_propose_fact": (False, False, True, False, "pose un fait sous une clef ; meme clef = remplacement"),
    "tool_scope": (False, False, True, False, "reduit ou retablit la vue du catalogue ; etat, pas action"),

    # ---- ecrit, non destructeur, NON rejouable (accumule) ------------------
    "absorb_rfc_knowledge": (False, False, False, True, "ingere une RFC : chaque appel ajoute des chunks"),
    "auto_ingest": (False, False, False, True, "ingestion : accumule dans le RAG"),
    "biblio": (False, False, False, True, "recherche bibliographique puis ingestion"),
    "crawl": (False, False, False, True, "crawl externe puis ecriture des pages"),
    "event": (False, False, False, False, "publie sur le bus : chaque appel ajoute un evenement"),
    "forge_trigger_audit": (False, False, False, False, "declenche un audit qui ecrit son rapport"),
    "memory": (False, False, False, False, "ecrit ou lit la memoire ; l'ecriture accumule"),
    "plan": (False, False, False, False, "produit un plan et le journalise"),
    "rag": (False, False, False, False, "search lit, mais les actions d'ingestion ecrivent"),
    "research_agent": (False, False, False, True, "recherche externe puis restitution ecrite"),
    "route_dt": (False, False, False, False, "route une tache : trace la decision"),
    "route_task": (False, False, False, False, "route une tache : trace la decision"),
    "task": (False, False, False, False, "assigne, reclame ou solde une tache"),
    "ask": (False, False, False, True, "interroge un fournisseur tiers : consomme du quota, sort du perimetre"),

    # ---- DESTRUCTEUR : peut ecraser, supprimer, ou changer l'etat du systeme
    "cross_platform_fs": (False, True, False, False, "operations de fichiers, suppression comprise"),
    "docker_action": (False, True, False, False, "cycle de vie de conteneurs : stop et suppression possibles"),
    "forge_call_dynamic": (False, True, False, False, "execute un tool forge quelconque : effet non borne a l'avance"),
    "forge_spawn_swarm": (False, True, False, False, "edition map-reduce multi-fichiers"),
    "github": (False, True, False, True, "operations sur un depot distant : pousse, ecrit, supprime"),
    "governed_edit": (False, True, False, False, "ecrit dans un fichier du depot : ecrase le contenu vise"),
    "hub": (False, True, False, False, "administration du hub, redemarrage compris"),
    "loop_orchestrate": (False, True, False, False, "boucle d'orchestration : execute des actions arbitraires"),
    "manage_forge_lifecycle": (False, True, False, False, "demarre et arrete des organes"),
    "netcfg": (False, True, False, True, "modifie la configuration reseau"),
    "nokido_ensure_service": (False, True, False, False, "demarre, arrete ou redemarre un service"),
    "oracle_python_repl": (False, True, False, False, "execute du Python arbitraire"),
    "orchestrate": (False, True, False, False, "enchaine des actions arbitraires"),
    "query": (False, True, False, False, "SQL arbitraire : un DELETE y passe comme un SELECT"),
    "react_orchestrate": (False, True, False, False, "boucle ReAct : execute des actions arbitraires"),
    "run": (False, True, False, True, "shell, python ou job detache : effet non borne"),
    "secret": (False, True, False, False, "manipule le coffre : ecrasement d'un secret possible"),
    "skill": (False, True, False, False, "execute une competence, dont l'effet n'est pas borne a l'avance"),
    "trigger_autonomous_evolution": (False, True, False, False, "declenche une auto-modification du corps"),
    "write": (False, True, False, False, "ecrit un fichier : ecrase l'existant"),
    "agy_run": (False, True, False, False, "execute agy : effet non borne (RBAC owner-only)"),
}

# Vue publique, au format attendu par la spec MCP.
ANNOTATIONS: Dict[str, Dict[str, Any]] = {}
for _nom, (_ro, _de, _id, _ow, _raison) in _TABLE.items():
    _a: Dict[str, Any] = {"readOnlyHint": _ro, "openWorldHint": _ow}
    if not _ro:
        _a["destructiveHint"] = bool(_de)
        _a["idempotentHint"] = bool(_id)
    ANNOTATIONS[_nom] = _a


def raison(nom: str) -> str:
    """Pourquoi ce tool est classe ainsi. Vide si inconnu."""
    entry = _TABLE.get(nom)
    return entry[4] if entry else ""


def annotation_de(nom: str) -> Optional[Dict[str, Any]]:
    """Annotation d'un tool, ou None s'il n'est pas classe.

    None et « pas d'effet » sont deux choses differentes : un tool non classe est
    presume DESTRUCTEUR par le defaut de la spec. Ne jamais rendre un dict vide
    ici, il se lirait comme une innocuite mesuree.
    """
    a = ANNOTATIONS.get(nom)
    return dict(a) if a is not None else None


def annoter(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Injecte `annotations` dans chaque tool du catalogue.

    Non destructif : une annotation deja presente dans la declaration du tool
    l'emporte -- la table ici est un defaut, pas une autorite qui ecrase.
    Un tool absent de la table est laisse SANS annotation : la spec le rendra
    alors destructeur par defaut, ce qui vaut mieux qu'une innocuite inventee.
    """
    sortie: List[Dict[str, Any]] = []
    for t in tools:
        nom = t.get("name")
        if not isinstance(nom, str) or t.get("annotations"):
            sortie.append(t)
            continue
        a = ANNOTATIONS.get(nom)
        if a is None:
            sortie.append(t)
            continue
        t2 = dict(t)
        t2["annotations"] = dict(a)
        sortie.append(t2)
    return sortie


def couverture(noms_catalogue: List[str]) -> Dict[str, Any]:
    """Qui est annote, qui ne l'est pas, et qui est annote pour rien.

    Les deux ecarts comptent, et pas pour la meme raison :
    - `manquants` : des tools que le catalogue expose sans dire ce qu'ils font ;
    - `orphelins` : des annotations qui survivent a leur tool -- signe d'un
      renommage ou d'un retrait, donc d'une table qui derive du reel.
    """
    presents = set(n for n in noms_catalogue if isinstance(n, str))
    connus = set(ANNOTATIONS)
    manquants = sorted(presents - connus)
    orphelins = sorted(connus - presents)
    return {
        "catalogue": len(presents),
        "annotes": len(presents & connus),
        "manquants": manquants,
        "orphelins": orphelins,
        "taux": (len(presents & connus) / len(presents)) if presents else None,
    }


# Ce qu'un appel de fonction TRAHIT du comportement reel d'un handler. La cle est
# le nom appele, la valeur la capacite qu'il implique. Deliberement court : on ne
# cherche pas a tout couvrir, on cherche a CONTREDIRE une declaration.
# ⚠️ Table volontairement ETROITE. Une premiere version comptait `get` comme un
# appel reseau : chaque `args.get('action')` — donc tout dict — ressortait en
# capacite `net`, et deux tools etaient accuses a tort. Elle comptait aussi
# `remove` comme destructeur : `os.remove(temp_path)`, qui est le nettoyage
# normal d'une ecriture atomique, accusait les memes.
# Un audit qui crie a faux se fait desarmer — c'est la regle du corps, et elle
# vaut d'abord pour l'audit qu'on ecrit soi-meme. On ne retient donc que des
# noms SANS homonyme courant, et le filtrage des temporaires est fait a part.
_CAPACITE_PAR_APPEL = {
    "Popen": "exec", "system": "exec", "check_output": "exec",
    "check_call": "exec", "create_subprocess_exec": "exec",
    "create_subprocess_shell": "exec",
    "write_text": "write", "write_bytes": "write",
    "unlink": "delete", "rmtree": "delete",
    "executemany": "sql",
    "urlopen": "net",
}
# Un effacement portant sur un fichier temporaire n'est pas une destruction : il
# termine une ecriture atomique (ecrire un temp, puis remplacer). L'accuser ferait
# passer pour destructeur tout tool qui ecrit proprement.
_INDICES_TEMPORAIRE = ("temp", "tmp", "_swap", ".part")


def _dire(message: str) -> None:
    """Journal qui ne leve JAMAIS.

    Un audit dont le chemin d'erreur peut echouer transforme une lecture ratee en
    plantage — c'est ce qui vient d'arriver ici. `stderr` d'abord, et si meme lui
    refuse, on abandonne en silence plutot que de propager : la valeur de retour
    (`{}`) porte deja l'information, le journal n'est qu'un supplement.
    """
    try:
        import sys as _s
        print(message, file=_s.stderr, flush=True)
    except Exception:  # noqa: BLE001  # muet-ok : le journal ne casse rien
        pass
# Capacites qui DEMENTENT une annotation de lecture seule.
_MUTANTES = {"exec", "write", "delete", "sql"}


def comportement_reel(chemin_registre: Optional[str] = None) -> Dict[str, List[str]]:
    """Ce que chaque handler FAIT, lu dans l'AST — pas ce qu'il declare.

    AF1 de la veille (`mcp-sec-audit`) : « auditer les serveurs MCP pour les
    capacites d'outil SUR-PRIVILEGIEES ». L'entree disait « on declare une portee,
    on ne la confronte pas » — c'etait a moitie faux : `incoherences()` confronte
    deja la declaration au RING. Ce qui manquait est la confrontation au CODE.

    La difference compte. Le ring dit qui a le droit d'appeler ; il ne dit pas ce
    que l'appel fait. Un tool annote en lecture seule, joignable a un ring severe
    (donc coherent au sens de `incoherences`), peut tout de meme ouvrir un
    subprocess — et rien ne le disait.

    ⚠️ Portee HONNETE de cette lecture : elle ne voit que les appels DIRECTS dans
    le corps du handler. Un effet obtenu via un module tiers ne ressort pas. Un
    handler absent du resultat n'est donc PAS prouve inoffensif — il est
    `non_mesurable`, jamais `sain`. C'est la meme regle que partout : on classe
    par liste BLANCHE.

    ⚠️⚠️ Et l'erreur symetrique, payee en ecrivant cette fonction : une table trop
    large accuse a tort. `get` comptait chaque `dict.get()` comme un appel reseau,
    `remove` comptait `os.remove(temp_path)` — le nettoyage d'une ecriture
    atomique — comme une destruction. Deux tools ont ete accuses avant que la
    verification ne rende le verdict a zero. Mieux vaut un detecteur qui rate
    qu'un detecteur qu'on desarme.
    """
    import ast as _ast
    from pathlib import Path as _Path

    chemin = _Path(chemin_registre) if chemin_registre else (
        _Path(__file__).resolve().parent / "forge_mcp_registry.py")
    try:
        arbre = _ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        # ⚠️ Ce bloc utilisait `logger`, qui n'existe PAS dans ce module : le
        # gestionnaire d'erreur LEVAIT lui-meme (`NameError`), et un registre
        # illisible faisait planter l'audit au lieu de rendre un vide declare.
        # Meme defaut que le garde RSS du wrapper de job, mort sur son propre
        # journal en 2026-09-06. La regle qui en decoule : un garde AGIT d'abord,
        # journalise ENSUITE, et son journal NE LEVE JAMAIS.
        _dire("[annotations] registre ILLISIBLE (%s: %s) — aucun comportement "
              "mesure ; ne pas lire ce vide comme une absence d'effet"
              % (type(exc).__name__, str(exc)[:90]))
        return {}

    faits: Dict[str, List[str]] = {}
    for noeud in _ast.walk(arbre):
        if not isinstance(noeud, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            continue
        if not noeud.name.startswith("handle_"):
            continue
        capacites = set()
        for n in _ast.walk(noeud):
            if not isinstance(n, _ast.Call):
                continue
            nom = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            cap = _CAPACITE_PAR_APPEL.get(nom)
            if not cap:
                continue
            if cap == "delete":
                cible = _ast.unparse(n.args[0]).lower() if n.args else ""
                if any(t in cible for t in _INDICES_TEMPORAIRE):
                    continue  # fin d'ecriture atomique, pas une destruction
            capacites.add(cap)
        if capacites:
            faits[noeud.name[len("handle_"):]] = sorted(capacites)
    return faits


def declaration_dementie(chemin_registre: Optional[str] = None) -> List[Dict[str, Any]]:
    """Tools dont l'ANNOTATION est contredite par le CODE.

    Le complement d'`incoherences()` : celle-ci confronte au ring, celle-la au
    comportement. Trois verdicts, jamais deux :

      `lecture_seule_dementie` : annote `readOnlyHint` et pourtant il execute,
                                 ecrit, supprime ou ecrit en base.
      `inoffensif_dementi`     : annote non destructeur alors qu'il supprime.
      `non_mesurable`          : aucun appel direct reconnu — l'effet peut passer
                                 par un module tiers. Ni sain ni fautif : INCONNU.
    """
    faits = comportement_reel(chemin_registre)
    out: List[Dict[str, Any]] = []
    for nom, a in sorted(ANNOTATIONS.items()):
        reel = faits.get(nom)
        if reel is None:
            out.append({"tool": nom, "type": "non_mesurable",
                        "detail": "aucun appel direct reconnu dans le handler ; "
                                  "un effet via un module tiers reste possible"})
            continue
        mutantes = sorted(set(reel) & _MUTANTES)
        if a.get("readOnlyHint") and mutantes:
            out.append({"tool": nom, "type": "lecture_seule_dementie",
                        "fait": reel, "detail": raison(nom)})
        if a.get("destructiveHint") is False and "delete" in reel:
            out.append({"tool": nom, "type": "inoffensif_dementi",
                        "fait": reel, "detail": raison(nom)})
    return out


def incoherences(ring_par_tool: Dict[str, int]) -> List[Dict[str, Any]]:
    """Contradictions entre ce qu'un tool DECLARE et ce que le videur EXIGE.

    Deux sens, et le second est le plus utile :

    - `lecture_seule_mais_privilegiee` : annote en lecture seule alors que le
      videur exige un ring sensible. Soit l'annotation ment, soit le ring est
      trop severe -- dans les deux cas quelqu'un se fie a une fausse indication.
    - `destructeur_mais_ouvert_a_tous` : annote destructeur et joignable au ring
      le plus permissif. C'est le cas qui coute cher.

    Un tool absent de `ring_par_tool` n'est PAS silencieusement conforme : il
    ressort en `ring_inconnu`. Sans cette troisieme categorie, une table de rings
    incomplete se lirait comme une absence de contradiction.
    """
    out: List[Dict[str, Any]] = []
    for nom, a in sorted(ANNOTATIONS.items()):
        if nom not in ring_par_tool:
            out.append({"tool": nom, "type": "ring_inconnu",
                        "detail": "aucun ring connu pour ce tool : non verifiable"})
            continue
        ring = ring_par_tool[nom]
        if a.get("readOnlyHint") and ring <= RING_SENSIBLE:
            out.append({"tool": nom, "type": "lecture_seule_mais_privilegiee",
                        "ring": ring, "detail": raison(nom)})
        if a.get("destructiveHint") and ring >= 4:
            out.append({"tool": nom, "type": "destructeur_mais_ouvert_a_tous",
                        "ring": ring, "detail": raison(nom)})
    return out
