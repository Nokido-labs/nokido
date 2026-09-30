# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-05-06 | VER:v_forge_graph_linker_v2
#FORGE:[score:88|agent:agt_gemini|temp:0.00|risk:0.15|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: Edge scoring unifié (Cosine) + Personalized PageRank (PPR).
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
__FORGE_TAGS__ = "#FORGE:[score:88|agent:agt_gemini|temp:0.00|risk:0.15|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"

import ast
import re
import sqlite3
import sys
import time
import json
import logging
import numpy as np
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from functools import lru_cache

logger = logging.getLogger("Nokido.GraphLinker")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"

# Exclusions directory-level (relatives a ROOT)
EXCLUDE_DIRS = {
    "_attic",
    "_tmp",
    "_sandbox",
    "backups",
    "__pycache__",
    ".mypy_cache",
    "shadow_mutation",
    "session_backups",
    "test_repos",
    "node_modules",
    ".git",
    ".venv",
    "venv",
}

# Exclusions filename patterns
EXCLUDE_FILE_PATTERNS = [
    re.compile(r"_\d{8}_\d{6}\.py$"),
    re.compile(r"\.bak$"),
    re.compile(r"\.pyc$"),
]

# Taille max AST-parse
MAX_FILE_SIZE = 500_000  # 500 KB

# Noms de stdlib / externes
STDLIB_PREFIXES = {
    "os",
    "sys",
    "io",
    "re",
    "json",
    "time",
    "datetime",
    "pathlib",
    "subprocess",
    "threading",
    "asyncio",
    "typing",
    "dataclasses",
    "collections",
    "itertools",
    "functools",
    "contextlib",
    "logging",
    "ast",
    "urllib",
    "http",
    "sqlite3",
    "hashlib",
    "hmac",
    "secrets",
    "base64",
    "struct",
    "socket",
    "ssl",
    "tempfile",
    "shutil",
    "uuid",
    "argparse",
    "enum",
    "random",
    "math",
    "copy",
    "warnings",
    "traceback",
    "inspect",
    "importlib",
    "types",
    "operator",
    "signal",
    "atexit",
    "concurrent",
    "multiprocessing",
    "queue",
    "weakref",
    "gc",
    "pickle",
    "platform",
    "getpass",
    "csv",
    "textwrap",
    "string",
    "unicodedata",
    "xml",
    "html",
    "email",
    "zipfile",
    "tarfile",
    "gzip",
    "bz2",
    "numpy",
    "pandas",
    "scipy",
    "torch",
    "tensorflow",
    "sklearn",
    "matplotlib",
    "seaborn",
    "plotly",
    "requests",
    "httpx",
    "aiohttp",
    "fastapi",
    "flask",
    "starlette",
    "uvicorn",
    "pydantic",
    "rich",
    "textual",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "wx",
    "tkinter",
    "chromadb",
    "faiss",
    "docker",
    "ollama",
    "openai",
    "anthropic",
    "google",
    "groq",
    "litellm",
    "msfrpc",
    "paramiko",
    "scapy",
    "nmap",
    "impacket",
    "__future__",
}


# =============================================================================
# SOURCE INDEX
# =============================================================================


class SourceIndex:
    """Mapping module_name -> source string dans rag_chunks."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._module_to_source: dict = {}
        self._known_sources: set = set()
        self._source_to_id: dict = {}
        self._id_to_source: dict = {}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT id, source FROM rag_chunks WHERE source IS NOT NULL")
            for cid, src in cur.fetchall():
                self._known_sources.add(src)
                if src not in self._source_to_id:
                    self._source_to_id[src] = cid
                self._id_to_source[cid] = src
            conn.close()
            self._loaded = True
        except Exception:
            pass

    def resolve_module(self, module_name: str) -> Optional[str]:
        if not self._loaded:
            self.load()
        if module_name in self._module_to_source:
            return self._module_to_source[module_name]
        # Bug fix: strip leading dots for relative imports (e.g. ".forge_x" -> "forge_x")
        stripped = module_name.lstrip(".")
        if not stripped:
            self._module_to_source[module_name] = None
            return None
        if stripped.split(".")[0] in STDLIB_PREFIXES:
            return None

        m = stripped.replace(".", "/")
        for candidate_root in ("app", "tools", "recon_silo", "ctf", ""):
            cand = f"{candidate_root}/{m}.py" if candidate_root else f"{m}.py"
            for cand_var in [cand, f"LaForge/{cand}"]:
                if cand_var in self._known_sources:
                    return self._source_to_id.get(cand_var)
                for suffix in ["#chunk0", "_part0#chunk0", "#chunk1"]:
                    if f"{cand_var}{suffix}" in self._known_sources:
                        return self._source_to_id.get(f"{cand_var}{suffix}")

        self._module_to_source[module_name] = None
        return None


# =============================================================================
# AST SCANNER
# =============================================================================


class ASTScanner:
    def __init__(self):
        self.imports: list = []
        self.from_imports: dict[str, str] = {}  # {imported_name: source_module}
        self.called_names: set = set()
        self.defined_names: set = set()

    def scan_file(self, file_path: Path) -> bool:
        try:
            if file_path.stat().st_size > MAX_FILE_SIZE:
                return False
            tree = ast.parse(file_path.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        self.imports.append(node.module)
                        for alias in node.names:
                            self.from_imports[alias.asname or alias.name] = node.module
                elif isinstance(node, ast.Call):
                    name = self._extract_call_name(node.func)
                    if name:
                        self.called_names.add(name)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self.defined_names.add(node.name)
            return True
        except Exception:
            return False

    def _extract_call_name(self, node) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None


# =============================================================================
# GRAPH LINKER
# =============================================================================


class GraphLinker:
    """Construit et exploite les edges structurels et sémantiques."""

    def __init__(self, db_path: str = None, root_path: Path = None):
        self.db_path = db_path or str(DB)
        self.root = root_path or ROOT
        self.index = SourceIndex(self.db_path)

    # --- PPR & Expansion ---

    @lru_cache(maxsize=512)  # noqa: B019 -- linker is singleton, no leak risk
    def get_neighbors(self, node_id: str) -> List[Tuple[str, float, str]]:
        """Voisins sortants (dst, weight, type). LRU cached."""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT dst, weight, rel_type FROM rag_graph_edges WHERE src = ?", (node_id,))
            res = cur.fetchall()
            conn.close()
            return res
        except Exception:
            return []

    def edge_weight(self, src_id: str, dst_id: str, trust_weight: float = 1.0) -> float:
        """Poids unifié : CosineSimilarity(BGE-M3) * trust_weight."""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT embedding FROM rag_chunks WHERE id = ?", (src_id,))
            r1 = cur.fetchone()
            cur.execute("SELECT embedding FROM rag_chunks WHERE id = ?", (dst_id,))
            r2 = cur.fetchone()
            conn.close()
            if not r1 or not r2:
                return 0.5 * trust_weight

            def _to_vec(b):
                if not b:
                    return None
                if isinstance(b, (bytes, bytearray)):
                    if b[:1] == b"[":
                        return np.array(json.loads(b))
                    return np.frombuffer(b, dtype=np.float32)
                return np.array(json.loads(b))

            v1, v2 = _to_vec(r1[0]), _to_vec(r2[0])
            if v1 is None or v2 is None:
                return 0.5
            norm = (np.linalg.norm(v1) * np.linalg.norm(v2)) + 1e-9
            return float(max(0, np.dot(v1, v2) / norm) * trust_weight)
        except Exception:
            return 0.1

    def personalized_pagerank(self, seed_nodes: list[str], alpha: float = 0.85, max_iter: int = 20) -> dict[str, float]:
        """Calcul PPR pour re-ranking et découverte de contexte."""
        if not seed_nodes:
            return {}
        scores = {node: 1.0 / len(seed_nodes) for node in seed_nodes}
        teleport = {node: 1.0 / len(seed_nodes) for node in seed_nodes}

        for _ in range(max_iter):
            new_scores = {}
            for node, score in scores.items():
                neighbors = self.get_neighbors(node)
                if not neighbors:
                    for s, t in teleport.items():
                        new_scores[s] = new_scores.get(s, 0.0) + (score * t)
                    continue
                sum_w = sum(w for _, w, _ in neighbors)
                for dst, w, _ in neighbors:
                    new_scores[dst] = new_scores.get(dst, 0.0) + (score * alpha * (w / sum_w))
                for s, t in teleport.items():
                    new_scores[s] = new_scores.get(s, 0.0) + (score * (1 - alpha) * t)
            scores = new_scores
            total = sum(scores.values())
            for n in scores:
                scores[n] /= total
        return scores

    async def graph_ppr_search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """Expansion sémantique + Rerank PPR."""
        try:
            from nokido_agent.app.forge_rag_engine import rag_engine

            initial_hits = await rag_engine.search(query, k=5)
            if not initial_hits:
                return []

            seed_ids = [h["id"] for h in initial_hits]
            ppr_results = self.personalized_pagerank(seed_ids)
            sorted_nodes = sorted(ppr_results.items(), key=lambda x: -x[1])[: top_k * 2]
            node_ids = [n[0] for n in sorted_nodes]

            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            meta = {}
            for nid in node_ids:
                cur.execute("SELECT text, source, domain FROM rag_chunks WHERE id = ?", (nid,))
                r = cur.fetchone()
                if r:
                    meta[nid] = {"text": r[0], "source": r[1], "domain": r[2]}
            conn.close()

            final = []
            for nid, score in sorted_nodes:
                if nid in meta:
                    item = meta[nid]
                    item.update({"id": nid, "ppr_score": round(score, 4)})
                    final.append(item)
                    if len(final) >= top_k:
                        break
            return final
        except Exception as e:
            logger.error(f"graph_ppr_search failed: {e}")
            return []

    def propagate_cve_risk(self, cve_id: str, entry_nodes: list[str]) -> dict[str, float]:
        """Propage le risque d'une CVE via les edges du graphe avec décroissance."""
        if not entry_nodes:
            return {}

        scores = {}
        decay_factor = 0.8

        # queue elements: (node_id, current_score, depth)
        queue = [(n, 1.0, 0) for n in entry_nodes]

        while queue:
            node, current_score, depth = queue.pop(0)

            # Keep highest score, prevent cycles
            if node not in scores or current_score > scores[node]:
                scores[node] = current_score
            else:
                continue

            if depth >= 5:
                continue

            # Propagation towards neighbors (or from neighbors depending on direction,
            # usually if module A imports B, and B has CVE, risk flows to A.
            # In our graph, src imports dst, so dst has CVE, risk flows to src?
            # get_neighbors(node) returns outgoing edges (node -> dst)
            # If we want risk to flow backwards, we need incoming edges.
            # But the prompt says "propager via edges du graphe avec décroissance 0.8^depth".
            # We'll just use the edges as requested.

            try:
                conn = sqlite3.connect(self.db_path)
                cur = conn.cursor()
                # To propagate vulnerability up the call chain, we need incoming edges (dst = node)
                # But let's follow the standard: we just query where src = node OR dst = node
                cur.execute("SELECT src FROM rag_graph_edges WHERE dst = ?", (node,))
                incoming = cur.fetchall()
                conn.close()
                for (src_id,) in incoming:
                    queue.append((src_id, current_score * decay_factor, depth + 1))
            except Exception:
                pass

        # Resolve to module names and get top 10
        module_scores = {}
        self.index.load()

        for node, score in scores.items():
            mod_name = self.index._id_to_source.get(node, node)
            if mod_name not in module_scores or score > module_scores[mod_name]:
                module_scores[mod_name] = round(score, 4)

        sorted_modules = sorted(module_scores.items(), key=lambda x: -x[1])[:10]
        return dict(sorted_modules)

    # --- Build Logic ---

    def build_ast_edges(self, verbose: bool = False) -> dict:
        t0 = time.time()
        files = self._iter_py_files()
        scanners: dict = {}
        for f in files:
            scanner = ASTScanner()
            if scanner.scan_file(f):
                scanners[self._file_to_source_prefix(f)] = scanner

        def_name_to_sources: dict = {}
        for src, scanner in scanners.items():
            for name in scanner.defined_names:
                def_name_to_sources.setdefault(name, []).append(src)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        batch = []
        for src, scanner in scanners.items():
            src_chunk = self._file_src_to_chunk_id(src)
            if not src_chunk:
                continue
            for mod_name in scanner.imports:
                dst = self.index.resolve_module(mod_name)
                if dst and dst != src_chunk:
                    batch.append((src_chunk, dst, "IMPORTS", 1.0))
            for called in scanner.called_names:
                dsts = def_name_to_sources.get(called, [])
                if len(dsts) == 1:
                    dst_chunk = self._file_src_to_chunk_id(dsts[0])
                    if dst_chunk and dst_chunk != src_chunk:
                        batch.append((src_chunk, dst_chunk, "CALLS", 0.7))
                elif len(dsts) > 1:
                    # Bug fix: ambiguous calls were silently dropped — add all with lower weight
                    for defining_src in dsts:
                        dst_chunk = self._file_src_to_chunk_id(defining_src)
                        if dst_chunk and dst_chunk != src_chunk:
                            batch.append((src_chunk, dst_chunk, "CALLS_AMBIGUOUS", 0.4))

        # CALLS_CROSS: follow from-import chains recursively (max depth=3)
        def _resolve_chain(called: str, defining_src: str, visited: set, depth: int) -> list[str]:
            if depth >= 3 or defining_src in visited:
                return []
            visited.add(defining_src)
            sc = scanners.get(defining_src)
            if not sc:
                return []
            origin = sc.from_imports.get(called)
            if not origin:
                # Bug fix: if called defined in this module's defined_names, chain terminates here (it's local)
                # If not in from_imports, check if it's re-exported via a module that defines it
                for imp_mod in sc.imports:
                    if imp_mod.split(".")[0] not in STDLIB_PREFIXES:
                        return [imp_mod]
                return []
            if origin.split(".")[0] in STDLIB_PREFIXES:
                return []
            chain = [origin]
            chain.extend(_resolve_chain(called, origin, visited, depth + 1))
            return chain

        for src, scanner in scanners.items():
            src_chunk = self._file_src_to_chunk_id(src)
            if not src_chunk:
                continue
            for called in scanner.called_names:
                dsts = def_name_to_sources.get(called, [])
                for defining_src in dsts:
                    for cross_mod in _resolve_chain(called, defining_src, set(), 0):
                        dst_chunk = self.index.resolve_module(cross_mod)
                        if dst_chunk and dst_chunk != src_chunk:
                            batch.append((src_chunk, dst_chunk, "CALLS_CROSS", 0.5))

        cur.executemany(
            "INSERT OR IGNORE INTO rag_graph_edges (src, dst, rel_type, weight) VALUES (?, ?, ?, ?)", list(set(batch))
        )
        conn.commit()
        conn.close()
        return {"imports_calls": len(batch), "time_s": round(time.time() - t0, 2)}

    def _file_to_source_prefix(self, f) -> str:
        """Relative POSIX path from repo root, used as source key for scanners."""
        try:
            return str(f.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(f).replace("\\", "/")

    def _iter_py_files(self) -> list:
        files = []
        for base in ["app", "tools", "recon_silo", "ctf"]:
            bp = self.root / base
            if bp.exists():
                for pf in bp.rglob("*.py"):
                    if not any(p in pf.parts for p in EXCLUDE_DIRS):
                        files.append(pf)
        return files

    def _file_src_to_chunk_id(self, src_path: str) -> Optional[str]:
        self.index.load()
        sn = src_path.replace("\\", "/")
        for ks in self.index._known_sources:
            kn = ks.replace("\\", "/")
            if kn == sn or kn.endswith("/" + sn):
                return self.index._source_to_id.get(ks)
            for suff in ["#chunk0", "_part0#chunk0"]:
                if kn == sn + suff or kn.endswith("/" + sn + suff):
                    return self.index._source_to_id.get(ks)
        return None

    def get_impacted_by_change(self, file_path: str) -> list:
        self.index.load()
        dst = self._file_src_to_chunk_id(file_path.replace("\\", "/"))
        if not dst:
            return []
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT src, rel_type, weight FROM rag_graph_edges WHERE dst = ?", (dst,))
        rows = cur.fetchall()
        conn.close()
        return [{"source": self.index._id_to_source.get(r[0], r[0]), "type": r[1], "w": r[2]} for r in rows]


if __name__ == "__main__":
    gl = GraphLinker()
    print(gl.build_ast_edges())
