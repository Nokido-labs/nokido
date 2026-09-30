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
import os
import subprocess
import sys
from pathlib import Path

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


def _grep_files(needle: str) -> list[str]:
    """Fichiers .py contenant `needle` (ripgrep si dispo, sinon os.walk)."""
    roots = [str(ROOT / r) for r in _SCAN_ROOTS if (ROOT / r).exists()]
    if not roots:
        return []
    try:
        rg = subprocess.run(
            ["rg", "-l", "--no-messages", "-t", "py", needle, *roots],
            capture_output=True, text=True, timeout=20,
        errors="replace")
        if rg.returncode in (0, 1):
            return [l.strip() for l in rg.stdout.splitlines()
                    if l.strip().endswith(".py")]
    except (OSError, subprocess.SubprocessError):
        pass
    # fallback : os.walk + lecture (rg absent)
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
                pass
    return hits


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


def definitions(func_name: str, max_files: int = _MAX_CALLER_FILES) -> list[dict]:
    """Ou ce nom est-il DEFINI ? [{file, classe|None, line}].

    JIT comme le reste du module : grep d'abord (`def <nom>`), AST ensuite sur
    les seuls fichiers qui matchent. Pas de graphe persistant a maintenir.
    """
    out: list[dict] = []
    for fp in _grep_files("def " + func_name)[:max_files]:
        try:
            tree = ast.parse(Path(fp).read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        rel = os.path.relpath(fp, ROOT).replace("\\", "/")
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for corps in node.body:
                    if (isinstance(corps, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and corps.name == func_name):
                        out.append({"file": rel, "classe": node.name,
                                    "line": corps.lineno})
        for node in tree.body:      # definition de MODULE (pas une methode)
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == func_name):
                out.append({"file": rel, "classe": None, "line": node.lineno})
    return out


def ambiguite(func_name: str) -> dict:
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
    defs = definitions(func_name)
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
    etat = ambiguite(func_name).get("etat", ILLISIBLE)
    for fp in _grep_files(func_name)[:max_files]:
        try:
            tree = ast.parse(Path(fp).read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        targets = _local_aliases(tree, func_name)
        rel = os.path.relpath(fp, ROOT).replace("\\", "/")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            kind = _ref_kind(node, targets)
            if kind:
                out.append({"file": rel, "caller": node.name, "line": node.lineno,
                            "via": kind, "resolution": etat})
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
