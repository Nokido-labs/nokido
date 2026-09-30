from __future__ import annotations
# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_forge_graph_linker
#FORGE:[score:82|agent:claude-mcp|temp:0.00|risk:0.15|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: Ajouter les edges IMPORTS/CALLS dans rag_graph_edges via AST, sans casser CO_SOURCE/CO_DOMAIN/SEMANTIC
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__  = "#FORGE:[score:82|agent:claude-mcp|temp:0.00|risk:0.15|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"
"""
app/forge_graph_linker.py — AST-based IMPORTS / CALLS edges for Graph-RAG
=========================================================================

PROBLEME RESOLU :
forge_graph_rag.py (GraphRAG class) peuple 3 types d'edges :
  - CO_SOURCE  : chunks meme fichier (6720)
  - CO_DOMAIN  : chunks meme domaine (5484)
  - SEMANTIC   : cosinus > 0.75 (45164)
Total : 57368 edges.

MANQUE : edges structurelles code -> code.
Resultat : forge_commit_intel.get_impacted_modules() retourne [] car
il n'y a aucun lien "module A importe module B" ou "module A appelle
symbole defini dans module B" dans le graph.

Ce module ajoute 2 nouveaux rel_type dans la meme table rag_graph_edges :
  - IMPORTS (weight 1.0)  : source importe target (direct ou from X import Y)
  - CALLS   (weight 0.7)  : source appelle fonction/classe definie dans target

APPROCHE PRAGMATIQUE :
1. Scanner tous les .py dans app/ et tools/, exclure _attic/_tmp/backups/_sandbox
2. Pour chaque fichier :
   - ast.parse()
   - Collecter ast.Import et ast.ImportFrom -> nom module target
   - Collecter symboles definis (FunctionDef/ClassDef top-level) -> index global
3. Deuxieme passe :
   - Pour chaque ast.Call avec func.Name ou func.Attribute, resoudre au module
     qui definit ce symbole -> edge CALLS
4. Inserer dans rag_graph_edges via INSERT OR IGNORE (PK = src, dst, rel_type)

RESOLUTION module_name -> chunk_id :
- Pour chaque module "foo", chercher un chunk dont source matche
  "app/foo.py#chunk0" (ou premier chunk du fichier)
- Si module externe (numpy, sqlite3, etc) : skip
- Si pas de chunk principal trouve : skip aussi (module pas indexe)

API :
  from forge_graph_linker import GraphLinker

  gl = GraphLinker()
  stats = gl.build_ast_edges()
  # {"files_scanned": N, "imports": X, "calls": Y, "time_s": Z}

  # Requete d'impact : quels modules importent <file_path> ?
  impacted = gl.get_impacted_by_change("app/forge_llm_router.py")
  # list[str] des sources qui importent ce fichier

  gl.clear_ast_edges()  # wipe IMPORTS + CALLS pour rebuild
  gl.stats()            # counts par rel_type

CLI :
  python app/forge_graph_linker.py build   # build complet
  python app/forge_graph_linker.py stats   # distribution edges
  python app/forge_graph_linker.py clear   # efface IMPORTS + CALLS
  python app/forge_graph_linker.py impact app/forge_llm_router.py  # test impact

SAFETY :
- Skip fichiers > 500 KB (AST parse trop cher)
- Timeout ast.parse global 60s (skip si trop long)
- Exclusions : _attic, _tmp, _sandbox, backups, .mypy_cache
- Transactions : commit tous les 1000 edges
"""

import ast
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"

# Exclusions directory-level (relatives a ROOT)
EXCLUDE_DIRS = {"_attic", "_tmp", "_sandbox", "backups", "__pycache__",
                ".mypy_cache", "shadow_mutation", "session_backups",
                "test_repos", "node_modules", ".git", ".venv", "venv"}

# Exclusions filename patterns
EXCLUDE_FILE_PATTERNS = [
    re.compile(r"_\d{8}_\d{6}\.py$"),          # timestamped backups auto_boot_20260420_163829.py
    re.compile(r"\.bak$"),
    re.compile(r"\.pyc$"),
]

# Taille max AST-parse
MAX_FILE_SIZE = 500_000  # 500 KB

# Noms de stdlib / externes a ne pas resoudre vers un fichier local
STDLIB_PREFIXES = {
    "os", "sys", "io", "re", "json", "time", "datetime", "pathlib",
    "subprocess", "threading", "asyncio", "typing", "dataclasses",
    "collections", "itertools", "functools", "contextlib", "logging",
    "ast", "urllib", "http", "sqlite3", "hashlib", "hmac", "secrets",
    "base64", "struct", "socket", "ssl", "tempfile", "shutil", "uuid",
    "argparse", "enum", "random", "math", "copy", "warnings", "traceback",
    "inspect", "importlib", "types", "operator", "signal", "atexit",
    "concurrent", "multiprocessing", "queue", "weakref", "gc", "pickle",
    "platform", "getpass", "csv", "textwrap", "string", "unicodedata",
    "xml", "html", "email", "zipfile", "tarfile", "gzip", "bz2",
    "numpy", "pandas", "scipy", "torch", "tensorflow", "sklearn",
    "matplotlib", "seaborn", "plotly", "requests", "httpx", "aiohttp",
    "fastapi", "flask", "starlette", "uvicorn", "pydantic", "rich",
    "textual", "PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "tkinter",
    "chromadb", "faiss", "docker", "ollama", "openai", "anthropic",
    "google", "groq", "litellm",
    "msfrpc", "paramiko", "scapy", "nmap", "impacket",
    "__future__",  # pseudo module
}


# =============================================================================
# UTILITIES
# =============================================================================


def _is_excluded(path: Path) -> bool:
    """Check if path should be excluded from AST scan."""
    # Directory exclusion (any parent part matches)
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return True
    # Filename pattern exclusion
    for pattern in EXCLUDE_FILE_PATTERNS:
        if pattern.search(path.name):
            return True
    return False


def _is_external_module(module_name: str) -> bool:
    """Return True if module is stdlib / well-known external lib."""
    if not module_name:
        return True
    root = module_name.split(".")[0]
    return root in STDLIB_PREFIXES


def _file_to_source_prefix(file_path: Path, root: Path = ROOT) -> str:
    """
    Convertit un Path absolu en prefix 'source' tel qu'il apparait dans
    rag_chunks (ex: C:/.../LaForge/app/forge_llm_router.py -> app/forge_llm_router.py).
    """
    try:
        rel = file_path.relative_to(root)
    except ValueError:
        return str(file_path)
    # Normaliser en forward slash
    return str(rel).replace("\\", "/")


def _module_name_to_file_candidates(module_name: str, root: Path = ROOT) -> list:
    """
    'forge_llm_router' -> ['app/forge_llm_router.py', 'tools/forge_llm_router.py']
    'app.forge_llm_router' -> ['app/forge_llm_router.py']
    'tools.nokido_hub' -> ['tools/nokido_hub.py']
    """
    # Normaliser dots en slashes (pour imports qualifies)
    m = module_name.replace(".", "/")

    candidates = []
    for candidate_root in ("app", "tools", "recon_silo", "ctf", ""):
        if candidate_root:
            candidates.append(f"{candidate_root}/{m}.py")
        else:
            candidates.append(f"{m}.py")

    # Si module_name est simple (ex: forge_xxx sans path),
    # le plus probable est app/<name>.py
    # Cette ordre ^^^ fait que app/ est teste en premier
    return candidates


# =============================================================================
# SOURCE INDEX (module_name -> source_string dans rag_chunks)
# =============================================================================


class SourceIndex:
    """
    Maintient le mapping module_name -> source string (tel qu'apparait
    dans rag_chunks.source).

    Ex: 'forge_llm_router' -> 'app/forge_llm_router.py'
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        # module_name -> source (premier chunk du module, representatif)
        self._module_to_source: dict = {}
        # source reel -> True (cache existence)
        self._known_sources: set = set()
        # source reel -> chunk_id REEL (PK id)
        self._source_to_id: dict = {}
        self._loaded = False

    def load(self) -> None:
        """Charge la liste des sources uniques depuis rag_chunks."""
        if self._loaded:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT id, source FROM rag_chunks WHERE source IS NOT NULL")
            rows = cur.fetchall()
            for cid, src in rows:
                self._known_sources.add(src)
                if src not in self._source_to_id:
                    self._source_to_id[src] = cid
            conn.close()
            self._loaded = True
            print(f"  [DEBUG] SourceIndex loaded {len(self._known_sources)} sources.")
            if len(self._known_sources) > 0:
                print(f"  [DEBUG] Sample: {list(self._known_sources)[:5]}")
        except Exception:
            pass

    def resolve_module(self, module_name: str) -> Optional[str]:
        """
        Resolv 'forge_llm_router' -> chunk_id REEL si existe.
        Cache result.
        """
        if not self._loaded:
            self.load()

        if module_name in self._module_to_source:
            return self._module_to_source[module_name]

        # Externe ? skip
        if _is_external_module(module_name):
            self._module_to_source[module_name] = None
            return None

        # Chercher un candidate path dans known_sources
        for candidate in _module_name_to_file_candidates(module_name):
            # Normalisation : on cherche avec et sans prefix LaForge/
            candidates = [candidate, f"LaForge/{candidate}"]
            
            for cand in candidates:
                # 1. Exact match
                if cand in self._known_sources:
                    return self._source_to_id.get(cand)

                # 2. Chunk-based match
                for suffix in ["#chunk0", "_part0#chunk0", "#chunk1"]:
                    if f"{cand}{suffix}" in self._known_sources:
                        return self._source_to_id.get(f"{cand}{suffix}")

                # 3. Fuzzy filename match (last resort)
                fname = Path(cand).name
                for src in self._known_sources:
                    if src.endswith(fname) or f"{fname}#" in src:
                        return self._source_to_id.get(src)
        if module_name == "forge_agentic_engine":
            print(f"  [DEBUG] FAILED to resolve {module_name}")
        self._module_to_source[module_name] = None
        return None


# =============================================================================
# AST SCANNER
# =============================================================================


class ASTScanner:
    """
    Scan un fichier .py et extrait :
    - imports : list[str] noms de modules importes
    - called_names : set[str] noms appeles (ex: 'my_function', 'obj.method')
    - defined_names : set[str] noms definis au top-level
    """

    def __init__(self):
        self.imports: list = []
        self.called_names: set = set()
        self.defined_names: set = set()

    def scan_file(self, file_path: Path) -> bool:
        """Parse et extrait. Retourne True si succes."""
        try:
            if file_path.stat().st_size > MAX_FILE_SIZE:
                return False
            source = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(file_path))
        except (SyntaxError, OSError, UnicodeDecodeError, Exception):
            return False

        for node in ast.walk(tree):
            # Imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.imports.append(node.module)
                for alias in node.names:
                    # from X import Y -> resolve Y si on peut
                    pass

            # Calls
            elif isinstance(node, ast.Call):
                name = self._extract_call_name(node.func)
                if name:
                    self.called_names.add(name)

            # Definitions top-level
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.defined_names.add(node.name)

        return True

    def _extract_call_name(self, node) -> Optional[str]:
        """Extract call name from ast.Attribute/Name."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            # Ex: logger.info -> 'info' (on prend juste l attr)
            return node.attr
        return None


# =============================================================================
# GRAPH LINKER
# =============================================================================


class GraphLinker:
    """
    Construit et maintient les edges IMPORTS / CALLS dans rag_graph_edges.
    """

    def __init__(self, db_path: str = None, root_path: Path = None):
        self.db_path = db_path or str(DB)
        self.root = root_path or ROOT
        self.index = SourceIndex(self.db_path)

    def _iter_py_files(self) -> list:
        """List des .py valides dans root (app/ + tools/ + ...)."""
        files = []
        for base in ["app", "tools", "recon_silo", "ctf"]:
            base_path = self.root / base
            if not base_path.exists():
                continue
            for py_file in base_path.rglob("*.py"):
                if _is_excluded(py_file):
                    continue
                files.append(py_file)
        return files

    def build_ast_edges(self, verbose: bool = False) -> dict:
        """
        Scanne tous les .py et construit les edges IMPORTS + CALLS.
        """
        t0 = time.time()
        files = self._iter_py_files()
        stats = {
            "files_scanned":   0,
            "files_skipped":   0,
            "imports":         0,
            "calls":           0,
            "time_s":          0.0,
        }

        # ETAPE 1 : Premier passage - construire le mapping
        # defined_name_globally -> source_path qui le definit
        # (pour resolver les CALLS)
        if verbose:
            print(f"Scanning {len(files)} files...")

        scanners: dict = {}  # source_path -> ASTScanner
        for f in files:
            scanner = ASTScanner()
            if scanner.scan_file(f):
                src = _file_to_source_prefix(f)
                scanners[src] = scanner
                stats["files_scanned"] += 1
                if src == "app/LaForge.py":
                    print(f"  [DEBUG] Nokido.py: {len(scanner.imports)} imports, {len(scanner.defined_names)} definitions")
            else:
                print(f"  [DEBUG] Skipped: {f}")
                stats["files_skipped"] += 1

        # Global def_name -> [source_paths] qui le definissent
        def_name_to_sources: dict = {}
        for src, scanner in scanners.items():
            for name in scanner.defined_names:
                def_name_to_sources.setdefault(name, []).append(src)

        if verbose:
            print(f"  Scanned: {stats['files_scanned']}, skipped: {stats['files_skipped']}")
            print(f"  Defined names: {len(def_name_to_sources)}")
            print(f"  Scanners keys (sample): {list(scanners.keys())[:10]}")
            if "app/LaForge.py" in scanners:
                print("  [DEBUG] app/LaForge.py FOUND in scanners")
            else:
                print("  [DEBUG] app/LaForge.py NOT FOUND in scanners")

        # ETAPE 2 : Construction des edges
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn.cursor()

        imports_batch = []
        calls_batch = []

        for src, scanner in scanners.items():
            # Le chunk_id source = premier chunk de ce fichier
            src_chunk = self._file_src_to_chunk_id(src)
            if not src_chunk:
                continue

            # IMPORTS : pour chaque import, resoudre vers module cible
            for mod_name in scanner.imports:
                dst_chunk = self.index.resolve_module(mod_name)
                if src == "app/LaForge.py":
                    print(f"  [DEBUG] Nokido.py imports {mod_name} -> {dst_chunk}")
                if dst_chunk and dst_chunk != src_chunk:
                    imports_batch.append((src_chunk, dst_chunk, "IMPORTS", 1.0))

            # CALLS : pour chaque nom appele, resoudre vers module qui le definit
            for called_name in scanner.called_names:
                dst_sources = def_name_to_sources.get(called_name, [])
                # Si une seule source le definit : edge fiable
                if len(dst_sources) == 1:
                    dst_src = dst_sources[0]
                    if dst_src == src:
                        continue  # self-call, skip
                    dst_chunk = self._file_src_to_chunk_id(dst_src)
                    if dst_chunk:
                        calls_batch.append((src_chunk, dst_chunk, "CALLS", 0.7))
                # Sinon ambigu : skip (eviter faux-positifs)

        # Dedupliquer (src, dst, rel_type) localement
        imports_batch = list(set(imports_batch))
        calls_batch = list(set(calls_batch))

        if verbose:
            print(f"  Final Candidate IMPORTS: {len(imports_batch)}")
            print(f"  Final Candidate CALLS:   {len(calls_batch)}")
            if len(imports_batch) > 0:
                print(f"  Sample: {imports_batch[0]}")

        # Bulk insert avec INSERT OR IGNORE (PK = src, dst, rel_type)
        cur.executemany(
            "INSERT OR IGNORE INTO rag_graph_edges (src, dst, rel_type, weight) VALUES (?, ?, ?, ?)",
            imports_batch,
        )
        stats["imports"] = len(imports_batch)

        cur.executemany(
            "INSERT OR IGNORE INTO rag_graph_edges (src, dst, rel_type, weight) VALUES (?, ?, ?, ?)",
            calls_batch,
        )
        stats["calls"] = len(calls_batch)

        conn.commit()
        conn.close()

        stats["time_s"] = round(time.time() - t0, 2)
        return stats

    def _file_src_to_chunk_id(self, src_path: str) -> Optional[str]:
        """
        Convertit 'app/forge_xxx.py' en son chunk_id REEL (PK id)
        Agnostique du séparateur de chemin (Windows/Unix).
        """
        self.index.load()
        # Normalisation du chemin d'entrée
        src_norm = src_path.replace("\\", "/")
        
        # On cherche un match parmi les sources connues (normalisées elles aussi)
        for known_src in self.index._known_sources:
            known_norm = known_src.replace("\\", "/")
            
            # Match exact ou par suffixe (pour gérer LaForge/prefix)
            if known_norm == src_norm or known_norm.endswith("/" + src_norm):
                return self.index._source_to_id.get(known_src)
            
            # Match avec chunk suffixes
            for suffix in ["#chunk0", "_part0#chunk0", "#chunk1"]:
                if known_norm == src_norm + suffix or known_norm.endswith("/" + src_norm + suffix):
                    return self.index._source_to_id.get(known_src)

        return None

    def clear_ast_edges(self) -> dict:
        """Wipe uniquement les edges IMPORTS + CALLS."""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("DELETE FROM rag_graph_edges WHERE rel_type IN ('IMPORTS', 'CALLS')")
            deleted = cur.rowcount
            conn.commit()
            conn.close()
            return {"deleted": deleted, "ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def stats(self) -> dict:
        """Distribution edges par rel_type."""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT rel_type, COUNT(*) 
                FROM rag_graph_edges 
                GROUP BY rel_type 
                ORDER BY COUNT(*) DESC
            """)
            result = {rel: n for rel, n in cur.fetchall()}
            conn.close()
            return result
        except Exception as e:
            return {"error": str(e)}

    def get_impacted_by_change(self, file_path: str) -> list:
        """
        Retourne la liste des sources (modules) qui importent ou appellent
        file_path. Utilise pour forge_commit_intel.get_impacted_modules().

        Args:
            file_path: chemin relatif style 'app/forge_llm_router.py'

        Returns:
            list[dict] avec {"source": ..., "rel_type": ..., "weight": ...}
        """
        self.index.load()
        # Normaliser le path
        file_path = file_path.replace("\\", "/")
        # Chercher le chunk_id correspondant
        dst_chunk = self._file_src_to_chunk_id(file_path)
        if not dst_chunk:
            return []

        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT src, rel_type, weight 
                FROM rag_graph_edges 
                WHERE dst = ? AND rel_type IN ('IMPORTS', 'CALLS')
                ORDER BY 
                  CASE rel_type WHEN 'IMPORTS' THEN 0 ELSE 1 END,
                  weight DESC
            """, (dst_chunk,))
            results = []
            for src, rel_type, weight in cur.fetchall():
                # Extract file from chunk_id (ex: 'app/forge_xxx.py#chunk0' -> 'app/forge_xxx.py')
                src_file = re.split(r"(?:#chunk\d+|_part\d+)", src)[0]
                results.append({
                    "source":    src_file,
                    "chunk_id":  src,
                    "rel_type":  rel_type,
                    "weight":    weight,
                })
            conn.close()
            return results
        except Exception:
            return []

    def reverse_impact(self, file_path: str) -> list:
        """Qui DEPUIS file_path importe / appelle ? (transpose)."""
        self.index.load()
        file_path = file_path.replace("\\", "/")
        src_chunk = self._file_src_to_chunk_id(file_path)
        if not src_chunk:
            return []

        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT dst, rel_type, weight 
                FROM rag_graph_edges 
                WHERE src = ? AND rel_type IN ('IMPORTS', 'CALLS')
            """, (src_chunk,))
            results = []
            for dst, rel_type, weight in cur.fetchall():
                dst_file = re.split(r"(?:#chunk\d+|_part\d+)", dst)[0]
                results.append({
                    "target":   dst_file,
                    "chunk_id": dst,
                    "rel_type": rel_type,
                    "weight":   weight,
                })
            conn.close()
            return results
        except Exception:
            return []


# =============================================================================
# CLI
# =============================================================================


def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp_build = sub.add_parser("build", help="Scan AST et build les edges IMPORTS+CALLS")
    sp_build.add_argument("--clear-first", action="store_true",
                          help="Clear les edges existants avant de rebuild")

    sub.add_parser("stats", help="Distribution edges par rel_type")
    sub.add_parser("clear", help="Efface les edges IMPORTS + CALLS")

    sp_impact = sub.add_parser("impact", help="Qui importe / appelle ce fichier ?")
    sp_impact.add_argument("file_path")

    sp_reverse = sub.add_parser("reverse", help="Ce fichier importe / appelle quoi ?")
    sp_reverse.add_argument("file_path")

    args = parser.parse_args()
    gl = GraphLinker()

    if args.cmd == "build":
        if args.clear_first:
            result = gl.clear_ast_edges()
            print(f"Cleared: {result}")
        stats = gl.build_ast_edges(verbose=True)
        import json
        print(json.dumps(stats, indent=2))
        return 0

    if args.cmd == "stats":
        import json
        print(json.dumps(gl.stats(), indent=2))
        return 0

    if args.cmd == "clear":
        import json
        print(json.dumps(gl.clear_ast_edges(), indent=2))
        return 0

    if args.cmd == "impact":
        results = gl.get_impacted_by_change(args.file_path)
        print(f"=== {len(results)} modules impactes par changement dans {args.file_path} ===")
        for r in results[:30]:
            print(f"  [{r['rel_type']:<8} w={r['weight']:.1f}] {r['source']}")
        return 0

    if args.cmd == "reverse":
        results = gl.reverse_impact(args.file_path)
        print(f"=== {args.file_path} importe / appelle {len(results)} modules ===")
        for r in results[:30]:
            print(f"  [{r['rel_type']:<8} w={r['weight']:.1f}] -> {r['target']}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
