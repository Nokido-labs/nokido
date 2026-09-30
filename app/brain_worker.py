"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_165156_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns/Raises
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
brain_worker.py — Sidecar ML de La Forge  (v2 — PriorityQueue)
===============================================================
Processus DÉTACHÉ de la TUI Textual. Contient Torch / sentence-transformers
/ onnxruntime-genai. Communique via ZeroMQ REP sur 127.0.0.1:5557.

Architecture :
  Thread principal  → ZMQ REP (répond immédiatement : task_id ou résultat)
  Thread worker     → PriorityQueue → traitement ML séquentiel

Priorités :
  0  = action utilisateur  (passe devant tout)
  5  = warmup RAG          (démarrage)
 10  = boucle background   (peut attendre)

Protocole :
  ping            → pong
  status          → {embedder, generator, dim, queue_size, pending}
  submit          → {task_id}   (réponse IMMÉDIATE)
  check task_id   → {status: pending|completed|error, data?, error?}
  shutdown        → bye
"""

# Titre processus
try:
    import ctypes as _ct

    _ct.windll.kernel32.SetConsoleTitleW("Nokido Brain Worker [NPU :5557]")
except Exception:
    pass

import argparse
import json
import logging
import os
import queue
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# ── Env vars avant tout import ML ────────────────────────────────────────────
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] brain - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("brain")

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_PORT = 5557
PUB_PORT = 5558  # PUB/SUB — chunks SSH + stream LLM
MINILM_MODEL_ID = "BAAI/bge-m3"  # 1024d — recall@10 +8pp vs MiniLM (bge_m3_vs_minilm.md)
CACHE_TTL_SECONDS = 300  # résultats gardés 5 min

# ── Parallel embed workers (Python 3.14t free-threaded / nogil) ──────────────
_IS_NOGIL: bool = hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()
N_EMBED_WORKERS: int = int(os.environ.get("BRAIN_WORKER_THREADS", "4" if _IS_NOGIL else "1"))

# Topic PUB pour les chunks SSH
TOPIC_SSH = b"ssh"
TOPIC_OLLAMA = b"ollama"

# =============================================================================
# NPU / EXECUTION PROVIDERS — Ryzen 7 8700G (Phoenix)
# Cascade : NPU (VitisAI) > iGPU (DirectML) > CPU
# =============================================================================
try:
    from nokido_agent.app.forge_npu import get_npu_manager, OnnxEmbedderNPU, EP

    _npu_mgr = get_npu_manager()
    HAS_FORGE_NPU = True
    logger.info(f"[NPU] Best EP : {_npu_mgr.best_ep().value.upper()}")
except ImportError:
    HAS_FORGE_NPU = False
    _npu_mgr = None
    EP = None
    logger.info("[NPU] forge_npu absent — CPU seulement")

# =============================================================================
# TREE-SITTER — Sentinelle sécurité + chirurgie bytewise
# =============================================================================

HAS_TREE_SITTER = False
_TS_ERROR = ""

# Modules/fonctions dangereux — filtrés en Python après capture
_BLOCKED_MODULES = {"os", "subprocess", "shutil", "socket", "ctypes", "importlib"}
_BLOCKED_OBJECTS = {"os", "subprocess", "shutil", "sys"}
_BLOCKED_FUNCS = {"eval", "exec", "__import__", "compile"}

ts_parser = None

try:
    from tree_sitter import Language, Parser
    import tree_sitter_python as tspython

    PY_LANGUAGE = Language(tspython.language())

    # API 0.21.x : Parser() puis set_language()
    # API 0.23+  : Parser(language)
    try:
        ts_parser = Parser()
        ts_parser.set_language(PY_LANGUAGE)
    except AttributeError:
        ts_parser = Parser(PY_LANGUAGE)

    # Validation rapide
    _test = ts_parser.parse(b"x = 1")
    assert _test.root_node is not None and not _test.root_node.has_error

    HAS_TREE_SITTER = True
    logger.info("tree-sitter Python chargé (tree-walk mode)")
except ImportError as e:
    _TS_ERROR = str(e)
    logger.info(f"tree-sitter non disponible ({e}) — audit AST natif sera utilisé")
except Exception as e:
    _TS_ERROR = str(e)
    logger.warning(f"tree-sitter init échoué : {e}")


# ── Helpers tree-walk (pas de Query, 100% compatible) ─────────────────────────


def _walk_tree(node: object) -> Iterable[object]:
    """Generator yielding all nodes in a tree-sitter structure recursively."""
    yield node
    for child in node.children:
        yield from _walk_tree(child)


def _node_text(node: object) -> str:
    """Texte UTF-8 d'un nœud."""
    return node.text.decode("utf8") if node.text else ""


def _find_function_node(root_node: object, target_name: str) -> object:
    """
    Trouve le premier nœud function_definition dont le nom == target_name.
    Retourne le nœud ou None.
    """
    for node in _walk_tree(root_node):
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node and _node_text(name_node) == target_name:
                return node
    return None


_BASE = Path(__file__).parent
_ROOT = _BASE.parent  # dossier racine du projet (parent de app/)
# Chemins GPU (DirectML) et CPU — relatifs à la racine du projet
PHI35_DIRECTML = _ROOT / "models" / "gpu" / "gpu-int4-awq-block-128"
PHI35_CPU = _ROOT / "models" / "cpu_and_mobile" / "cpu-int4-awq-block-128-acc-level-4"

# =============================================================================
# MODÈLES ML
# =============================================================================


class Embedder:
    """
    Embedder MiniLM avec cascade automatique EP :
      NPU (VitisAI) > DirectML (Radeon 780M) > CPU (sentence-transformers)
    """

    def __init__(self) -> None:
        """Initialise."""
        self._model = None  # sentence-transformers (fallback CPU)
        self._onnx_emb = None  # OnnxEmbedderNPU si disponible
        self._dim = 0
        self._ready = False
        self._backend = "cpu"
        self._lock = threading.Lock()

    def load(self) -> bool:
        """Load."""
        if self._ready:
            return True

        # ── Tentative NPU/DirectML via ONNX Runtime ───────────────────────
        if HAS_FORGE_NPU and _npu_mgr is not None and EP is not None:
            best = _npu_mgr.best_ep()
            if best.value in ("npu", "directml"):
                try:
                    onnx_emb = OnnxEmbedderNPU(_npu_mgr)
                    if onnx_emb.load():
                        self._onnx_emb = onnx_emb
                        self._dim = onnx_emb.dim
                        self._backend = onnx_emb.ep
                        self._ready = True
                        logger.info(f"Embedder OK [{self._backend.upper()}] via ONNX Runtime")
                        return True
                    logger.info("[NPU] OnnxEmbedderNPU non chargé — fallback CPU")
                except Exception as e:
                    logger.info(f"[NPU] fallback CPU ({e})")

        # ── Fallback CPU : sentence-transformers ───────────────────────────
        try:
            logger.info(f"Chargement embedder CPU : {MINILM_MODEL_ID}…")
            t0 = time.monotonic()
            from sentence_transformers import SentenceTransformer

            with self._lock:
                self._model = SentenceTransformer(MINILM_MODEL_ID, device="cpu")
                self._dim = self._model.get_sentence_embedding_dimension()
                self._backend = "cpu"
                self._ready = True
            logger.info(f"Embedder CPU OK — dim={self._dim} en {time.monotonic() - t0:.2f}s")
            return True
        except Exception as e:
            logger.warning(f"sentence-transformers indisponible : {e}")
            return False

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Encode."""
        if not self._ready or not texts:
            return []
        if self._onnx_emb is not None:
            result = self._onnx_emb.encode(texts)
            if result:
                return result
        with self._lock:
            if self._model is None:
                return []
            try:
                vecs = self._model.encode(
                    texts,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                return [v.tolist() for v in vecs]
            except Exception as e:
                logger.error(f"encode CPU : {e}")
                return []

    @property
    def ready(self) -> bool:
        """Ready."""
        return self._ready

    @property
    def dim(self) -> int:
        """Dim."""
        return self._dim

    @property
    def backend(self) -> str:
        """Backend."""
        return self._backend


class Generator:
    """Phi-3.5 ONNX — chargé si modèle présent."""

    def __init__(self) -> None:
        """Initialise."""
        self._og = None
        self._model = None
        self._tok = None
        self._ready = False
        self._backend = "none"
        self._lock = threading.Lock()

    def load(self) -> bool:
        """Load."""
        # Sécurité : ne jamais charger le modèle GPU/DirectML (crash iGPU partagé)
        # Retirer ce commentaire uniquement après validation stabilité DirectML
        phi = PHI35_CPU if PHI35_CPU.exists() else None
        if phi is None:
            logger.info(
                "Phi-3.5 non installé (optionnel). "
                "Pour activer : huggingface-cli download "
                "microsoft/Phi-3.5-mini-instruct-onnx "
                "--include 'gpu/*' --local-dir ./models"
            )
            return False
        try:
            logger.info(f"Chargement generator : {phi.parent.name}…")
            t0 = time.monotonic()
            import onnxruntime_genai as og

            with self._lock:
                self._og = og
                self._model = og.Model(str(phi))
                self._tok = og.Tokenizer(self._model)
                self._backend = "directml" if ("directml" in str(phi) or "gpu" in str(phi)) else "cpu"
                self._ready = True
            logger.info(f"Generator OK [{self._backend.upper()}] en {time.monotonic() - t0:.2f}s")
            return True
        except Exception as e:
            logger.warning(f"onnxruntime-genai indisponible : {e}")
            return False

    def generate(self, messages: List[Dict], max_tokens: int = 512) -> str:
        """Generate."""
        if not self._ready:
            raise RuntimeError("Generator non chargé")
        prompt = _build_phi35_prompt(messages)
        with self._lock:
            tokens = self._tok.encode(prompt)
            params = self._og.GeneratorParams(self._model)
            params.max_length = len(tokens) + max_tokens
            params.input_ids = tokens
            gen = self._og.Generator(self._model, params)
            parts = []
            while not gen.is_done():
                gen.compute_logits()
                gen.generate_next_token()
                parts.append(self._tok.decode([gen.get_next_tokens()[0]]))
            del gen
        return "".join(parts)

    def unload(self) -> None:
        """Unload."""
        with self._lock:
            # Destruction explicite pour éviter les fuites OGA (C++ backend)
            try:
                if self._tok is not None:
                    del self._tok
            except Exception:
                pass
            try:
                if self._model is not None:
                    del self._model
            except Exception:
                pass
            self._model = None
            self._tok = None
            self._og = None
            self._ready = False
            import gc

            gc.collect()

    @property
    def ready(self) -> bool:
        """Ready."""
        return self._ready

    @property
    def backend(self) -> str:
        """Backend."""
        return self._backend


def _build_phi35_prompt(messages: List[Dict]) -> str:
    """build phi35 prompt."""
    parts = []
    for m in messages:
        role, content = m.get("role", "user"), m.get("content", "")
        if role == "system":
            parts.append(f"<|system|>\n{content}<|end|>\n")
        elif role == "user":
            parts.append(f"<|user|>\n{content}<|end|>\n")
        elif role == "assistant":
            parts.append(f"<|assistant|>\n{content}<|end|>\n")
    parts.append("<|assistant|>\n")
    return "".join(parts)


# =============================================================================
# TREE-SITTER — AUDIT SÉCURITÉ + CHIRURGIE BYTEWISE
# =============================================================================


def security_audit(code: str) -> dict:
    """
    Analyse tree-sitter du code Python.
    Retourne {"safe": bool, "message": str, "violations": [...]}
    Fallback sur ast natif si tree-sitter non disponible.
    """
    if not HAS_TREE_SITTER:
        return _fallback_ast_audit(code)

    try:
        tree = ts_parser.parse(bytes(code, "utf8"))
        root = tree.root_node

        # 1. Erreur de syntaxe (nœud ERROR dans le CST)
        if root.has_error:
            return {
                "safe": False,
                "message": "Syntaxe invalide (nœud ERROR dans le CST tree-sitter)",
                "violations": ["SYNTAX_ERROR"],
            }

        # 2. Scan de sécurité par tree-walk (compatible toutes versions)
        violations = []

        for node in _walk_tree(root):
            # import os / import subprocess ...
            if node.type == "import_statement":
                for child in _walk_tree(node):
                    if child.type == "dotted_name" or child.type == "identifier":
                        name = _node_text(child).split(".")[0]
                        if name in _BLOCKED_MODULES:
                            violations.append(f"import:{name}")

            # from os import ... / from subprocess import ...
            elif node.type == "import_from_statement":
                mod_node = node.child_by_field_name("module_name")
                if mod_node:
                    name = _node_text(mod_node).split(".")[0]
                    if name in _BLOCKED_MODULES:
                        violations.append(f"from:{name}")

            # os.system(...), subprocess.run(...) etc.
            elif node.type == "call":
                func = node.child_by_field_name("function")
                if func and func.type == "attribute":
                    obj = func.child_by_field_name("object")
                    attr = func.child_by_field_name("attribute")
                    if obj and _node_text(obj) in _BLOCKED_OBJECTS:
                        violations.append(f"call:{_node_text(obj)}.{_node_text(attr) if attr else '?'}")
                # eval(...), exec(...), __import__(...)
                elif func and func.type == "identifier":
                    name = _node_text(func)
                    if name in _BLOCKED_FUNCS:
                        violations.append(f"builtin:{name}()")

        violations = list(set(violations))
        if violations:
            return {
                "safe": False,
                "message": f"Accès interdit détecté : {violations}",
                "violations": violations,
            }

        return {"safe": True, "message": "Audit AST & sécurité : OK", "violations": []}

    except Exception as e:
        return {"safe": False, "message": f"Crash audit tree-sitter : {e}", "violations": []}


def _fallback_ast_audit(code: str) -> dict:
    """Fallback avec ast natif si tree-sitter absent."""
    import ast

    try:
        ast.parse(code)
    except SyntaxError as e:
        return {
            "safe": False,
            "message": f"SyntaxError l.{e.lineno}: {e.msg}",
            "violations": ["SYNTAX_ERROR"],
        }
    return {"safe": True, "message": "Audit AST natif : OK (tree-sitter non dispo)", "violations": []}


def analyze_code(code: str) -> dict:
    """
    Analyse enrichie d'un snippet Python pour le RAG.
    Retourne des métadonnées ML : complexité, libs, score sécu, structure.
    """
    import ast as _ast

    result = {
        "cyclomatic_complexity": 0,
        "libraries": [],
        "functions": [],
        "classes": [],
        "loc": 0,
        "sloc": 0,  # lignes non vides
        "security_score": 1.0,  # 1.0 = clean, 0.0 = dangereux
        "has_docstrings": False,
        "has_type_hints": False,
    }

    lines = code.split("\n")
    result["loc"] = len(lines)
    result["sloc"] = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))

    # ── Parse AST ─────────────────────────────────────────────────────────
    try:
        tree = _ast.parse(code)
    except SyntaxError:
        result["security_score"] = 0.0
        return result

    # ── Complexité cyclomatique (branches décisionnelles) ─────────────────
    cc = 1  # base
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.If, _ast.While, _ast.For, _ast.ExceptHandler)):
            cc += 1
        elif isinstance(node, _ast.BoolOp):
            cc += len(node.values) - 1  # and/or ajoutent des branches
        elif isinstance(node, (_ast.Assert, _ast.With)):
            cc += 1
    result["cyclomatic_complexity"] = cc

    # ── Bibliothèques importées ───────────────────────────────────────────
    libs = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                libs.add(alias.name.split(".")[0])
        elif isinstance(node, _ast.ImportFrom):
            if node.module:
                libs.add(node.module.split(".")[0])
    result["libraries"] = sorted(libs)

    # ── Fonctions et classes ──────────────────────────────────────────────
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            result["functions"].append(node.name)
            ds = _ast.get_docstring(node)
            if ds:
                result["has_docstrings"] = True
            # Type hints
            if node.returns or any(a.annotation for a in node.args.args):
                result["has_type_hints"] = True
        elif isinstance(node, _ast.ClassDef):
            result["classes"].append(node.name)
            if _ast.get_docstring(node):
                result["has_docstrings"] = True

    # ── Score sécurité ────────────────────────────────────────────────────
    dangerous_libs = {"os", "subprocess", "shutil", "ctypes", "importlib", "socket", "pickle"}
    dangerous_calls = {"eval", "exec", "__import__", "compile"}
    sec = 1.0
    for lib in libs:
        if lib in dangerous_libs:
            sec -= 0.15
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            fn = getattr(node, "func", None)
            if fn and isinstance(fn, _ast.Name) and fn.id in dangerous_calls:
                sec -= 0.25
    result["security_score"] = round(max(0.0, sec), 2)

    return result


def locate_function(source_bytes: bytes, target_name: str) -> Optional[dict]:
    """
    Localise une fonction par nom dans le source via tree-sitter.
    Retourne {"start_byte", "end_byte", "start_line", "indent"} ou None.
    """
    if not HAS_TREE_SITTER:
        return None

    tree = ts_parser.parse(source_bytes)
    func_node = _find_function_node(tree.root_node, target_name)
    if func_node is None:
        return None

    return {
        "start_byte": func_node.start_byte,
        "end_byte": func_node.end_byte,
        "start_line": func_node.start_point[0] + 1,
        "indent": func_node.start_point[1],
    }


def apply_surgery(source: str, target_name: str, new_code: str) -> dict:
    """
    Remplace une fonction dans source par new_code via byte-slicing tree-sitter.
    Préserve 100% du formatage/commentaires hors de la fonction cible.

    Retourne {
        "success": bool,
        "message": str,
        "result":  str (nouveau source complet) si success,
        "backup":  str (ancien code de la fonction) si success,
    }
    """
    if not HAS_TREE_SITTER:
        return {"success": False, "message": "tree-sitter non disponible", "result": "", "backup": ""}

    source_bytes = bytes(source, "utf8")

    # 1. Audit sécurité du nouveau code
    audit = security_audit(new_code)
    if not audit["safe"]:
        return {
            "success": False,
            "message": f"Nouveau code rejeté — {audit['message']}",
            "result": "",
            "backup": "",
        }

    # 2. Vérifier que new_code est syntaxiquement valide
    new_tree = ts_parser.parse(bytes(new_code, "utf8"))
    if new_tree.root_node.has_error:
        return {
            "success": False,
            "message": "Nouveau code a des erreurs de syntaxe",
            "result": "",
            "backup": "",
        }

    # 3. Localiser la fonction cible
    loc = locate_function(source_bytes, target_name)
    if loc is None:
        return {
            "success": False,
            "message": f"Fonction '{target_name}' introuvable dans le source",
            "result": "",
            "backup": "",
        }

    # 4. Ajuster l'indentation du new_code pour matcher l'original
    target_indent = loc["indent"]
    adjusted_lines = []
    for i, line in enumerate(new_code.splitlines(keepends=True)):
        if i == 0:
            # Première ligne : indenter au bon niveau
            adjusted_lines.append(" " * target_indent + line.lstrip())
        elif line.strip():
            # Lignes non-vides : recalculer l'indentation relative
            stripped = line.lstrip()
            original_indent = len(line) - len(stripped)
            # On suppose que le new_code est indenté à partir de la colonne 0
            # → on ajoute target_indent à chaque ligne
            adjusted_lines.append(" " * (target_indent + original_indent) + stripped)
        else:
            adjusted_lines.append(line)
    adjusted_code = "".join(adjusted_lines)

    # 5. Byte-slicing chirurgical
    backup_code = source_bytes[loc["start_byte"] : loc["end_byte"]].decode("utf8")
    new_source = (
        source_bytes[: loc["start_byte"]].decode("utf8")
        + adjusted_code
        + source_bytes[loc["end_byte"] :].decode("utf8")
    )

    # 6. Validation post-chirurgie : le résultat doit se parser sans erreur
    check_tree = ts_parser.parse(bytes(new_source, "utf8"))
    if check_tree.root_node.has_error:
        return {
            "success": False,
            "message": "Code résultant invalide après chirurgie (erreur CST)",
            "result": "",
            "backup": backup_code,
        }

    lines_before = backup_code.count("\n") + 1
    lines_after = adjusted_code.count("\n") + 1

    return {
        "success": True,
        "message": f"Chirurgie OK — {target_name} ({lines_before}→{lines_after} lignes)",
        "result": new_source,
        "backup": backup_code,
    }


# =============================================================================
# PRIORITY QUEUE + WORKER THREAD
# =============================================================================


class TaskWorker:
    """
    Thread ML séquentiel alimenté par une PriorityQueue.
    Le thread principal ZMQ ne bloque jamais : il enfile et répond task_id.
    """

    def __init__(self, embedder: Embedder, generator: Generator) -> None:
        """Initialise."""
        self._embedder = embedder
        self._generator = generator
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._cache: Dict[str, Dict] = {}
        self._cache_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None  # kept for compat
        self._embedders: List[Embedder] = []
        self._threads: List[threading.Thread] = []

    # ── Cycle de vie ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start N embed worker threads (N=N_EMBED_WORKERS, >=1)."""
        self._running = True
        # Instantiate N Embedder clones — each owns its ONNX session so no lock contention.
        # The primary self._embedder (passed at __init__) is always index-0 to preserve
        # existing callers that inspect self._embedder directly.
        self._embedders = []
        for i in range(N_EMBED_WORKERS):
            if i == 0:
                emb = self._embedder
            else:
                emb = Embedder()
                emb.load()
            self._embedders.append(emb)

        self._threads = [
            threading.Thread(
                target=self._worker_loop,
                args=(emb,),
                name=f"brain-ml-worker-{i}",
                daemon=True,
            )
            for i, emb in enumerate(self._embedders)
        ]
        for t in self._threads:
            t.start()
        # Back-compat: keep self._thread pointing at thread-0
        self._thread = self._threads[0]
        logger.info(f"Worker ML démarré — {N_EMBED_WORKERS} thread(s) [nogil={_IS_NOGIL}]")

    def stop(self) -> None:
        """Stop all worker threads."""
        self._running = False
        for t in self._threads:
            t.join(timeout=2.0)

    # ── API publique (appelée depuis le thread ZMQ) ───────────────────────────

    def submit(self, task_type: str, payload: dict, priority: int) -> str:
        """Enfile une tâche — retourne son ID immédiatement."""
        task_id = f"t_{int(time.time() * 1000)}"
        expires = datetime.now(timezone.utc) + timedelta(seconds=CACHE_TTL_SECONDS)
        with self._cache_lock:
            self._cache[task_id] = {"status": "pending", "expires": expires}
        # Tuple : (priorité, timestamp, tâche) — timestamp pour FIFO à priorité égale
        self._queue.put((priority, time.time(), {"id": task_id, "type": task_type, **payload}))
        logger.debug(f"[Prio:{priority}] soumis {task_type} {task_id} (queue={self._queue.qsize()})")
        return task_id

    def check(self, task_id: str) -> dict:
        """Check."""
        with self._cache_lock:
            return dict(self._cache.get(task_id, {"status": "not_found"}))

    @property
    def queue_size(self) -> int:
        """Queue size."""
        return self._queue.qsize()

    @property
    def pending_count(self) -> int:
        """Pending count."""
        with self._cache_lock:
            return sum(1 for v in self._cache.values() if v["status"] == "pending")

    # ── Boucle interne ────────────────────────────────────────────────────────

    def _worker_loop(self, embedder: Embedder) -> None:
        """Worker loop for a dedicated Embedder instance (N_EMBED_WORKERS parallel threads).

        Identical logic to _loop() but uses the caller-supplied *embedder* arg
        instead of self._embedder so that each thread owns an independent ONNX
        session — critical for Python 3.14t free-threaded (nogil) where multiple
        threads genuinely run in parallel.  The shared PriorityQueue is thread-safe
        by design; self._cache writes are protected by self._cache_lock.
        """
        while self._running:
            try:
                priority, ts, task = self._queue.get(timeout=0.5)
            except queue.Empty:
                self._cleanup_cache()
                continue

            task_id = task["id"]
            task_type = task["type"]
            wait_s = time.time() - ts
            logger.info(f"[Prio:{priority}] {task_type} {task_id} (attente {wait_s:.1f}s)")

            try:
                data = self._process_with_embedder(task_type, task, embedder)
                expires = datetime.now(timezone.utc) + timedelta(seconds=CACHE_TTL_SECONDS)
                with self._cache_lock:
                    self._cache[task_id] = {
                        "status": "completed",
                        "data": data,
                        "expires": expires,
                    }
            except Exception as e:
                logger.error(f"{task_type} {task_id} failed : {e}")
                expires = datetime.now(timezone.utc) + timedelta(seconds=CACHE_TTL_SECONDS)
                with self._cache_lock:
                    self._cache[task_id] = {
                        "status": "error",
                        "error": str(e),
                        "expires": expires,
                    }
            finally:
                self._queue.task_done()

    def _loop(self) -> None:
        """loop."""
        while self._running:
            try:
                priority, ts, task = self._queue.get(timeout=0.5)
            except queue.Empty:
                self._cleanup_cache()
                continue

            task_id = task["id"]
            task_type = task["type"]
            wait_s = time.time() - ts
            logger.info(f"[Prio:{priority}] {task_type} {task_id} (attente {wait_s:.1f}s)")

            try:
                data = self._process(task_type, task)
                expires = datetime.now(timezone.utc) + timedelta(seconds=CACHE_TTL_SECONDS)
                with self._cache_lock:
                    self._cache[task_id] = {
                        "status": "completed",
                        "data": data,
                        "expires": expires,
                    }
            except Exception as e:
                logger.error(f"{task_type} {task_id} failed : {e}")
                expires = datetime.now(timezone.utc) + timedelta(seconds=CACHE_TTL_SECONDS)
                with self._cache_lock:
                    self._cache[task_id] = {
                        "status": "error",
                        "error": str(e),
                        "expires": expires,
                    }
            finally:
                self._queue.task_done()

    def _process_with_embedder(self, task_type: str, task: dict, embedder: Embedder) -> Any:
        """Like _process() but uses the supplied *embedder* instance.

        Called by _worker_loop() so that each parallel thread uses its own
        ONNX session.  All non-embed task types fall through to _process()
        which uses self._embedder (index-0, safe since generate/audit/… are
        not ONNX-bound).
        """
        if task_type == "embed":
            texts = task.get("texts", [])
            if not embedder.ready:
                raise RuntimeError("Embedder non disponible")
            vecs = embedder.encode(texts)
            if not vecs:
                raise RuntimeError("encode retourné vide")

            try:
                from nokido_agent.app.forge_vec_ledger import sign_and_log as _sal

                sigs = _sal(
                    vecs=vecs,
                    texts=texts,
                    source=task.get("source", ""),
                    backend=embedder.backend,
                    agent_id="brain:embedder",
                    session_id=task.get("session_id", ""),
                )
                return {"vecs": vecs, "sigs": sigs, "signed": True}
            except Exception as _le:
                logger.debug(f"[vec_ledger] non-bloquant: {_le}")
                return vecs

        # All other task types: delegate to the original _process()
        return self._process(task_type, task)

    def _process(self, task_type: str, task: dict) -> Any:
        """process."""
        if task_type == "embed":
            texts = task.get("texts", [])
            if not self._embedder.ready:
                raise RuntimeError("Embedder non disponible")
            vecs = self._embedder.encode(texts)
            if not vecs:
                raise RuntimeError("encode retourné vide")

            # ── Signature cryptographique + Ledger Ring 3 ─────────────────────
            # Overhead mesuré : ~0.006ms/chunk → négligeable vs 14ms NPU
            # Hash SHA256(float32 bytes) + HMAC signé localement
            # Inscrit en event_log ring=3 (promotion ultérieure par PromOrch)
            try:
                from nokido_agent.app.forge_vec_ledger import sign_and_log as _sal

                sigs = _sal(
                    vecs=vecs,
                    texts=texts,
                    source=task.get("source", ""),
                    backend=self._embedder.backend,
                    agent_id="brain:embedder",
                    session_id=task.get("session_id", ""),
                )
                # Retourner vecs + signatures en une réponse atomique
                return {"vecs": vecs, "sigs": sigs, "signed": True}
            except Exception as _le:
                logger.debug(f"[vec_ledger] non-bloquant: {_le}")
                return vecs  # fallback sans signature

        if task_type in ("generate", "stream"):
            if not self._generator.ready:
                raise RuntimeError("Generator non disponible")
            return self._generator.generate(
                task.get("messages", []),
                task.get("max_tokens", 512),
            )

        if task_type == "audit":
            code = task.get("code", "")
            return security_audit(code)

        if task_type == "analyze":
            code = task.get("code", "")
            return analyze_code(code)

        if task_type == "surgery":
            source = task.get("source", "")
            target_name = task.get("target_name", "")
            new_code = task.get("new_code", "")
            return apply_surgery(source, target_name, new_code)

        if task_type == "locate":
            source = task.get("source", "")
            target_name = task.get("target_name", "")
            source_bytes = bytes(source, "utf8")
            loc = locate_function(source_bytes, target_name)
            if loc is None:
                return {"found": False, "target": target_name}
            return {"found": True, **loc, "target": target_name}

        raise ValueError(f"Type inconnu : {task_type!r}")

    def _cleanup_cache(self) -> None:
        """cleanup cache."""
        now = datetime.now(timezone.utc)
        with self._cache_lock:
            expired = [k for k, v in self._cache.items() if v["expires"] < now]
            for k in expired:
                del self._cache[k]
        if expired:
            logger.debug(f"Cache : {len(expired)} entrées expirées supprimées")


# =============================================================================
# SSH KEEP-ALIVE MANAGER
# Maintient une connexion asyncssh persistante dans un thread dédié.
# Les commandes arrivent via une queue interne et le résultat est
# publié sur le socket ZMQ PUB (topic b"ssh:<req_id>").
# =============================================================================


class SshManager:
    """
    Gère une connexion asyncssh persistante dans un thread asyncio dédié.
    Expose run(cmd, req_id, pub_fn) : exécute une commande SSH et publie
    les chunks via pub_fn(topic, chunk_dict).
    """

    def __init__(self) -> None:
        """Initialise."""
        self._conn = None
        self._lock = threading.Lock()
        self._loop = None
        self._thread = None
        self._running = False
        self._cmd_queue = None  # asyncio.Queue, créée dans le thread
        self._settings = None  # dict {host, port, user, key}
        self._pub_fn = None  # callable(topic: bytes, payload: dict)
        self._connected = False
        self._keepalive_task = None

    def configure(self, host: str, port: int, user: str, key_path: str, pub_fn: object) -> None:
        """Configure avant start()."""
        self._settings = dict(host=host, port=port, user=user, key_path=key_path)
        self._pub_fn = pub_fn

    def start(self) -> None:
        """Lance le thread asyncio dédié SSH."""
        if self._settings is None:
            logger.warning("[SSH] configure() non appelé")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="brain-ssh", daemon=True)
        self._thread.start()
        logger.info(f"[SSH] thread démarré → {self._settings['host']}")

    def stop(self) -> None:
        """Stop."""
        self._running = False

    def enqueue(self, cmd: str, req_id: str, sudo: bool = False) -> None:
        """Thread-safe : enfile une commande SSH depuis le thread ZMQ."""
        if self._loop and self._cmd_queue:
            self._loop.call_soon_threadsafe(self._cmd_queue.put_nowait, {"cmd": cmd, "req_id": req_id, "sudo": sudo})

    # ── Boucle asyncio interne ────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """run loop."""
        import asyncio as _aio

        self._loop = _aio.new_event_loop()
        _aio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())
        self._loop.close()

    async def _main(self) -> None:
        """main."""
        import asyncio as _aio

        self._cmd_queue = _aio.Queue()
        await self._connect()
        # Garder-alive : envoie un keepalive toutes les 30s
        self._keepalive_task = _aio.create_task(self._keepalive())
        while self._running:
            try:
                item = await _aio.wait_for(self._cmd_queue.get(), timeout=1.0)
                _aio.create_task(self._exec(**item))
            except _aio.TimeoutError:
                continue
        if self._conn:
            self._conn.close()

    async def _connect(self) -> None:
        """connect."""
        try:
            import asyncssh as _assh

            s = self._settings
            kh = str(Path.home() / ".ssh" / "known_hosts")
            self._conn = await _assh.connect(
                s["host"],
                port=s["port"],
                username=s["user"],
                client_keys=[s["key_path"]],
                known_hosts=kh if Path(kh).exists() else None,
            )
            self._connected = True
            logger.info(f"[SSH] connecté → {s['host']}")
            if self._pub_fn:
                self._pub_fn(TOPIC_SSH, {"event": "connected", "host": s["host"]})
        except Exception as e:
            self._connected = False
            logger.warning(f"[SSH] connexion échouée : {e}")
            if self._pub_fn:
                self._pub_fn(TOPIC_SSH, {"event": "error", "msg": str(e)})

    async def _keepalive(self) -> None:
        """keepalive."""
        import asyncio as _aio

        while self._running:
            await _aio.sleep(30)
            if self._conn and not self._conn.is_closed():
                try:
                    await self._conn.run("true", timeout=5)
                except Exception:
                    logger.info("[SSH] keepalive perdu — reconnexion…")
                    await self._connect()
            elif self._running:
                await self._connect()

    async def _exec(self, cmd: str, req_id: str, sudo: bool = False) -> None:
        """Exécute cmd et publie les chunks sur PUB topic b'ssh:<req_id>'."""
        topic = TOPIC_SSH + b":" + req_id.encode()
        if not self._connected or self._conn is None or self._conn.is_closed():
            await self._connect()
        if not self._connected:
            if self._pub_fn:
                self._pub_fn(topic, {"type": "error", "msg": "SSH non connecté", "done": True})
            return
        full_cmd = f"sudo {cmd}" if sudo else cmd
        try:
            result = await self._conn.run(full_cmd, timeout=60)
            # Publier stdout en chunks
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            if stdout and self._pub_fn:
                # Chunking : 512 chars par message pour ne pas saturer le socket
                for i in range(0, max(1, len(stdout)), 512):
                    self._pub_fn(topic, {"type": "stdout", "data": stdout[i : i + 512], "done": False})
            if stderr and self._pub_fn:
                self._pub_fn(topic, {"type": "stderr", "data": stderr, "done": False})
            if self._pub_fn:
                self._pub_fn(topic, {"type": "done", "exit": result.exit_status, "done": True})
        except Exception as e:
            logger.error(f"[SSH] exec échoué : {e}")
            if self._pub_fn:
                self._pub_fn(topic, {"type": "error", "msg": str(e), "done": True})

    @property
    def connected(self) -> bool:
        """Connected."""
        return self._connected


# =============================================================================
# SERVICE ZeroMQ (thread principal)
# =============================================================================


class BrainService:
    """
    Boucle ZMQ REP — répond TOUJOURS immédiatement, jamais bloquant.
    Le travail ML est délégué au TaskWorker (thread séparé).
    """

    def __init__(
        self, port: int = DEFAULT_PORT, load_generator: bool = False
    ):  # activer via --no-generator=False ou LAFORGE_PHI35=true
        """Initialise."""
        self._port = port
        self._load_generator = load_generator
        self._emb = Embedder()
        self._gen = Generator()
        self._worker: Optional[TaskWorker] = None
        self._running = False
        self._ssh = SshManager()
        self._pub_socket = None  # zmq.PUB sur PUB_PORT
        # Short-Term Memory : historique des 3 derniers essais par session
        self._stm: dict = {}  # {session_id: [{"code":..., "error":..., "ts":...}]}
        self._STM_MAX = 3  # max essais gardés par session

    def start(self) -> None:
        """Start."""
        try:
            import zmq
        except ImportError:
            logger.error("pyzmq non installé — pip install pyzmq")
            sys.exit(1)

        # Charger les modèles (bloquant, avant d'ouvrir le socket)
        self._emb.load()
        if self._load_generator:
            self._gen.load()

        self._worker = TaskWorker(self._emb, self._gen)
        self._worker.start()

        # ── Engrid bridge — route les appels LLM via SpikeRouter ─────────────
        try:
            from nokido_agent.app.forge_engrid_bridge import patch_task_worker as _ptw

            _patched = _ptw(self._worker)
            if _patched:
                logger.info("[BrainService] Engrid bridge actif — LLM routé via SpikeRouter")
        except Exception as _eb:
            logger.debug(f"[BrainService] Engrid bridge non disponible: {_eb}")

        ctx = zmq.Context()
        socket = ctx.socket(zmq.REP)
        socket.setsockopt(zmq.LINGER, 0)
        socket.bind(f"tcp://127.0.0.1:{self._port}")

        # ── PUB socket — chunks SSH + stream LLM ────────────────────────────────
        pub = ctx.socket(zmq.PUB)
        pub.setsockopt(zmq.LINGER, 0)
        pub.setsockopt(zmq.SNDHWM, 1000)  # high-water mark
        pub.bind(f"tcp://127.0.0.1:{PUB_PORT}")
        self._pub_socket = pub

        # Fonction publish thread-safe (appelée depuis SshManager thread)
        _pub_lock = threading.Lock()

        def _pub_fn(topic: bytes, payload: dict) -> None:
            """pub fn."""
            try:
                data = json.dumps(payload, ensure_ascii=False).encode()
                with _pub_lock:
                    pub.send_multipart([topic, data], zmq.NOBLOCK)
            except Exception as _pe:
                logger.debug(f"[PUB] {_pe}")

        self._running = True
        logger.info(
            f"BrainService prêt :{self._port} PUB:{PUB_PORT} "
            f"| emb={'OK' if self._emb.ready else 'non dispo'} "
            f"| gen={'OK' if self._gen.ready else 'non dispo'}"
        )

        # ── SSH keep-alive : acces lus au COFFRE d'abord (forge_secrets : coffre, WCM,
        # Nokido.env, environnement). Owner 2026-09-25 : plus d'acces en dur ; un os.environ
        # brut n'avait aucun repli une fois la ligne de Nokido.env migree au coffre.
        def _acces_ssh(cle, defaut=""):
            try:
                from nokido_agent.app.forge_secrets import get_secret as _gs

                return _gs(cle) or defaut
            except Exception as _e:  # noqa: BLE001 - coffre illisible : DIT, puis repli
                logger.warning(f"[SSH] coffre illisible pour {cle} ({type(_e).__name__}) — repli environnement")
                return os.environ.get(cle) or defaut

        _ssh_host = _acces_ssh("SSH_HOST")
        _ssh_port = int(_acces_ssh("SSH_PORT", "22") or 22)
        _ssh_user = _acces_ssh("SSH_USER")
        _ssh_key = _acces_ssh("PRIVATE_KEY_PATH")
        if not _ssh_host:
            # Tenter de lire Nokido.env
            _env = Path(__file__).parent / "Nokido.env"
            if _env.exists():
                for _ln in _env.read_text(encoding="utf-8").splitlines():
                    _ln = _ln.strip()
                    if _ln.startswith("SSH_HOST="):
                        _ssh_host = _ln.split("=", 1)[1]
                    elif _ln.startswith("SSH_PORT="):
                        _ssh_port = int(_ln.split("=", 1)[1] or 22)
                    elif _ln.startswith("SSH_USER="):
                        _ssh_user = _ln.split("=", 1)[1]
                    elif _ln.startswith("PRIVATE_KEY_PATH="):
                        _ssh_key = _ln.split("=", 1)[1]
        if _ssh_host and _ssh_user and _ssh_key:
            self._ssh.configure(_ssh_host, _ssh_port, _ssh_user, _ssh_key, _pub_fn)
            self._ssh.start()
            logger.info(f"[SSH] keep-alive vers {_ssh_host}:{_ssh_port}")
        else:
            logger.info("[SSH] non configuré — ssh_run désactivé")

        # ── PromotionOrchestrator — file d'attente adaptative RAG ──────────────
        # Non-bloquant : thread daemon avec son propre event loop asyncio.
        # Reprend les pending de la session précédente (restore_from_db).
        try:
            from nokido_agent.app.forge_promotion_queue import attach_to_brain_service as _attach_promo

            _attach_promo(self)
            logger.info("[promo] PromotionOrchestrator attaché au BrainService")
        except Exception as _pe:
            logger.debug(f"[promo] non disponible : {_pe}")

        def _stop(sig: object, frame: object) -> None:
            """stop."""
            logger.info("Signal reçu — arrêt")
            self._running = False

        signal.signal(signal.SIGTERM, _stop)
        if sys.platform != "win32":
            signal.signal(signal.SIGINT, _stop)

        # Détection msgpack
        _use_msgpack = False
        try:
            import msgpack

            _use_msgpack = True
            logger.info("[zmq] MessagePack activé (binaire, 3x plus compact)")
        except ImportError:
            logger.info("[zmq] JSON (msgpack non installé — pip install msgpack)")

        while self._running:
            try:
                if not socket.poll(500):
                    continue
                raw = socket.recv(zmq.NOBLOCK)
                # Ping IdleWatchdog — reset le timer à chaque requête
                try:
                    _watchdog.ping()
                except Exception:
                    pass
            except Exception:
                continue
            try:
                # Décodage adaptatif : msgpack ou JSON
                if _use_msgpack:
                    try:
                        req = msgpack.unpackb(raw, raw=False)
                    except Exception:
                        req = json.loads(raw.decode("utf-8"))
                else:
                    req = json.loads(raw.decode("utf-8"))
                rep = self._dispatch(req)
            except Exception as e:
                rep = {"ok": False, "error": f"dispatch : {e}"}

            # Patch datetime serializer 2026-05-02
            def _json_default(o):
                if isinstance(o, (datetime,)):
                    return o.isoformat()
                if isinstance(o, timedelta):
                    return o.total_seconds()
                if hasattr(o, "tolist"):
                    return o.tolist()
                return str(o)

            try:
                if _use_msgpack:
                    socket.send(msgpack.packb(rep, use_bin_type=True, default=_json_default))
                else:
                    socket.send(json.dumps(rep, ensure_ascii=False, default=_json_default).encode("utf-8"))
            except Exception as e:
                logger.error(f"send : {e}")
                # Fallback safe : retire les valeurs non-sérialisables et retente
                try:
                    safe_rep = json.loads(json.dumps(rep, default=_json_default))
                    if _use_msgpack:
                        socket.send(msgpack.packb(safe_rep, use_bin_type=True))
                    else:
                        socket.send(json.dumps(safe_rep).encode("utf-8"))
                except Exception as e2:
                    logger.error(f"send fallback : {e2}")
                    socket.send(msgpack.packb({"ok": False, "error": f"serialize_fail: {e}"}, use_bin_type=True))

        # Arrêt propre
        self._worker.stop()
        self._ssh.stop()
        if self._gen.ready:
            self._gen.unload()
        socket.close()
        if self._pub_socket:
            self._pub_socket.close()
        ctx.term()
        logger.info("BrainService arrêté proprement")

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def _dispatch(self, req: dict) -> dict:
        """dispatch."""
        cmd = req.get("cmd", "")

        if cmd == "ping":
            return {"ok": True, "data": "pong"}

        # ── SSH via keep-alive ───────────────────────────────────────────────────────────────
        if cmd == "ssh_run":
            # Réponse IMMÉDIATE avec req_id, puis chunks publiés sur PUB
            # La TUI doit s'abonner à topic b'ssh:<req_id>' avant d'envoyer
            req_id = req.get("req_id") or f"ssh_{int(time.time() * 1000)}"
            command = req.get("cmd", "")
            sudo = bool(req.get("sudo", False))
            if not command:
                return {"ok": False, "error": "cmd vide"}
            if not self._ssh.connected:
                return {"ok": False, "error": "SSH non connecté", "hint": "ssh_status pour diagnostiquer"}
            self._ssh.enqueue(command, req_id, sudo)
            return {"ok": True, "req_id": req_id, "topic": f"ssh:{req_id}", "pub_port": PUB_PORT}

        if cmd == "ssh_status":
            return {
                "ok": True,
                "data": {
                    "connected": self._ssh.connected,
                    "pub_port": PUB_PORT,
                },
            }

        if cmd == "npu_status":
            if _npu_mgr is not None:
                return {"ok": True, "data": _npu_mgr.status_report()}
            return {"ok": True, "data": {"best_ep": "cpu", "npu": False, "directml": False, "cpu": True}}

        if cmd == "status":
            return {
                "ok": True,
                "data": {
                    "embedder": self._emb.ready,
                    "generator": self._gen.ready,
                    "tree_sitter": HAS_TREE_SITTER,
                    "ts_error": _TS_ERROR,
                    "dim": self._emb.dim,
                    "ep_backend": getattr(self._emb, "backend", "cpu"),
                    "backend": self._gen.backend,
                    "queue_size": self._worker.queue_size,
                    "pending": self._worker.pending_count,
                },
            }

        if cmd == "submit":
            t = req.get("type", "")
            prio = int(req.get("priority", 10))

            if t == "embed":
                if not self._emb.ready:
                    return {"ok": False, "error": "embedder non disponible"}
                tid = self._worker.submit("embed", {"texts": req.get("texts", [])}, prio)

            elif t in ("generate", "stream"):
                if not self._gen.ready:
                    return {"ok": False, "error": "generator non disponible"}
                tid = self._worker.submit(
                    t,
                    {
                        "messages": req.get("messages", []),
                        "max_tokens": req.get("max_tokens", 512),
                    },
                    prio,
                )

            elif t == "audit":
                # Audit rapide — via la queue pour cohérence
                tid = self._worker.submit("audit", {"code": req.get("code", "")}, prio)

            elif t == "analyze":
                tid = self._worker.submit("analyze", {"code": req.get("code", "")}, prio)

            elif t == "surgery":
                tid = self._worker.submit(
                    "surgery",
                    {
                        "source": req.get("source", ""),
                        "target_name": req.get("target_name", ""),
                        "new_code": req.get("new_code", ""),
                    },
                    prio,
                )

            elif t == "locate":
                tid = self._worker.submit(
                    "locate",
                    {
                        "source": req.get("source", ""),
                        "target_name": req.get("target_name", ""),
                    },
                    prio,
                )

            else:
                return {"ok": False, "error": f"type inconnu : {t!r}"}

            return {"ok": True, "task_id": tid, "priority": prio}

        # ── Commandes directes (synchrones, pas de queue) ────────────────────
        # Utile pour les audits rapides qui n'ont pas besoin de passer par la
        # PriorityQueue (pas de ML impliqué, < 1ms).

        if cmd == "audit_sync":
            code = req.get("code", "")
            return {"ok": True, "data": security_audit(code)}

        if cmd == "surgery_sync":
            result = apply_surgery(
                req.get("source", ""),
                req.get("target_name", ""),
                req.get("new_code", ""),
            )
            return {"ok": True, "data": result}

        if cmd == "locate_sync":
            source_bytes = bytes(req.get("source", ""), "utf8")
            target_name = req.get("target_name", "")
            loc = locate_function(source_bytes, target_name)
            if loc is None:
                return {"ok": True, "data": {"found": False, "target": target_name}}
            return {"ok": True, "data": {"found": True, **loc, "target": target_name}}

        if cmd == "check":
            result = self._worker.check(req.get("task_id", ""))
            return {"ok": True, **result}

        if cmd == "shutdown":
            self._running = False
            return {"ok": True, "data": "bye"}

        # ── Analyse enrichie (métadonnées ML pour le RAG) ────────────────
        if cmd == "analyze_sync":
            code = req.get("code", "")
            return {"ok": True, "data": analyze_code(code)}

        # ── Short-Term Memory ────────────────────────────────────────────
        if cmd == "stm_push":
            sid = req.get("session", "default")
            entry = {
                "code": req.get("code", "")[:4000],
                "error": req.get("error", ""),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            if sid not in self._stm:
                self._stm[sid] = []
            self._stm[sid].append(entry)
            if len(self._stm[sid]) > self._STM_MAX:
                self._stm[sid] = self._stm[sid][-self._STM_MAX :]
            return {"ok": True, "count": len(self._stm[sid])}

        if cmd == "stm_get":
            sid = req.get("session", "default")
            history = self._stm.get(sid, [])
            return {"ok": True, "data": history}

        if cmd == "stm_clear":
            sid = req.get("session", "default")
            self._stm.pop(sid, None)
            return {"ok": True}

        # ── Score de confiance ───────────────────────────────────────────
        if cmd == "score_sync":
            code = req.get("code", "")
            analysis = analyze_code(code)
            audit = security_audit(code)
            # Score composite : sécurité * (1 - complexité normalisée) * couverture docs
            cc_norm = min(analysis["cyclomatic_complexity"] / 30.0, 1.0)
            doc_bonus = 0.1 if analysis["has_docstrings"] else 0.0
            type_bonus = 0.05 if analysis["has_type_hints"] else 0.0
            confidence = round(
                analysis["security_score"] * (1.0 - cc_norm * 0.3)
                + doc_bonus
                + type_bonus
                - (0.3 if not audit["safe"] else 0.0),
                2,
            )
            confidence = max(0.0, min(1.0, confidence))
            return {
                "ok": True,
                "data": {
                    "confidence": confidence,
                    "analysis": analysis,
                    "audit": audit,
                },
            }

        return {"ok": False, "error": f"commande inconnue : {cmd!r}"}


# =============================================================================
if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()

    # ── IdleWatchdog — arrêt automatique si inactif ───────────────────────
    try:
        # Charger LAFORGE_IDLE_TIMEOUT depuis Nokido.env si absent de l'env
        import os as _os

        if "LAFORGE_IDLE_TIMEOUT" not in _os.environ:
            _ef = Path(__file__).parent.parent / "Nokido.env"
            if _ef.exists():
                for _el in _ef.read_text(encoding="utf-8").splitlines():
                    if _el.startswith("LAFORGE_IDLE_TIMEOUT="):
                        _os.environ["LAFORGE_IDLE_TIMEOUT"] = _el.split("=", 1)[1].strip()
                    elif _el.startswith("LAFORGE_IDLE_ENABLED="):
                        _os.environ["LAFORGE_IDLE_ENABLED"] = _el.split("=", 1)[1].strip()
        import sys as _sw

        _sw.path.insert(0, str(Path(__file__).parent))
        from nokido_agent.app.forge_idle_watchdog import IdleWatchdog as _IW

        _watchdog = _IW("BrainWorker")
        _watchdog.start()
    except Exception as _we:
        pass  # silencieux si non disponible

    parser = argparse.ArgumentParser(description="La Forge — Brain Worker ML v2")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-generator", action="store_true")
    parser.add_argument(
        "--parent-pid",
        type=int,
        default=None,
        help="PID du process parent (Nokido TUI) — quitte automatiquement si le parent meurt",
    )
    parser.add_argument(
        "--close-delay",
        type=int,
        default=5,
        help="Délai en secondes avant fermeture de la console après arrêt (défaut: 5)",
    )
    args = parser.parse_args()

    # ── Surveillance du parent : quitte si Nokido est fermé ─────────────
    if args.parent_pid:
        import threading as _threading

        def _watch_parent(ppid: int) -> None:
            """Thread daemon : poll le PID parent toutes les 2s, suicide si mort."""
            try:
                import psutil as _ps

                while True:
                    import time as _t

                    _t.sleep(2)
                    if not _ps.pid_exists(ppid):
                        logger.info(f"Parent PID {ppid} disparu — arrêt Brain")
                        import os as _os

                        _os.kill(_os.getpid(), signal.SIGTERM)
                        break
            except ImportError:
                # psutil absent : fallback os.kill(ppid, 0)
                import os as _os, time as _t

                while True:
                    _t.sleep(2)
                    try:
                        _os.kill(ppid, 0)  # signal 0 = test existence
                    except (ProcessLookupError, PermissionError):
                        logger.info(f"Parent PID {ppid} disparu — arrêt Brain")
                        _os.kill(_os.getpid(), signal.SIGTERM)
                        break

        _w = _threading.Thread(target=_watch_parent, args=(args.parent_pid,), daemon=True)
        _w.start()
        logger.info(f"Surveillance parent PID {args.parent_pid} activée")

    # ── Délai de fermeture console Windows ───────────────────────────────
    _close_delay = max(0, args.close_delay)
    if _close_delay > 0 and sys.platform == "win32":
        import atexit as _atexit

        def _on_exit() -> None:
            """on exit."""
            logger.info(f"Brain terminé — fermeture console dans {_close_delay}s")
            import time as _t

            _t.sleep(_close_delay)

        _atexit.register(_on_exit)

    # Par défaut --no-generator : Phi-3.5 trop lourd (3GB), Ollama gère la génération
    BrainService(port=args.port, load_generator=False).start()
