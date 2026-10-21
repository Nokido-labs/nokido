"""
forge_panorama_builder.py
=========================
Scan AST de app/forge_*.py pour extraire le vrai graphe d'imports internes,
puis genere un panorama Mermaid data-driven via forge_mermaid_gen.

Usage:
    from forge_panorama_builder import build_panorama
    result = build_panorama()  # {"mermaid": str, "nodes": [...], "edges": [...]}
"""

from __future__ import annotations
import ast
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"

# Racines virtuelles : fichiers qui importent forge_* sans etre des forge_*.py
# C'est crucial pour ne pas compter Nokido.py et mcp_server_tools.py comme orphelins
# (ils importent enormement mais le scan naif ne les voyait pas)
VIRTUAL_ROOTS = [
    APP_DIR / "Nokido.py",
    APP_DIR / "mcp_server_tools.py",
    APP_DIR / "bootstrap.py",
]


# Cache des imports PAR FICHIER, indexe sur (mtime_ns, taille). Mesure du 2026-10-18 (cProfile d'introspect) :
# scan_forge_modules RE-PARSAIT les ~1 190 modules a CHAQUE appel (ast.parse 5,7 s + ast.walk) -- 12 s sur 31.
# Ce n'est pas une carte figee : un fichier modifie change de mtime/taille et il est re-parse au passage
# suivant ; seul l'inchange est relu en memoire.
_IMPORTS_CACHE: Dict[str, tuple] = {}

# L'IMPORTS_CACHE SUR DISQUE (integre de 85cc404d9, NEMOTRON, GREEN de 9356d4517 ; mesure : scan 4 091 ms a froid ->
# 39 ms) : la memoire meurt avec le processus, ce cache lui survit. Le premier _extract_imports du processus relit
# _CACHE_DISQUE ; un fichier dont (mtime_ns, taille) n'a pas bouge n'est pas re-parse au demarrage suivant.
_CACHE_DISQUE: Path = ROOT / "sandbox" / "cache" / "panorama_imports.json"
_CACHE_CHARGE = False           # le disque a-t-il ete consulte (y compris "fichier absent") ?
_CACHE_MODIFIES: set = set()    # fichiers recalcules depuis le dernier chargement/ecriture


def _charger_cache_disque() -> None:
    """Charge _CACHE_DISQUE dans _IMPORTS_CACHE, UNE fois par processus. Format {chemin: [mtime_ns, taille, [imports]]}.
    Absent -> rien ; illisible ou corrompu -> logger.warning qui le DIT, cache vide, jamais d'exception."""
    global _CACHE_CHARGE
    if _CACHE_CHARGE:
        return
    _CACHE_CHARGE = True
    try:
        texte = Path(_CACHE_DISQUE).read_text(encoding="utf-8")
    except FileNotFoundError:
        return  # rien a charger, pas une erreur
    except OSError as exc:
        logger.warning("cache panorama illisible (%s) : %s -- ignore, imports recalcules", _CACHE_DISQUE, exc)
        return
    try:
        brut = json.loads(texte)
    except ValueError as exc:
        logger.warning("cache panorama CORROMPU (%s) : %s -- ignore, cache vide, recalcule", _CACHE_DISQUE, exc)
        return
    if not isinstance(brut, dict):
        logger.warning("cache panorama CORROMPU (%s) : structure inattendue -- ignore, recalcule", _CACHE_DISQUE)
        return
    for chemin, val in brut.items():
        try:
            mtime, taille, imports = val
            _IMPORTS_CACHE[str(chemin)] = (int(mtime), int(taille), frozenset(imports))
        except (TypeError, ValueError, KeyError) as exc:
            logger.warning("cache panorama : entree corrompue pour %r (%s) -- ignoree", chemin, exc)


def _persister_imports() -> None:
    """Ecrit _IMPORTS_CACHE dans _CACHE_DISQUE (atomique : .tmp puis os.replace), seulement si une entree a ete
    recalculee. Echec d'ecriture -> logger.warning, jamais d'exception."""
    if not _CACHE_MODIFIES:
        return
    cible = Path(_CACHE_DISQUE)
    entrees = {chemin: [mtime, taille, sorted(imports)]
               for chemin, (mtime, taille, imports) in _IMPORTS_CACHE.items()}
    try:
        cible.parent.mkdir(parents=True, exist_ok=True)
        tmp = cible.with_name(cible.name + ".tmp")
        tmp.write_text(json.dumps(entrees, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, cible)
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("cache panorama non ecrit (%s) : %s -- imports conserves en memoire", cible, exc)
        return
    _CACHE_MODIFIES.clear()


def _extract_imports(py_path: Path) -> Set[str]:
    """Retourne les modules importes par py_path (top-level uniquement), via le cache par (mtime, taille).
    Le premier appel du processus relit d'abord le cache disque."""
    if not _CACHE_CHARGE:
        _charger_cache_disque()
    try:
        st = py_path.stat()
    except OSError:
        return set()
    cle = str(py_path)
    connu = _IMPORTS_CACHE.get(cle)
    if connu is not None and connu[0] == st.st_mtime_ns and connu[1] == st.st_size:
        return set(connu[2])
    mods = _extract_imports_brut(py_path)
    _IMPORTS_CACHE[cle] = (st.st_mtime_ns, st.st_size, frozenset(mods))
    _CACHE_MODIFIES.add(cle)  # une entree a change : a ecrire en fin de scan
    return set(mods)


def _extract_imports_brut(py_path: Path) -> Set[str]:
    """Parse reel (sans cache) : modules importes par py_path."""
    try:
        src = py_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src, filename=str(py_path))
    except (SyntaxError, OSError):
        return set()

    mods: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module.split(".")[0])
    return mods


def scan_forge_modules(include_virtual_roots: bool = True) -> Dict[str, Set[str]]:
    """Scanne app/forge_*.py et retourne {module: set(imports_internes)}.

    Si include_virtual_roots=True, ajoute aussi Nokido.py, mcp_server_tools.py
    et bootstrap.py comme racines virtuelles (ils importent forge_* sans etre
    eux-memes des forge_*.py). Crucial pour eviter les faux orphelins.
    """
    graph: Dict[str, Set[str]] = {}
    if not APP_DIR.is_dir():
        return graph

    # Modules Nokido internes detectables
    internal_names = {p.stem for p in APP_DIR.glob("forge_*.py")}

    for py_path in APP_DIR.glob("forge_*.py"):
        mod_name = py_path.stem
        all_imports = _extract_imports(py_path)
        internal_deps = all_imports & internal_names
        internal_deps.discard(mod_name)  # pas d'auto-reference
        graph[mod_name] = internal_deps

    # Ajouter racines virtuelles (Nokido.py, mcp_server_tools.py, bootstrap.py)
    if include_virtual_roots:
        for vroot in VIRTUAL_ROOTS:
            if not vroot.is_file():
                continue
            mod_name = vroot.stem  # "Nokido", "mcp_server_tools", "bootstrap"
            all_imports = _extract_imports(vroot)
            internal_deps = all_imports & internal_names
            graph[mod_name] = internal_deps

    # Persistance : seulement si au moins une entree a ete recalculee ; un echec est dit, jamais leve.
    _persister_imports()

    return graph


def compute_orphans(graph: Dict[str, Set[str]] = None) -> Dict[str, list]:
    """Calcule les orphelins reels (jamais importes nulle part).

    Returns:
        {
          "true_orphans": [...],   # 0 import sortant ET 0 importateur
          "leaves": [...],         # 0 import sortant mais importes (utilitaires)
          "roots": [...],          # importent mais jamais importes (entry points)
        }
    """
    if graph is None:
        graph = scan_forge_modules(include_virtual_roots=True)

    in_degree: Dict[str, int] = {m: 0 for m in graph}
    for mod, deps in graph.items():
        for d in deps:
            if d in in_degree:
                in_degree[d] += 1

    true_orphans = [m for m in graph if not graph[m] and in_degree[m] == 0]
    leaves = [m for m in graph if not graph[m] and in_degree[m] > 0]
    roots = [m for m in graph if graph[m] and in_degree[m] == 0]

    return {
        "true_orphans": sorted(true_orphans),
        "leaves": sorted(leaves),
        "roots": sorted(roots),
        "stats": {
            "total_modules": len(graph),
            "total_edges": sum(len(d) for d in graph.values()),
            "true_orphans_count": len(true_orphans),
            "leaves_count": len(leaves),
            "roots_count": len(roots),
        },
    }


def _short(name: str) -> str:
    """forge_sovereign_mapper -> sovereign_mapper (pour noeuds lisibles)."""
    return name.replace("forge_", "") if name.startswith("forge_") else name


def build_mermaid_from_graph(graph: Dict[str, Set[str]], max_nodes: int = 20) -> str:
    """Construit un flowchart Mermaid directement depuis le graphe (sans LLM)."""
    # Trier par nb de dependances sortantes decroissant, garder top max_nodes
    ranked = sorted(graph.items(), key=lambda x: -len(x[1]))
    top = dict(ranked[:max_nodes])
    top_names = set(top.keys())

    lines = ["flowchart TD"]
    for mod, deps in top.items():
        short_mod = _short(mod)
        kept_deps = [d for d in deps if d in top_names]
        if not kept_deps:
            lines.append(f"    {short_mod}")
        else:
            for dep in sorted(kept_deps):
                lines.append(f"    {short_mod} --> {_short(dep)}")

    return "\n".join(lines)


def build_panorama_via_llm(graph: Dict[str, Set[str]]) -> dict:
    """Construit le prompt data-driven et appelle forge_mermaid_gen."""
    import sys

    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    from nokido_agent.app.forge_mermaid_gen import generate_mermaid

    # Top 15 modules par centralite (nb de liens sortants + entrants)
    in_degree: Dict[str, int] = {m: 0 for m in graph}
    for mod, deps in graph.items():
        for d in deps:
            if d in in_degree:
                in_degree[d] += 1
    centrality = {m: len(graph.get(m, set())) + in_degree.get(m, 0) for m in graph}
    top15 = sorted(centrality.items(), key=lambda x: -x[1])[:15]
    top_names = {m for m, _ in top15}

    # Construire description textuelle
    relations: List[str] = []
    for mod, _ in top15:
        deps = graph[mod] & top_names
        if deps:
            for d in sorted(deps):
                relations.append(f"{_short(mod)} utilise {_short(d)}")

    prompt = (
        "flowchart TD architecture reelle Nokido v16.2 detectee par scan AST. "
        f"Modules principaux ({len(top15)}): "
        + ", ".join(_short(m) for m, _ in top15)
        + ". Relations reelles (dependances d'import): "
        + "; ".join(relations[:30])
        + "."
    )

    r = generate_mermaid(prompt, diagram_type="flowchart", max_tokens=1400)
    return r


def build_panorama() -> dict:
    """Point d'entree principal. Retourne scan + mermaid direct + mermaid LLM."""
    graph = scan_forge_modules()
    mermaid_direct = build_mermaid_from_graph(graph, max_nodes=15)
    llm_result = build_panorama_via_llm(graph)

    return {
        "nb_modules": len(graph),
        "graph": {k: sorted(v) for k, v in graph.items()},
        "mermaid_direct": mermaid_direct,
        "mermaid_llm": llm_result["code"],
        "llm_source": llm_result["source"],
        "llm_ok": llm_result["ok"],
        "llm_ms": llm_result["elapsed_ms"],
    }


if __name__ == "__main__":
    import json

    out = build_panorama()
    print(f"Modules scannes: {out['nb_modules']}")
    print(f"LLM: {out['llm_source']} | ok={out['llm_ok']} | {out['llm_ms']}ms")
    print("\n=== MERMAID DIRECT (AST only) ===")
    print(out["mermaid_direct"])
    print("\n=== MERMAID LLM (enrichi) ===")
    print(out["mermaid_llm"])
