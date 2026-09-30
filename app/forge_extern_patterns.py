"""
forge_extern_patterns.py — Extraction AST de patterns de bibliothèques externes.

SHALLOW : lit summary depuis compressed.json (rapide, ~8KB).
DEEP_AST : extrait classes/fonctions/décorateurs/types depuis le source Python via ast.NodeVisitor.
           Déclenché par forge_reconstruction_loss.py sur signal RETRY_WITH_EXPANSION (Jaccard < 0.85).

Organe : Cervelet (perception structurelle du code externe)
Vascularisation : forge_reconstruction_loss → RETRY_WITH_EXPANSION → extract_patterns_from_gitingest(depth=DEEP_AST)
Scénario hémorragie : MAX_FILES cap + public-only filter évitent OOM sur transformers (133 MB source)
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
__FORGE_COLOR__ = "GREEN"

import ast
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("Nokido.ExternPatterns")

ROOT = Path(__file__).resolve().parent.parent
GITINGEST_DIR = ROOT / "data" / "gitingest"

TARGET_LIBS = [
    "httpx",
    "fastapi",
    "faiss",
    "sentence-transformers",
    "pyzmq",
    "onnxruntime",
    "pydantic",
    "mcp-python-sdk",
]

MAX_FILES_PER_LIB = 200  # cap OOM sur transformers (133 MB source)
MAX_FUNCS_PER_FILE = 50  # idem
_PRIVATE = lambda name: name.startswith("_")


# ---------------------------------------------------------------------------
# AST extractor
# ---------------------------------------------------------------------------


class _ASTExtractor(ast.NodeVisitor):
    """Extrait classes, fonctions, décorateurs et types depuis un module Python."""

    def __init__(self):
        self.classes: list[dict] = []
        self.functions: list[dict] = []
        self._func_count = 0

    @staticmethod
    def _get_docstring(node) -> str:
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, (ast.Constant, ast.Str)):
            val = node.body[0].value
            return (val.s if isinstance(val, ast.Str) else str(val.value))[:300]
        return ""

    @staticmethod
    def _unparse_annotation(node) -> str:
        try:
            return ast.unparse(node)
        except Exception:
            return "?"

    @staticmethod
    def _format_args(args: ast.arguments) -> str:
        parts = []
        for arg in args.args:
            a = arg.arg
            if arg.annotation:
                a += f": {_ASTExtractor._unparse_annotation(arg.annotation)}"
            parts.append(a)
        return ", ".join(parts)

    @staticmethod
    def _get_decorators(node) -> list[str]:
        result = []
        for d in node.decorator_list:
            try:
                result.append(ast.unparse(d))
            except Exception:
                result.append("?")
        return result

    def _visit_func(self, node, parent_class: str | None = None) -> dict | None:
        if _PRIVATE(node.name):
            return None
        if self._func_count >= MAX_FUNCS_PER_FILE:
            return None
        self._func_count += 1
        ret = self._unparse_annotation(node.returns) if node.returns else ""
        entry = {
            "name": node.name,
            "args": self._format_args(node.args),
            "return_type": ret,
            "decorators": self._get_decorators(node),
            "docstring": self._get_docstring(node),
        }
        if parent_class:
            entry["class"] = parent_class
        return entry

    def visit_ClassDef(self, node: ast.ClassDef):
        if _PRIVATE(node.name):
            return
        bases = []
        for b in node.bases:
            try:
                bases.append(ast.unparse(b))
            except Exception:
                pass
        methods = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                m = self._visit_func(item, parent_class=node.name)
                if m:
                    methods.append(m)
        self.classes.append(
            {
                "name": node.name,
                "bases": bases,
                "docstring": self._get_docstring(node),
                "methods": methods[:20],  # cap par classe
            }
        )

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # module-level only (class methods handled in visit_ClassDef)
        if node.col_offset == 0:
            f = self._visit_func(node)
            if f:
                self.functions.append(f)

    visit_AsyncFunctionDef = visit_FunctionDef


def extract_file_ast(path: Path) -> dict:
    """Parse un fichier .py et retourne classes + fonctions extraites."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return {"error": str(e)}

    ex = _ASTExtractor()
    ex.visit(tree)

    # module docstring
    mod_doc = ""
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, (ast.Constant, ast.Str)):
        val = tree.body[0].value
        mod_doc = (val.s if isinstance(val, ast.Str) else str(val.value))[:200]

    return {
        "file": path.name,
        "docstring": mod_doc,
        "classes": ex.classes,
        "functions": ex.functions,
    }


def build_ast_compressed(
    source_dir: Path,
    lib_name: str,
    max_files: int = MAX_FILES_PER_LIB,
    output_dir: Path | None = None,
) -> dict:
    """Walk source_dir, parse up to max_files .py files via AST, write compressed.json.

    Returns the compressed dict.
    """
    out_dir = output_dir or GITINGEST_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{lib_name}_compressed.json"

    py_files = sorted(source_dir.rglob("*.py"))[:max_files]
    logger.info(f"[extern_patterns] AST parse {len(py_files)} files for {lib_name}")

    all_classes: list[dict] = []
    all_functions: list[dict] = []
    all_decorators: set[str] = set()
    return_types: dict[str, str] = {}
    errors = 0

    for f in py_files:
        res = extract_file_ast(f)
        if "error" in res:
            errors += 1
            continue
        all_classes.extend(res["classes"])
        all_functions.extend(res["functions"])
        for fn in res["functions"]:
            if fn["decorators"]:
                all_decorators.update(fn["decorators"])
            if fn["return_type"]:
                return_types[fn["name"]] = fn["return_type"]
        for cls in res["classes"]:
            for m in cls.get("methods", []):
                if m["decorators"]:
                    all_decorators.update(m["decorators"])
                if m["return_type"]:
                    return_types[f"{cls['name']}.{m['name']}"] = m["return_type"]

    # compact summary
    class_names = [c["name"] for c in all_classes[:30]]
    func_names = [f["name"] for f in all_functions[:30]]
    summary = (
        f"{lib_name}: {len(all_classes)} classes, {len(all_functions)} module-level funcs. "
        f"Classes: {', '.join(class_names[:15])}. "
        f"Funcs: {', '.join(func_names[:15])}."
    )

    compressed = {
        "lib": lib_name,
        "source_dir": str(source_dir),
        "files_parsed": len(py_files),
        "parse_errors": errors,
        "summary": summary,
        "classes": all_classes[:100],
        "functions": all_functions[:200],
        "decorators": sorted(all_decorators)[:50],
        "return_types": dict(list(return_types.items())[:200]),
        "examples": [],  # populated by future example-extraction step
    }

    out_path.write_text(json.dumps(compressed, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"[extern_patterns] wrote {out_path} ({out_path.stat().st_size // 1024} KB)")
    # Auto-ingest AST nodes as rag_chunks with meta=AST JSON (pointer architecture)
    try:
        n_inserted = ingest_ast_nodes_to_rag(lib_name, compressed)
        compressed["_rag_inserted"] = n_inserted
    except Exception as e:
        logger.warning(f"[ast_ingest] auto-ingest skipped: {e}")
    return compressed


# ---------------------------------------------------------------------------
# Public interface (unchanged contract for forge_reconstruction_loss)
# ---------------------------------------------------------------------------


def query_extern_pattern(lib: str, question: str) -> str:
    """Consulte le RAG pour patterns d'implémentation sur une lib externe."""
    from nokido_agent.app.forge_self_correction import preflight_check_verbose

    query = f"pattern implementation {lib} {question}"
    res = preflight_check_verbose(query, context=f"domain:extern_pattern lib:{lib}")
    if not res.get("results"):
        return f"Aucun pattern trouvé pour {lib}: {question}"
    best = res["results"][0]
    return f"Pattern (score={best['score']}):\n{best['preview']}"


def extract_patterns_from_gitingest(
    lib_name: str | None = None,
    depth: str = "SHALLOW",
    source_dir: Path | None = None,
) -> dict[str, Any]:
    """Extrait et ancre patterns depuis compressed.json (SHALLOW) ou AST direct (DEEP_AST).

    Si compressed.json absent et source_dir fourni → build_ast_compressed() d'abord.
    Déclenché par forge_reconstruction_loss RETRY_WITH_EXPANSION avec depth='DEEP_AST'.
    """
    from nokido_agent.app.forge_self_correction import anchor_solution

    libs = [lib_name] if lib_name else TARGET_LIBS
    results: dict[str, Any] = {}

    for lib in libs:
        p = GITINGEST_DIR / f"{lib}_compressed.json"

        # Build AST compressed.json if missing and source_dir provided
        if not p.exists() and source_dir is not None:
            try:
                build_ast_compressed(source_dir, lib)
            except Exception as e:
                logger.error(f"[extern_patterns] build_ast_compressed({lib}): {e}")
                results[lib] = f"error:{e}"
                continue

        if not p.exists():
            results[lib] = "skip"
            continue

        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            summary = data.get("summary", "")
            if not summary:
                results[lib] = "skip"
                continue

            if depth == "DEEP_AST":
                decorators = data.get("decorators", [])
                return_types = data.get("return_types", {})
                classes = data.get("classes", [])
                functions = data.get("functions", [])
                extra = ""
                if decorators:
                    extra += f"\nDecorators: {', '.join(str(d) for d in decorators[:20])}"
                if return_types:
                    extra += f"\nReturn types: {json.dumps(return_types, ensure_ascii=False)[:400]}"
                if classes:
                    class_sigs = [f"{c['name']}({', '.join(c.get('bases', []))})" for c in classes[:10]]
                    extra += f"\nClasses: {', '.join(class_sigs)}"
                if functions:
                    func_sigs = [
                        f"{f['name']}({f.get('args', '')}) -> {f.get('return_type', '')}" for f in functions[:10]
                    ]
                    extra += f"\nFunctions: {'; '.join(func_sigs)}"
                solution_text = f"Patterns DEEP_AST de {lib}: {summary[:600]}{extra}"
            else:
                solution_text = f"Patterns extraits (SHALLOW) de {lib}: {summary[:500]}"

            anchor_solution(
                problem=f"Structure et patterns d'usage de {lib} [depth={depth}]",
                solution=solution_text,
                example=f"import {lib}",
                domain="extern_pattern",
            )
            logger.info(f"[extern_patterns] {lib} ancré depth={depth}")
            results[lib] = "ok"

        except Exception as e:
            logger.error(f"[extern_patterns] {lib}: {e}")
            results[lib] = f"error:{e}"

    return results


# ---------------------------------------------------------------------------
# AST pointer architecture — store AST nodes as rag_chunks with meta=AST JSON
# Vector search → chunk_id → meta (full AST) — no hallucination, exact structure
# ---------------------------------------------------------------------------


def ingest_ast_nodes_to_rag(
    lib_name: str,
    compressed: dict,
    db_path: Path | None = None,
) -> int:
    """Insert each AST class/function as a separate rag_chunk.

    text  = searchable signature + docstring (for FAISS/BM25)
    meta  = full AST node JSON (exact structure, decorators, args, bases)
    Pointer: FAISS returns chunk_id → load meta from rag_chunks → exact AST.
    Returns number of rows inserted.
    """
    import hashlib, json, sqlite3

    db_path = db_path or Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
    conn = sqlite3.connect(db_path)
    inserted = 0

    def _insert(node: dict, kind: str):
        nonlocal inserted
        name = node.get("name", "")
        if not name:
            return
        if kind == "function":
            text = f"{name}({node.get('args', '')}) -> {node.get('return_type', '')}: {node.get('docstring', '')[:120]}"
        else:  # class
            bases = ", ".join(node.get("bases", []))
            text = f"class {name}({bases}): {node.get('docstring', '')[:120]}"
        source = f"ast:{lib_name}:{kind}:{name}"
        chunk_id = hashlib.sha256(f"{source}:{text}".encode()).hexdigest()[:16]
        meta_json = json.dumps({"ast_kind": kind, "lib": lib_name, "node": node}, ensure_ascii=False)
        try:
            conn.execute(
                """INSERT OR IGNORE INTO rag_chunks
                   (id, text, source, domain, meta, quality_score)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (chunk_id, text, source, "extern_pattern", meta_json, 0.85),
            )
            # sync FTS5
            conn.execute(
                "INSERT OR IGNORE INTO rag_fts(chunk_id, text, source, domain) VALUES (?,?,?,?)",
                (chunk_id, text, source, "extern_pattern"),
            )
            inserted += 1
        except Exception as e:
            logger.debug(f"[ast_ingest] {name}: {e}")

    for fn in compressed.get("functions", []):
        _insert(fn, "function")
    for cls in compressed.get("classes", []):
        _insert(cls, "class")
        for m in cls.get("methods", []):
            m_copy = dict(m)
            m_copy["class"] = cls["name"]
            _insert(m_copy, "method")

    conn.commit()
    conn.close()
    logger.info(f"[ast_ingest] {lib_name}: {inserted} AST nodes → rag_chunks.meta")
    return inserted


if __name__ == "__main__":
    import sys

    if "--build" in sys.argv:
        # Usage: python forge_extern_patterns.py --build httpx /path/to/httpx/source
        idx = sys.argv.index("--build")
        lib = sys.argv[idx + 1]
        src = Path(sys.argv[idx + 2])
        result = build_ast_compressed(src, lib)
        print(
            f"Built: {result['files_parsed']} files, {len(result['classes'])} classes, {len(result['functions'])} funcs"
        )
    elif "--extract" in sys.argv:
        extract_patterns_from_gitingest()
    elif "--query" in sys.argv:
        lib = sys.argv[sys.argv.index("--query") + 1]
        q = sys.argv[sys.argv.index("--query") + 2]
        print(query_extern_pattern(lib, q))
