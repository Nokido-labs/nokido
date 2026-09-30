"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_shredder
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
shredder.py — Extracteur AST automatique pour Nokido.py
Usage : python shredder.py [--dry-run]

Pour chaque groupe défini dans GROUPS :
  1. Lit les nœuds AST depuis Nokido.py
  2. Analyse les Name/Attribute utilisés → collecte les imports nécessaires
  3. Écrit forge_*.py avec header auto + imports détectés + code
  4. Valide syntaxe AST du nouveau fichier
  5. (hors dry-run) Remplace le corps dans Nokido.py par un stub + import

Après tous les groupes, valide la syntaxe de Nokido.py résultant.
"""

import ast, sys, argparse, shutil
from pathlib import Path

APP = Path(__file__).resolve().parent
SRC = APP / "Nokido.py"

# ─────────────────────────────────────────────────────────────────────────────
# GROUPES D'EXTRACTION
# (module_name, [noms_noeuds_top_level])
# ─────────────────────────────────────────────────────────────────────────────
GROUPS = [
    (
        "forge_logging",
        [
            "_silent",
            "_JSONLHandler",
            "debug_log",
            "_debug_main_fh",
            "_debug_route_fh",
        ],
    ),
    (
        "forge_ollama_memory",
        [
            "OllamaMemoryManager",
            "get_mem_mgr",
        ],
    ),
    (
        "forge_prefect",
        [
            "PrefectManager",
        ],
    ),
    (
        "forge_llm",
        [
            "_get_ollama_semaphore",
            "ollama_call",
            "ollama_parallel",
            "ollama_stream",
            "IntentClassifier",
            "looks_like_shell_command",
        ],
    ),
    (
        "forge_versioning",
        [
            "SurgeryResult",
            "_NodeLocator",
            "_NodeReplacer",
            "CodeSurgeon",
            "ForgeSaveOrchestrator",
            "VersionManager",
        ],
    ),
    (
        "forge_rag_engine",
        [
            "RAGEngine",
            "SkillEntry",
            "AgenticEngine",
            "EvolutionOrchestrator",
        ],
    ),
    (
        "forge_orchestrator",
        [
            "SupervisorAnalysis",
            "ActionResult",
            "RoutingPlan",
            "OrchestratorState",
            "SupervisorAgent",
            "ActionAgent",
            "RAGAgent",
            "DialogueAgent",
            "OrchestratorManager",
            "SessionContext",
            "AutocompleteEngine",
            "get_orchestrator",
        ],
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# CATALOGUE des imports présents dans Nokido.py
# Construit dynamiquement à partir du fichier source.
# ─────────────────────────────────────────────────────────────────────────────


def build_import_catalog(tree: ast.Module) -> dict[str, str]:
    """
    Retourne un dict  nom_exposé → ligne_import_complète
    en parcourant tous les Import / ImportFrom top-level.

    Ex:
      "os"       → "import os"
      "Path"     → "from pathlib import Path"
      "asyncio"  → "import asyncio"
      "np"       → "import numpy as np"
    """
    catalog: dict[str, str] = {}

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                key = alias.asname if alias.asname else alias.name.split(".")[0]
                line = f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
                catalog[key] = line
                # Aussi enregistrer le module complet (ex: "logging")
                catalog[alias.name] = line

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                key = alias.asname if alias.asname else alias.name
                line = f"from {module} import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
                catalog[key] = line

    return catalog


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSE DES NOMS UTILISÉS dans un nœud AST
# ─────────────────────────────────────────────────────────────────────────────


def collect_names_used(nodes: list[ast.stmt]) -> set[str]:
    """
    Parcourt tous les nœuds AST et collecte :
      - ast.Name.id          → variables / fonctions référencées
      - ast.Attribute sur Name → ex: "os.path" → "os"
      - ast.Call sur Name    → fonctions appelées
    """
    names: set[str] = set()

    class _Visitor(ast.NodeVisitor):
        def visit_Name(self, node) -> None:
            """Visit name.

            Args:
                node: Description.
            """
            names.add(node.id)
            self.generic_visit(node)

        def visit_Attribute(self, node) -> None:
            # os.path.join → récupérer "os"
            """Visit attribute.

            Args:
                node: Description.
            """
            if isinstance(node.value, ast.Name):
                names.add(node.value.id)
            self.generic_visit(node)

    v = _Visitor()
    for node in nodes:
        v.visit(node)
    return names


def resolve_imports(
    names_used: set[str],
    catalog: dict[str, str],
    group_node_names: set[str],
) -> list[str]:
    """
    Pour chaque nom utilisé, si présent dans le catalogue d'imports
    ET pas un nœud du même groupe, retourner la ligne d'import.
    Déduplique et trie.
    """
    lines: set[str] = set()
    for name in names_used:
        if name in catalog and name not in group_node_names:
            lines.add(catalog[name])
    return sorted(lines)


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────


def find_nodes(tree: ast.Module, names: list[str]) -> dict[str, ast.stmt]:
    """Find nodes.

    Args:
        tree: Description.
        names: Description.
    """
    found = {}
    for node in tree.body:
        nm = getattr(node, "name", None)
        if nm in names:
            found[nm] = node
    return found


def extract_source_lines(lines: list[str], node: ast.stmt) -> str:
    """Extract source lines.

    Args:
        lines: Description.
        node: Description.
    """
    start = node.lineno - 1
    if hasattr(node, "decorator_list") and node.decorator_list:
        start = node.decorator_list[0].lineno - 1
    end = node.end_lineno
    return "".join(lines[start:end])


def build_module_source(
    module_name: str,
    auto_imports: list[str],
    node_sources: list[str],
) -> str:
    """Build module source.

    Args:
        module_name: Description.
        auto_imports: Description.
        node_sources: Description.
    """
    doc = (
        f'"""\n'
        f"{module_name}.py — extrait automatiquement depuis Nokido.py\n"
        f"Généré par shredder.py\n"
        f'"""\n'
        f"from __future__ import annotations\n"
    )
    imports_block = "\n".join(auto_imports)
    parts = [doc, imports_block, "\n\n"]
    for ns in node_sources:
        parts.append(ns.rstrip())
        parts.append("\n\n\n")
    return "".join(parts)


def validate_syntax(src: str, label: str) -> bool:
    """Validate syntax.

    Args:
        src: Description.
        label: Description.
    """
    try:
        ast.parse(src)
        return True
    except SyntaxError as e:
        print(f"  ❌ SyntaxError dans {label} L{e.lineno}: {e.msg}")
        return False


def stub_for_node(node: ast.stmt, module_name: str) -> str:
    """Stub for node.

    Args:
        node: Description.
        module_name: Description.
    """
    kind = "class" if isinstance(node, ast.ClassDef) else "def"
    return f"# {kind} {node.name} → extrait dans {module_name}.py\n"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────


def run(dry_run: bool = False) -> None:
    """Run.

    Args:
        dry_run: Description.
    """
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Shredder Nokido — {SRC.name} ({SRC.stat().st_size // 1024}KB)\n")

    src = SRC.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)

    if not validate_syntax(src, "Nokido.py initial"):
        print("❌ Nokido.py invalide — abandon")
        sys.exit(1)
    print(f"✅ Nokido.py syntaxe OK ({len(lines)}L)")

    # Catalogue des imports disponibles dans Nokido.py
    catalog = build_import_catalog(tree)
    print(f"✅ Catalogue imports : {len(catalog)} entrées\n")

    stubs: dict[str, str] = {}
    modules_ok: list[str] = []

    for module_name, node_names in GROUPS:
        out_path = APP / f"{module_name}.py"
        print(f"── {module_name}.py")

        found = find_nodes(tree, node_names)
        missing = [n for n in node_names if n not in found]
        if missing:
            print(f"  ⚠  Introuvables : {missing}")
        if not found:
            print("  ⏭  Aucun nœud — ignoré\n")
            continue

        # Collecter le code source de chaque nœud
        node_sources = []
        found_nodes = []
        for name in node_names:
            if name not in found:
                continue
            node = found[name]
            ns = extract_source_lines(lines, node)
            node_sources.append(ns)
            found_nodes.append(node)
            stubs[name] = stub_for_node(node, module_name)
            print(f"  📦 {name:<38} L{node.lineno}..{node.end_lineno} ({node.end_lineno - node.lineno + 1}L)")

        # Analyser les noms utilisés → imports auto
        names_used = collect_names_used(found_nodes)
        group_names = set(node_names)
        auto_imports = resolve_imports(names_used, catalog, group_names)
        print(f"  🔍 Imports détectés ({len(auto_imports)}) : {auto_imports[:6]}{'…' if len(auto_imports) > 6 else ''}")

        module_src = build_module_source(module_name, auto_imports, node_sources)

        if not validate_syntax(module_src, f"{module_name}.py"):
            print("  ❌ Invalide — ignoré\n")
            continue

        if not dry_run:
            out_path.write_text(module_src, encoding="utf-8")
            print(f"  ✅ Écrit : {out_path.name} ({len(module_src.splitlines())}L)\n")
        else:
            print(f"  ✅ [dry] Serait écrit : {out_path.name} ({len(module_src.splitlines())}L)\n")

        modules_ok.append(module_name)

    # ── Patch Nokido.py ──────────────────────────────────────────────────────
    if not dry_run and stubs:
        print(f"── Patch Nokido.py : remplacement de {len(stubs)} nœuds par des stubs")

        src2 = SRC.read_text(encoding="utf-8", errors="replace")
        lines2 = src2.splitlines(keepends=True)
        tree2 = ast.parse(src2)

        all_found = find_nodes(tree2, list(stubs.keys()))
        nodes_sorted = sorted(all_found.values(), key=lambda n: n.lineno, reverse=True)

        lines2_list = list(lines2)
        for node in nodes_sorted:
            start = node.lineno - 1
            if hasattr(node, "decorator_list") and node.decorator_list:
                start = node.decorator_list[0].lineno - 1
            end = node.end_lineno
            stub = stubs[node.name]
            lines2_list[start:end] = [stub]

        new_src = "".join(lines2_list)

        if not validate_syntax(new_src, "Nokido.py patché"):
            print("  ❌ Nokido.py patché invalide — ANNULÉ, original conservé")
        else:
            bak = APP / "backups" / "Nokido_pre_shredder.py"
            bak.parent.mkdir(exist_ok=True)
            shutil.copy2(SRC, bak)
            print(f"  💾 Backup → {bak.name}")
            SRC.write_text(new_src, encoding="utf-8")
            final_lines = len(new_src.splitlines())
            print(f"  ✅ Nokido.py → {final_lines}L (économie : {len(lines) - final_lines}L)")

    # ── Résumé ────────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"Modules créés  : {len(modules_ok)} → {modules_ok}")
    print(f"Nœuds stubbés  : {len(stubs)}")
    src_final = SRC.read_text(encoding="utf-8", errors="replace")
    print(f"Nokido.py     : {len(src_final.splitlines())}L")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
