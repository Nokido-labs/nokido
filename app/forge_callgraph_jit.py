#!/usr/bin/env python3
"""
app/forge_callgraph_jit.py — Call-graph fonction-level JIT (just-in-time).

Complète forge_graph_linker (résolution MODULE-level) par une analyse À LA
DEMANDE au niveau FONCTION, sans graphe persistant :
  - callees(func, file) : ce que la fonction APPELLE (AST de son corps).
  - callers(func)       : ce qui APPELLE la fonction (grep lexical ripgrep →
                          parse AST ciblé des SEULS fichiers qui matchent).

But : "comprendre l'impact d'une modif AVANT de la faire" — vision à rayons X
pour le planner. Lecture seule, déterministe, zéro graphe à maintenir.

CLI: python forge_callgraph_jit.py --selftest
"""
from __future__ import annotations

import ast
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
_SCAN_ROOTS = ("app", "tools")
_MAX_CALLER_FILES = 120
_DEP_CACHE: dict = {}
_DEP_CACHE_TTL = 60.0  # cache get_function_dependencies (grep+AST ~400ms) — TTL court


def _call_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _callees_in(node: ast.AST) -> list[str]:
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            nm = _call_name(n)
            if nm:
                names.add(nm)
    return sorted(names)


def callees(func_name: str, file_path: str) -> list[str]:
    """Fonctions appelées DANS func_name (parse AST du fichier donné)."""
    if not file_path:
        return []
    abs_path = file_path if os.path.isabs(file_path) else str(ROOT / file_path)
    try:
        tree = ast.parse(Path(abs_path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return _callees_in(node)
    return []


_RACINE_DEPOT: dict = {}


def _est_racine_depot(racine: Path) -> bool:
    """ROOT est-il LUI-MEME la racine d'un depot git ? Memorise par racine.

    Sinon `git grep` s'executerait dans un depot PARENT et exclurait les fichiers qu'il ignore : mesure du
    2026-10-18, un dossier de test sous sandbox/ (ignore) rendait une liste VIDE -- 12 NR rouges."""
    cle = str(racine)
    if cle not in _RACINE_DEPOT:
        try:
            r = subprocess.run(["git", "-c", "safe.directory=*", "-C", cle, "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            _RACINE_DEPOT[cle] = (r.returncode == 0 and
                                  Path(r.stdout.strip()).resolve() == Path(racine).resolve())
        except (OSError, subprocess.SubprocessError):
            _RACINE_DEPOT[cle] = False
    return _RACINE_DEPOT[cle]


def _git_grep_files(needle: str) -> "list[str] | None":
    """`git grep` natif : fichiers .py (suivis ET non suivis, hors ignores) contenant `needle` ; None si git est
    indisponible ou si ROOT n'est pas la racine d'un depot -- le repli Python prend alors le relais."""
    rels = [r for r in _SCAN_ROOTS if (ROOT / r).exists()]
    if not rels:
        return []
    if not _est_racine_depot(ROOT):
        return None
    try:
        g = subprocess.run(
            ["git", "-c", "safe.directory=*", "-c", "core.quotepath=off", "-C", str(ROOT), "grep", "-l", "-F",
             "--untracked", "-e", needle, "--", *rels],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if g.returncode not in (0, 1):
        return None
    return [str(ROOT / l.strip()) for l in g.stdout.splitlines() if l.strip().endswith(".py")]


def _git_grep_lignes(needle: str) -> "dict[str, list[str]] | None":
    """{fichier .py: [lignes contenant `needle`]} en UN `git grep -n` ; None si git est indisponible."""
    rels = [r for r in _SCAN_ROOTS if (ROOT / r).exists()]
    if not rels:
        return {}
    if not _est_racine_depot(ROOT):
        return None
    try:
        g = subprocess.run(
            ["git", "-c", "safe.directory=*", "-c", "core.quotepath=off", "-C", str(ROOT), "grep", "-n", "-F",
             "--untracked", "-e", needle, "--", *rels],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if g.returncode not in (0, 1):
        return None
    out: dict[str, list[str]] = {}
    for ligne in g.stdout.splitlines():
        chemin, _, reste = ligne.partition(":")
        if chemin.endswith(".py"):
            out.setdefault(str(ROOT / chemin), []).append(reste.partition(":")[2])
    return out


# `rg` est absent du poste (mesure 18/10) : le sonder a CHAQUE appel creait un processus pour rien. Sonde unique
# par processus ; {} = pas encore sonde.
_RG_ABSENT: dict = {}


def _rg_disponible() -> bool:
    if "absent" not in _RG_ABSENT:
        try:
            subprocess.run(["rg", "--version"], capture_output=True, text=True, timeout=10, errors="replace")
            _RG_ABSENT["absent"] = False
        except (OSError, subprocess.SubprocessError):
            _RG_ABSENT["absent"] = True
    return not _RG_ABSENT["absent"]


def _grep_def_et_usages(func_name: str) -> tuple:
    """(fichiers ou `def <nom>` apparait, fichiers ou `<nom>` apparait) -- UN seul `git grep -n` sans ripgrep.

    Avant le 18/10 : `definitions()` greppait `def <nom>` et `callers()` `<nom>`, deux sous-processus par symbole
    alors que le premier ensemble est INCLUS dans le second. Les lignes rendues suffisent a les separer, sans
    tronquer avant le tri (un `max_files` sur le grep elargi aurait perdu des definitions des noms tres utilises).
    """
    if not _rg_disponible():
        lignes = _git_grep_lignes(func_name)
        if lignes is not None:
            motif = "def " + func_name
            return [f for f, ls in lignes.items() if any(motif in l for l in ls)], list(lignes)
    return _grep_files("def " + func_name), _grep_files(func_name)


def prefiltre_definitions(mots) -> "dict[str, list[str]] | None":
    """{mot: fichiers ou `def <mot>` apparait} pour TOUS les mots en UN `git grep -n` ; None si git indisponible.

    Mesure du 18/10 (job_38a1e6d83854) : introspect lancait 6 a 9 git grep par appel (~0,9 s), un `def <mot>` par
    mot CANDIDAT de la question, alors que la plupart ne sont pas des symboles. Un mot sans ligne rend [] : il n'est
    defini nulle part (l'appelant ne relance rien) ; None seulement si le grep lui-meme n'a pas pu tourner.
    """
    mots = [m for m in dict.fromkeys(mots) if m]
    if not mots:
        return {}
    rels = [r for r in _SCAN_ROOTS if (ROOT / r).exists()]
    if not rels or not _est_racine_depot(ROOT):
        return None
    motifs = []
    for m in mots:
        motifs += ["-e", "def " + m]
    try:
        g = subprocess.run(
            ["git", "-c", "safe.directory=*", "-c", "core.quotepath=off", "-C", str(ROOT), "grep", "-n", "-F",
             "--untracked", *motifs, "--", *rels],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if g.returncode not in (0, 1):
        return None
    out: dict[str, list[str]] = {m: [] for m in mots}
    for ligne in g.stdout.splitlines():
        chemin, _, reste = ligne.partition(":")
        if not chemin.endswith(".py"):
            continue
        texte = reste.partition(":")[2]
        f = str(ROOT / chemin)
        for m in mots:
            if ("def " + m) in texte and f not in out[m]:
                out[m].append(f)
    return out


def _grep_files(needle: str) -> list[str]:
    """Fichiers .py contenant `needle` : ripgrep si dispo, sinon `git grep` natif, sinon os.walk + lecture.

    Mesure du 2026-10-18 (cProfile d'introspect) : ripgrep absent du poste -> le repli Python relisait tout
    app/ + tools/ A CHAQUE appel (63 259 lectures pour 3 questions, 8,2 s de read_text). `git grep` est
    l'outil natif deja present : memes fichiers (suivis + non suivis), aucune lecture en Python."""
    roots = [str(ROOT / r) for r in _SCAN_ROOTS if (ROOT / r).exists()]
    if not roots:
        return []
    if _rg_disponible():
        try:
            rg = subprocess.run(
                ["rg", "-l", "--no-messages", "-t", "py", needle, *roots],
                capture_output=True, text=True, timeout=20,
            errors="replace")
            if rg.returncode in (0, 1):
                return [l.strip() for l in rg.stdout.splitlines()
                        if l.strip().endswith(".py")]
        except (OSError, subprocess.SubprocessError):
            pass  # muet-ok : ripgrep en erreur -- git grep puis le repli Python prennent le relais
    natif = _git_grep_files(needle)
    if natif is not None:
        return natif
    # fallback : os.walk + lecture (ni rg ni git)
    hits: list[str] = []
    for r in _SCAN_ROOTS:
        base = ROOT / r
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            try:
                if needle in p.read_text(encoding="utf-8", errors="replace"):
                    hits.append(str(p))
            except OSError:
                pass  # muet-ok : fichier disparu ou verrouille pendant le parcours, rien de lisible a y chercher
    return hits


# INDEX PAR FICHIER, en cache sur (mtime_ns, taille). Reprofil du 2026-10-18 a cache chaud : callers re-parsait
# les fichiers candidats et re-parcourait CHAQUE fonction a chaque appel (8,2 s sur 11 pour 3 questions ; les
# fonctions imbriquees parcourues plusieurs fois). L'index garde, par fonction, les noms APPELES et les noms LUS
# de son sous-arbre : semantique IDENTIQUE a _local_aliases + _ref_kind (NR test_callgraph_index_nr). Un fichier
# modifie change de mtime/taille et il est reindexe au passage suivant.
_INDEX_CACHE: dict = {}

# L'INDEX SUR DISQUE : la memoire meurt avec le processus, l'index lui survit. Le premier _index_fichier du
# processus relit _CACHE_DISQUE (drapeau _CACHE_CHARGE) ; un fichier dont (mtime, taille) n'a pas bouge n'est
# pas re-parse au demarrage suivant -- cout a froid mesure 6,9 s de re-indexation sur 13,65 s (profil 18/10).
# Integre depuis 332030813 (NEMOTRON, GREEN de c8072bbe9).
_CACHE_DISQUE: Path = ROOT / "sandbox" / "cache" / "callgraph_index.json"
_CACHE_CHARGE = False           # le disque a-t-il ete consulte (y compris "fichier absent") ?
_CACHE_MODIFIES: set = set()    # fichiers indexes depuis le dernier chargement/ecriture


def _idx_vers_json(idx) -> object:
    """Index -> JSON : set/frozenset deviennent des listes triees (JSON n'a ni set, ni tuple, ni frozenset)."""
    if idx is None:
        return None  # fichier casse : l'entree None se persiste aussi
    return {"alias": {k: sorted(v) for k, v in idx["alias"].items()},
            "fonctions": [[n, l, sorted(a), sorted(u)] for n, l, a, u in idx["fonctions"]],
            "defs": [[c, n, l] for c, n, l in idx["defs"]]}


def _idx_depuis_json(d) -> "dict | None":
    """JSON -> index aux TYPES EXACTS d'un index calcule : alias en set, appels/lus en frozenset, entrees en
    tuple -- sinon l'index relu n'est PAS egal a l'index calcule (egalite Python stricte)."""
    if d is None:
        return None
    return {"alias": {k: set(v) for k, v in d["alias"].items()},
            "fonctions": [(n, l, frozenset(a), frozenset(u)) for n, l, a, u in d["fonctions"]],
            "defs": [(c, n, l) for c, n, l in d["defs"]]}


def _charger_cache_disque() -> None:
    """Charge _CACHE_DISQUE dans _INDEX_CACHE, UNE fois par processus (drapeau _CACHE_CHARGE).

    Fichier absent -> rien, sans relancer de lecture. Illisible ou corrompu -> logger.warning qui le DIT, puis
    cache vide : jamais d'exception, l'index se recalcule a la demande comme avant le cache."""
    global _CACHE_CHARGE
    if _CACHE_CHARGE:
        return
    _CACHE_CHARGE = True
    try:
        texte = Path(_CACHE_DISQUE).read_text(encoding="utf-8")
    except FileNotFoundError:
        return  # rien a charger, pas une erreur
    except OSError as exc:
        logger.warning("cache callgraph illisible (%s) : %s -- ignore, index recalcule", _CACHE_DISQUE, exc)
        return
    try:
        brut = json.loads(texte)
    except ValueError as exc:
        logger.warning("cache callgraph CORROMPU (%s) : %s -- ignore, index vide, recalcule",
                       _CACHE_DISQUE, exc)
        return
    entrees = brut.get("entrees") if isinstance(brut, dict) else None
    if not isinstance(entrees, dict):
        logger.warning("cache callgraph CORROMPU (%s) : structure inattendue -- ignore, index vide, recalcule",
                       _CACHE_DISQUE)
        return
    for fp, val in entrees.items():
        try:
            mtime, taille, idx = val
            _INDEX_CACHE[fp] = (int(mtime), int(taille), _idx_depuis_json(idx))
        except (TypeError, ValueError, KeyError) as exc:
            logger.warning("cache callgraph : entree corrompue pour %r (%s) -- ignoree", fp, exc)


def _persister_index() -> None:
    """Ecrit _INDEX_CACHE dans _CACHE_DISQUE : ecriture atomique (.tmp puis os.replace), mkdir parents, et
    SEULEMENT si une entree a change depuis le dernier chargement/ecriture. Echec d'ecriture ->
    logger.warning, jamais d'exception (l'index reste en memoire, il sera reecrit au passage suivant)."""
    if not _CACHE_MODIFIES:
        return
    cible = Path(_CACHE_DISQUE)
    entrees = {fp: [mtime, taille, _idx_vers_json(idx)]
               for fp, (mtime, taille, idx) in _INDEX_CACHE.items()}
    try:
        cible.parent.mkdir(parents=True, exist_ok=True)
        tmp = cible.with_name(cible.name + ".tmp")
        tmp.write_text(json.dumps({"version": 1, "entrees": entrees}, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, cible)
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("cache callgraph non ecrit (%s) : %s -- index conserve en memoire", cible, exc)
        return
    _CACHE_MODIFIES.clear()


def _indexer_arbre(tree: ast.AST) -> dict:
    alias: dict = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.asname:
                    alias.setdefault(a.name, set()).add(a.asname)
    fonctions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            appels, lus = set(), set()
            for n in ast.walk(node):
                if isinstance(n, ast.Call):
                    nom = _call_name(n)
                    if nom:
                        appels.add(nom)
                elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    lus.add(n.id)
            fonctions.append((node.name, node.lineno, frozenset(appels), frozenset(lus)))
    defs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for corps in node.body:
                if isinstance(corps, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs.append((node.name, corps.name, corps.lineno))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append((None, node.name, node.lineno))
    return {"alias": alias, "fonctions": fonctions, "defs": defs}


def _index_fichier(fp: str) -> "dict | None":
    """Index du fichier (cache par mtime/taille) ; None si illisible ou syntaxe invalide -- memorise aussi,
    pour ne pas re-tenter le meme fichier casse a chaque appel. Relit le disque au premier appel du processus."""
    if not _CACHE_CHARGE:
        _charger_cache_disque()
    try:
        st = os.stat(fp)
    except OSError:
        return None
    connu = _INDEX_CACHE.get(fp)
    if connu is not None and connu[0] == st.st_mtime_ns and connu[1] == st.st_size:
        return connu[2]
    try:
        idx = _indexer_arbre(ast.parse(Path(fp).read_text(encoding="utf-8", errors="replace")))
    except (OSError, SyntaxError):
        idx = None
    _INDEX_CACHE[fp] = (st.st_mtime_ns, st.st_size, idx)
    _CACHE_MODIFIES.add(fp)  # une entree a change : a ecrire au prochain _persister_index
    return idx


def _local_aliases(tree: ast.AST, func_name: str) -> set[str]:
    """Noms locaux qui désignent func_name dans ce fichier (résout les alias
    d'import `from X import func_name as _f` → {_f} comptent comme func_name)."""
    aliases = {func_name}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name == func_name and a.asname:
                    aliases.add(a.asname)
    return aliases


def _ref_kind(node: ast.AST, targets: set[str]) -> str | None:
    """Comment `node` (corps d'une fonction) référence une cible :
    'call' = appel direct (target(...) ou obj.target(...)) ;
    'ref'  = nom passé en argument / assigné (ex: to_thread(target, ...)) ;
    None   = aucune référence."""
    via = None
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and _call_name(n) in targets:
            return "call"
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in targets:
            via = "ref"  # réf (passé en arg / assigné), pas un appel direct
    return via


# Trois etats, jamais deux. « Pas d'ambiguite » et « je n'ai pas trouve la
# definition » demandent des actions opposees : la premiere autorise a agir, la
# seconde interdit de conclure.
RESOLU, AMBIGU, ILLISIBLE = "RESOLU", "AMBIGU", "ILLISIBLE"


def definitions(func_name: str, max_files: int = _MAX_CALLER_FILES, fichiers=None) -> list[dict]:
    """Ou ce nom est-il DEFINI ? [{file, classe|None, line}].

    JIT comme le reste du module : grep d'abord (`def <nom>`), AST ensuite sur
    les seuls fichiers qui matchent. Pas de graphe persistant a maintenir.
    `fichiers` : candidats deja greppes par l'appelant (callers), pour ne pas relancer git.
    """
    out: list[dict] = []
    for fp in (fichiers if fichiers is not None else _grep_files("def " + func_name))[:max_files]:
        idx = _index_fichier(fp)
        if idx is None:
            continue  # muet-ok : fichier illisible ou syntaxe invalide, ignore comme avant
        rel = os.path.relpath(fp, ROOT).replace("\\", "/")
        for classe, nom, ligne in idx["defs"]:   # methodes de classe puis definitions de MODULE
            if nom == func_name:
                out.append({"file": rel, "classe": classe, "line": ligne})
    _persister_index()
    return out


def ambiguite(func_name: str, fichiers_def=None) -> dict:
    """L'attribution de `callers(func_name)` est-elle sure ?

    POURQUOI (mesure 2026-08-31, debat CLAUDE<->AGY sur l'index structurel).
    `_call_name` rend `f.attr` pour un `ast.Attribute` : le nom de la methode
    SANS son receveur. Quand plusieurs classes definissent le meme nom, chaque
    appelant est donc attribue AU HASARD parmi elles.

    Ce n'est pas une hypothese. Sur `app/` + `tools/` : 874 des 2322 noms de
    methode (37,6 %) sont definis par >= 2 classes, et 50,6 % des 109 972 appels
    `x.methode()` visent l'un de ces noms. Cas les plus couteux mesures :
    `get_tools` est defini par 87 classes et `callers()` rend 80 appelants ;
    `get_capabilities`, 86 classes pour 60 appelants.

    L'outil rendait ces listes SANS reserve. Un agent y lisait « 80 usages, ne
    supprime pas » ou « 0 usage, supprime » avec la meme confiance — alors que
    la reponse pouvait etre fausse dans les deux sens. Un outil qui se tait sur
    son incertitude est plus dangereux qu'un outil absent, parce qu'on agit
    dessus. Lever l'ambiguite demande une inference de type inter-fichier
    (index type SCIP) ; la DECLARER ne demande rien, et c'est ce qu'on fait ici.
    """
    defs = definitions(func_name, fichiers=fichiers_def)
    if not defs:
        return {"etat": ILLISIBLE, "classes": 0, "definie_par": [],
                "note": "aucune definition trouvee dans %s — l'attribution ne "
                        "peut etre ni confirmee ni infirmee" % (_SCAN_ROOTS,)}
    classes = [d for d in defs if d["classe"]]
    noms = sorted({"%s:%s" % (d["file"], d["classe"]) for d in classes})
    if len(noms) >= 2:
        return {"etat": AMBIGU, "classes": len(noms), "definie_par": noms[:12],
                "note": "%d classes definissent `%s` ; les appelants ci-dessous "
                        "sont attribues SANS distinguer laquelle est appelee. "
                        "Ne pas conclure a un usage ni a une absence d'usage "
                        "sur cette seule base." % (len(noms), func_name)}
    return {"etat": RESOLU, "classes": len(noms), "definie_par": noms,
            "note": "nom porte par une seule definition — attribution sure"}


def callers(func_name: str, max_files: int = _MAX_CALLER_FILES) -> list[dict]:
    """Fonctions (ailleurs) qui appellent OU référencent func_name. grep → AST ciblé.

    Résout les alias d'import (`func as _f`) ET détecte les refs passées en
    argument (`to_thread(func, ...)`) — sinon sous-comptage. Champ `via` =
    'call' (appel direct) ou 'ref' (passé/assigné). Un appel dans une fonction
    imbriquée est attribué à la fonction englobante (approximation impact).
    """
    out: list[dict] = []
    # L'etat d'ambiguite est calcule UNE fois et estampille sur chaque entree :
    # un appelant lu isolement doit porter la reserve avec lui.
    fichiers_def, fichiers = _grep_def_et_usages(func_name)
    etat = ambiguite(func_name, fichiers_def).get("etat", ILLISIBLE)
    for fp in fichiers[:max_files]:
        idx = _index_fichier(fp)
        if idx is None:
            continue  # muet-ok : fichier illisible ou syntaxe invalide, ignore comme avant
        cibles = {func_name} | idx["alias"].get(func_name, set())
        rel = os.path.relpath(fp, ROOT).replace("\\", "/")
        for nom, ligne, appels, lus in idx["fonctions"]:
            kind = "call" if appels & cibles else ("ref" if lus & cibles else None)
            if kind:
                out.append({"file": rel, "caller": nom, "line": ligne, "via": kind, "resolution": etat})
    _persister_index()
    return out


def get_function_dependencies(func_name: str, file_path: str = "") -> dict:
    """Vue amont (callers) + aval (callees) d'une fonction = impact d'une modif.
    Caché (TTL 60s) : grep+AST coûte ~400ms, souvent re-demandé sur la même cible."""
    import time as _t

    _k = (func_name, file_path)
    _h = _DEP_CACHE.get(_k)
    if _h and (_t.time() - _h[0]) < _DEP_CACHE_TTL:
        return _h[1]
    cing = callers(func_name)
    amb = ambiguite(func_name)
    res: dict = {
        "function": func_name,
        "file": file_path or None,
        "callees": callees(func_name, file_path) if file_path else [],
        "callers": cing,
        "callers_count": len(cing),
        # Le consommateur voit desormais la RESERVE en meme temps que le chiffre.
        # Sans elle, `callers_count: 80` se lit comme 80 usages certains.
        "ambiguite": amb,
    }
    if amb["etat"] == AMBIGU:
        res["avertissement"] = (
            "callers_count=%d n'est PAS un nombre d'usages de cette methode : "
            "%d classes portent ce nom." % (len(cing), amb["classes"]))
    if not file_path:
        res["note"] = "file_path absent → callees non calculés (parse du corps requis)"
    if len(_DEP_CACHE) > 128:
        _DEP_CACHE.clear()
    _DEP_CACHE[_k] = (_t.time(), res)
    return res


def _selftest() -> int:
    import json
    ce = callees("get_function_dependencies", "app/forge_callgraph_jit.py")
    assert "callers" in ce and "callees" in ce, ce
    cr = callers("callees")
    assert any(c["caller"] == "get_function_dependencies" for c in cr), cr
    full = get_function_dependencies("callees", "app/forge_callgraph_jit.py")
    print("SELFTEST OK", json.dumps(
        {"callees_of_gfd": ce, "callers_of_callees": len(cr),
         "sample_callers": full["callers"][:3]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
