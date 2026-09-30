"""Relie Nokido au sidecar brain_worker (ZeroMQ, tcp://127.0.0.1:5557) pour embeddings,
generation, tree-sitter et memoire courte, et adapte le VersionManager externe.

Entrees : BrainClient, init_onnx_backend, shutdown_onnx_backend, get_brain,
get_embedder et get_generator (qui rendent le BrainClient), onnx_get_embeddings,
onnx_call, onnx_stream, onnx_status, ts_audit, ts_surgery, ts_locate, ml_analyze,
ml_score, stm_push, stm_get, stm_clear, VersionManagerAdapter, version_manager.
Importe par Nokido.py ; forge_cognitive_router le lit dans sys.modules.
Effets : fixe TOKENIZERS_PARALLELISM et OMP/MKL_NUM_THREADS a l'import ; instancie
version_manager a l'import (cible app/Nokido.py) ; init_onnx_backend retente 20 s
puis, si auto_launch, lance app/brain_worker.py en sous-processus.
"""
from __future__ import annotations

# Import oublie, mesure le 2026-09-08 : Optional[Any] L222.
from typing import Any

"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_164743_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns/Raises
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"

"""
forge_runtime.py — Inférence locale et versionnement pour La Forge
====================================================================
Fusion de : onnx_backend.py · version_manager.py (adaptateur)

Organisation :
  § 1 ONNX     : OnnxEmbedder (MiniLM-L6), OnnxGenerator (Phi-3.5 ONNX)
                 Inférence locale < 2ms pour embeddings, DirectML/NPU pour génération
  § 2 VERSION  : VersionManagerAdapter — pont vers le VersionManager externe
                 Gère les patches SemVer, l'historique, les rollbacks

Usage dans Nokido.py :
    from forge_runtime import (
        init_onnx_backend, get_embedder, get_generator,
        onnx_get_embeddings, onnx_call, onnx_stream, onnx_status,
        shutdown_onnx_backend,
        VersionManagerAdapter,
    )
    version_manager = VersionManagerAdapter()
"""


import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# § 1 — BACKEND ONNX  (ex-onnx_backend.py)
# =============================================================================

from typing import Callable


# =============================================================================
# DÉTECTION DES DÉPENDANCES
# =============================================================================

# =============================================================================
# ARCHITECTURE SIDECAR — brain_worker.py (ZeroMQ)
# =============================================================================
# sentence-transformers et onnxruntime-genai tournent dans brain_worker.py,
# un processus voisin lancé par le .bat AVANT Nokido.py.
# Communication : ZeroMQ REQ/REP JSON sur tcp://127.0.0.1:5557
#
# Si brain_worker absent → fallback transparent sur Ollama (bge-m3, etc.)
# Aucune modification requise dans le reste du code.
# =============================================================================

import sys as _sys_rt

HAS_SENTENCE_TRANSFORMERS: bool = False  # mis à jour dans init_onnx_backend()
HAS_ONNXRUNTIME_GENAI: bool = False
HAS_TREE_SITTER: bool = False  # tree-sitter dans le sidecar
_ST_IMPORT_ERROR: str = ""
_ONNX_IMPORT_ERROR: str = ""
_TS_ERROR: str = ""

BRAIN_PORT: int = 5557  # doit correspondre à --port de brain_worker.py

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")


class BrainClient:
    """
    Client ZeroMQ vers brain_worker.py (v2 — PriorityQueue).
    submit()       → task_id immédiat
    await_result() → attend le résultat par polling async (non-bloquant pour la TUI)
    Shortcuts :    embed(), generate(), stream()
    """

    # Priorités standard
    PRIO_USER = 0  # action utilisateur — passe devant tout
    PRIO_WARMUP = 5  # warmup RAG au démarrage
    PRIO_BACKGROUND = 10  # tâches autonomes background

    # Intervalle de polling entre deux check() (secondes)
    POLL_INTERVAL = 0.3

    def __init__(self, port: int = BRAIN_PORT, timeout_ms: int = 30_000) -> None:
        """Initialise."""
        self._port = port
        self._timeout = timeout_ms
        self._ctx = None
        self._socket = None
        self._connected = False
        self._status: dict = {}
        self._lock = None  # asyncio.Lock, créé au 1er appel async
        self._zmq_module = None  # référence vers le module zmq

    # ── Connexion ─────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Connexion + ping de validation (synchrone, appelé depuis init_onnx_backend)."""
        try:
            import zmq

            self._zmq_module = zmq
            self._ctx = zmq.Context()
            self._socket = self._ctx.socket(zmq.REQ)
            self._socket.setsockopt(zmq.RCVTIMEO, 1_200)
            self._socket.setsockopt(zmq.SNDTIMEO, 1_200)
            self._socket.setsockopt(zmq.LINGER, 0)
            self._socket.connect(f"tcp://127.0.0.1:{self._port}")
            rep = self._call_sync({"cmd": "ping"})
            if rep.get("data") == "pong":
                st = self._call_sync({"cmd": "status"})
                self._status = st.get("data", {})
                self._connected = True
                globals()["HAS_SENTENCE_TRANSFORMERS"] = self._status.get("embedder", False)
                globals()["HAS_ONNXRUNTIME_GENAI"] = self._status.get("generator", False)
                globals()["HAS_TREE_SITTER"] = self._status.get("tree_sitter", False)
                globals()["_TS_ERROR"] = self._status.get("ts_error", "")
                # Erreurs spécifiques par composant
                if self._status.get("embedder"):
                    globals()["_ST_IMPORT_ERROR"] = ""
                else:
                    globals()["_ST_IMPORT_ERROR"] = "sidecar connecté mais embedder non chargé"
                if self._status.get("generator"):
                    globals()["_ONNX_IMPORT_ERROR"] = ""
                else:
                    globals()["_ONNX_IMPORT_ERROR"] = "sidecar connecté mais generator non chargé"
                logger.info(
                    f"BrainClient connecté :{self._port} "
                    f"| emb={self._status.get('embedder')} "
                    f"| gen={self._status.get('generator')} "
                    f"| ts={self._status.get('tree_sitter')}"
                )
                return True
            else:
                _msg = "brain_worker ne répond pas au ping"
                globals()["_ST_IMPORT_ERROR"] = _msg
                globals()["_ONNX_IMPORT_ERROR"] = _msg
        except ImportError:
            _msg = "pyzmq non installé (pip install pyzmq)"
            globals()["_ST_IMPORT_ERROR"] = _msg
            globals()["_ONNX_IMPORT_ERROR"] = _msg
            logger.warning("pyzmq non installé — sidecar désactivé")
        except Exception as e:
            _msg = f"brain_worker absent :{self._port} ({e})"
            globals()["_ST_IMPORT_ERROR"] = _msg
            globals()["_ONNX_IMPORT_ERROR"] = _msg
            logger.debug(f"{_msg} — fallback Ollama")
        return False

    def disconnect(self) -> None:
        """Disconnect."""
        try:
            if self._socket:
                self._socket.close()
            if self._ctx:
                self._ctx.term()
        except Exception:
            pass
        self._connected = False

    # ── Appels bas niveau ─────────────────────────────────────────────────────

    def _call_sync(self, payload: dict) -> dict:
        """call sync."""
        # MessagePack (binaire, 3x plus compact) → fallback JSON
        try:
            import msgpack

            raw = msgpack.packb(payload, use_bin_type=True)
            self._socket.send(raw)
            return msgpack.unpackb(self._socket.recv(), raw=False)
        except ImportError:
            raw = json.dumps(payload, ensure_ascii=False).encode()
            self._socket.send(raw)
            return json.loads(self._socket.recv().decode())

    async def _call(self, payload: dict) -> dict:
        """Appel ZMQ dans executor — non-bloquant pour asyncio/Textual."""
        if not self._connected:
            return {"ok": False, "error": "non connecté"}
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            loop = asyncio.get_event_loop()
            try:
                return await loop.run_in_executor(None, self._call_sync, payload)
            except Exception as e:
                logger.error(f"BrainClient._call {payload.get('cmd')}: {e}")
                return {"ok": False, "error": str(e)}

    # ── submit + check + await_result ─────────────────────────────────────────

    async def submit(self, task_type: str, payload: dict, priority: int = PRIO_BACKGROUND) -> Optional[str]:
        """Soumet une tâche — retourne le task_id immédiatement."""
        rep = await self._call({"cmd": "submit", "type": task_type, "priority": priority, **payload})
        if rep.get("ok"):
            return rep["task_id"]
        logger.debug(f"submit {task_type} : {rep.get('error')}")
        return None

    async def check(self, task_id: str) -> dict:
        """Vérifie l'état d'une tâche : pending / completed / error."""
        rep = await self._call({"cmd": "check", "task_id": task_id})
        return rep if rep.get("ok") else {"status": "error", "error": rep.get("error")}

    async def await_result(self, task_id: str, timeout: float = 120.0) -> Optional[Any]:
        """
        Attend le résultat d'une tâche par polling non-bloquant.
        Retourne la donnée ou None si timeout / erreur.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            rep = await self.check(task_id)
            status = rep.get("status")
            if status == "completed":
                return rep.get("data")
            if status == "error":
                logger.debug(f"await_result {task_id} error : {rep.get('error')}")
                return None
            await asyncio.sleep(self.POLL_INTERVAL)
        logger.warning(f"await_result {task_id} timeout {timeout}s")
        return None

    # ── Shortcuts (interface identique à l'ancienne version) ─────────────────

    async def embed(self, texts: List[str], priority: int = PRIO_WARMUP) -> Optional[List[List[float]]]:
        """Embedding via MiniLM — async, priorité warmup par défaut."""
        if not self._connected or not self._status.get("embedder"):
            return None
        tid = await self.submit("embed", {"texts": texts}, priority)
        if not tid:
            return None
        return await self.await_result(tid, timeout=60.0)

    async def generate(self, messages: List[Dict], max_tokens: int = 512, priority: int = PRIO_USER) -> str:
        """Génération Phi-3.5 — async, priorité user par défaut."""
        if not self._connected or not self._status.get("generator"):
            raise RuntimeError("BrainClient generator non disponible")
        tid = await self.submit("generate", {"messages": messages, "max_tokens": max_tokens}, priority)
        if not tid:
            raise RuntimeError("submit generate échoué")
        result = await self.await_result(tid, timeout=120.0)
        if result is None:
            raise RuntimeError("generate timeout ou erreur")
        return result

    async def stream(
        self,
        messages: List[Dict],
        on_token: "Callable",
        on_done: "Callable",
        max_tokens: int = 1024,
        priority: int = PRIO_USER,
    ) -> str:
        """
        Génération + découpe en mots pour simuler le streaming.
        (REQ/REP ne supporte pas le vrai token streaming.)
        """
        text = await self.generate(messages, max_tokens, priority)
        for word in text.split(" "):
            on_token(word + " ")
            await asyncio.sleep(0)
        on_done()
        return text

    # ── Propriétés ────────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        """Connected."""
        return self._connected

    @property
    def embedder_ready(self) -> bool:
        """Embedder ready."""
        return self._connected and bool(self._status.get("embedder"))

    @property
    def generator_ready(self) -> bool:
        """Generator ready."""
        return self._connected and bool(self._status.get("generator"))

    @property
    def tree_sitter_ready(self) -> bool:
        """Tree sitter ready."""
        return self._connected and bool(self._status.get("tree_sitter"))

    @property
    def dim(self) -> int:
        """Dim."""
        return self._status.get("dim", 0)

    @property
    def backend(self) -> str:
        """Backend."""
        return self._status.get("backend", "none")

    # ── Tree-sitter : audit + chirurgie (appels synchrones via ZMQ) ────────

    def audit_sync(self, code: str) -> dict:
        """
        Audit sécurité tree-sitter synchrone.
        Retourne {"safe": bool, "message": str, "violations": [...]}.
        """
        if not self._connected:
            return {"safe": True, "message": "sidecar absent — audit ignoré", "violations": []}
        try:
            rep = self._call_sync({"cmd": "audit_sync", "code": code})
            return rep.get("data", {"safe": False, "message": "réponse invalide", "violations": []})
        except Exception as e:
            logger.warning(f"audit_sync échoué : {e}")
            return {"safe": True, "message": f"audit timeout ({e})", "violations": []}

    def surgery_sync(self, source: str, target_name: str, new_code: str) -> dict:
        """
        Chirurgie tree-sitter synchrone (byte-slicing).
        Retourne {"success", "message", "result", "backup"}.
        """
        if not self._connected:
            return {"success": False, "message": "sidecar absent", "result": "", "backup": ""}
        try:
            # Timeout plus long pour les gros fichiers
            self._socket.setsockopt(self._zmq_module.RCVTIMEO, 10_000)
            rep = self._call_sync(
                {
                    "cmd": "surgery_sync",
                    "source": source,
                    "target_name": target_name,
                    "new_code": new_code,
                }
            )
            return rep.get("data", {"success": False, "message": "réponse invalide"})
        except Exception as e:
            logger.warning(f"surgery_sync échoué : {e}")
            return {"success": False, "message": f"surgery timeout ({e})", "result": "", "backup": ""}
        finally:
            try:
                self._socket.setsockopt(self._zmq_module.RCVTIMEO, self._timeout)
            except Exception:
                pass

    def locate_sync(self, source: str, target_name: str) -> Optional[dict]:
        """
        Localise une fonction dans le source via tree-sitter.
        Retourne {"found", "start_byte", "end_byte", "start_line", "indent"} ou None.
        """
        if not self._connected:
            return None
        try:
            rep = self._call_sync(
                {
                    "cmd": "locate_sync",
                    "source": source,
                    "target_name": target_name,
                }
            )
            data = rep.get("data", {})
            return data if data.get("found") else None
        except Exception as e:
            logger.warning(f"locate_sync échoué : {e}")
            return None

    # ── Analyse enrichie ML (complexité, libs, sécu) ─────────────────────

    def analyze_sync(self, code: str) -> dict:
        """Analyse enrichie : complexité cyclomatique, libs, score sécu, structure."""
        if not self._connected:
            return {}
        try:
            rep = self._call_sync({"cmd": "analyze_sync", "code": code[:4000]})
            return rep.get("data", {})
        except Exception as e:
            logger.debug(f"analyze_sync: {e}")
            return {}

    def score_sync(self, code: str) -> dict:
        """Score de confiance composite (sécu × complexité + bonus docs/types)."""
        if not self._connected:
            return {"confidence": 0.5}
        try:
            rep = self._call_sync({"cmd": "score_sync", "code": code[:4000]})
            return rep.get("data", {"confidence": 0.5})
        except Exception as e:
            logger.debug(f"score_sync: {e}")
            return {"confidence": 0.5}

    # ── Short-Term Memory ────────────────────────────────────────────────

    def stm_push(self, session: str, code: str, error: str) -> int:
        """Pousse un essai échoué dans la STM du sidecar. Retourne le nb d'entrées."""
        if not self._connected:
            return 0
        try:
            rep = self._call_sync({"cmd": "stm_push", "session": session, "code": code[:2000], "error": error})
            return rep.get("count", 0)
        except Exception:
            return 0

    def stm_get(self, session: str) -> list:
        """Récupère l'historique STM (max 3 derniers essais)."""
        if not self._connected:
            return []
        try:
            rep = self._call_sync({"cmd": "stm_get", "session": session})
            return rep.get("data", [])
        except Exception:
            return []

    def stm_clear(self, session: str) -> None:
        """Vide la STM d'une session."""
        if not self._connected:
            return
        try:
            self._call_sync({"cmd": "stm_clear", "session": session})
        except Exception:
            pass


# Singleton partagé
_brain: Optional[BrainClient] = None

# =============================================================================
# CONFIGURATION — CHEMINS MODÈLES
# =============================================================================

# Chemin du dossier models/ relatif au script Nokido.py
_BASE = Path(__file__).parent

# all-MiniLM-L6-v2 : téléchargé dans le cache HuggingFace automatiquement
MINILM_MODEL_ID = "all-MiniLM-L6-v2"

# Phi-3.5 Mini : dossier local téléchargé via huggingface-cli
# Cherche d'abord DirectML (NPU/iGPU), puis CPU
PHI35_DIRECTML_PATH = _BASE / "models" / "phi3.5" / "directml" / "directml-int4-awq-block-128"
PHI35_CPU_PATH = _BASE / "models" / "phi3.5" / "cpu_and_mobile" / "cpu-int4-rtn-block-32-acc-level-4"


# Context:


def _find_phi35_path() -> Path | None:
    """Retourne le chemin Phi-3.5 disponible (DirectML prioritaire).

    Recherche dans l'ordre :
    1. Le chemin DirectML prdfinie (PHI35_DIRECTML_PATH).
    2. Le chemin CPU prdfinie (PHI35_CPU_PATH).
    3. Tout fichier *.onnx sous le rpertoire de base des modles phi3.5.

    Retourne le dossier contenant le modle trouv, ou ``None`` si aucun
    modle n'est dtect.
    """
    if PHI35_DIRECTML_PATH.exists():
        logger.info(f"Phi-3.5 DirectML trouv : {PHI35_DIRECTML_PATH}")
        return PHI35_DIRECTML_PATH
    if PHI35_CPU_PATH.exists():
        logger.info(f"Phi-3.5 CPU trouv : {PHI35_CPU_PATH}")
        return PHI35_CPU_PATH
    # Cherche n'importe quel dossier phi3.5 prsent
    phi_base = _BASE / "models" / "phi3.5"
    if phi_base.exists():
        for p in phi_base.rglob("*.onnx"):
            logger.info(f"Phi-3.5 trouv (auto) : {p.parent}")
            return p.parent
    return None


# =============================================================================
# EMBEDDINGS — all-MiniLM-L6-v2
# =============================================================================


class OnnxEmbedder:
    """
    Embeddings synchrones via sentence-transformers (all-MiniLM-L6-v2).
    Dimension de sortie : 1024.
    Latence typique : 1-3ms pour un batch de 32 textes.
    """

    _instance: Optional["OnnxEmbedder"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialise."""
        self._model: Optional[SentenceTransformer] = None
        self._ready = False
        self._dim = 1024

    @classmethod
    def get(cls) -> "OnnxEmbedder":
        """Singleton thread-safe."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def load(self) -> bool:
        """Charge le modèle (bloquant, appeler une fois au démarrage)."""
        if self._ready:
            return True
        if not HAS_SENTENCE_TRANSFORMERS:
            _hint = f" : {_ST_IMPORT_ERROR}" if _ST_IMPORT_ERROR else ""
            logger.warning(f"sentence-transformers non chargé — embeddings désactivés{_hint}")
            return False
        try:
            from sentence_transformers import SentenceTransformer

            t0 = time.monotonic()
            self._model = SentenceTransformer(
                MINILM_MODEL_ID,
                device="cpu",  # évite spawn GPU sur Windows
            )
            self._dim = self._model.get_sentence_embedding_dimension()
            self._ready = True
            logger.info(f"OnnxEmbedder chargé : {MINILM_MODEL_ID} dim={self._dim} en {time.monotonic() - t0:.2f}s")
            return True
        except Exception as e:
            logger.error(f"Erreur chargement OnnxEmbedder : {e}")
            return False

    @property
    def ready(self) -> bool:
        """Ready."""
        return self._ready

    @property
    def dim(self) -> int:
        """Dim."""
        return self._dim

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Encode une liste de textes → liste d'embeddings (synchrone)."""
        if not self._ready or not texts:
            return []
        try:
            vecs = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
            return [v.tolist() for v in vecs]
        except Exception as e:
            logger.error(f"OnnxEmbedder.encode : {e}")
            return []

    async def encode_async(self, texts: List[str]) -> List[List[float]]:
        """Version async : délègue à run_in_executor pour ne pas bloquer la TUI."""
        if not self._ready:
            return []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.encode, texts)


# =============================================================================
# GÉNÉRATION — Phi-3.5 Mini Instruct ONNX
# =============================================================================

# Template de chat pour Phi-3.5 (format <|user|> ... <|end|> <|assistant|>)
_PHI35_SYSTEM_TOKEN = "<|system|>"
_PHI35_USER_TOKEN = "<|user|>"
_PHI35_ASST_TOKEN = "<|assistant|>"
_PHI35_END_TOKEN = "<|end|>"


def _build_phi35_prompt(messages: List[Dict]) -> str:
    """
    Convertit une liste de messages OpenAI-style en prompt Phi-3.5.
    messages = [{"role": "system"|"user"|"assistant", "content": str}, ...]
    """
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "").strip()
        if role == "system":
            parts.append(f"{_PHI35_SYSTEM_TOKEN}\n{content}{_PHI35_END_TOKEN}\n")
        elif role == "user":
            parts.append(f"{_PHI35_USER_TOKEN}\n{content}{_PHI35_END_TOKEN}\n")
        elif role == "assistant":
            parts.append(f"{_PHI35_ASST_TOKEN}\n{content}{_PHI35_END_TOKEN}\n")
    # Ouvrir le tour assistant
    parts.append(f"{_PHI35_ASST_TOKEN}\n")
    return "".join(parts)


class OnnxGenerator:
    """
    Générateur de texte via Phi-3.5 Mini Instruct ONNX.
    - DirectML prioritaire (iGPU Radeon 780M + NPU Ryzen AI)
    - Fallback CPU automatique
    - Interface compatible ollama_call / ollama_stream
    """

    _instance: Optional["OnnxGenerator"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialise."""
        self._model = None
        self._tokenizer = None
        self._ready = False
        self._path: Optional[Path] = None
        self._backend = "none"  # "directml" | "cpu" | "none"

    @classmethod
    def get(cls) -> "OnnxGenerator":
        """Get."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def load(self) -> bool:
        """Charge Phi-3.5 (bloquant, appeler en thread ou au démarrage)."""
        if self._ready:
            return True
        if not HAS_ONNXRUNTIME_GENAI:
            logger.warning("onnxruntime-genai non installé — génération ONNX désactivée")
            return False

        path = _find_phi35_path()
        if path is None:
            logger.warning(
                "Phi-3.5 ONNX non trouvé. "
                "Télécharge via : huggingface-cli download microsoft/Phi-3.5-mini-instruct-onnx "
                "--include 'directml/*' --local-dir ./models/phi3.5"
            )
            return False

        try:
            import onnxruntime_genai as og

            t0 = time.monotonic()
            self._model = og.Model(str(path))
            self._tokenizer = og.Tokenizer(self._model)
            self._ready = True
            self._path = path
            # Détecter le backend utilisé
            self._backend = "directml" if "directml" in str(path).lower() else "cpu"
            logger.info(
                f"OnnxGenerator chargé : Phi-3.5 [{self._backend}] depuis {path.name} en {time.monotonic() - t0:.1f}s"
            )
            return True
        except Exception as e:
            logger.error(f"Erreur chargement OnnxGenerator : {e}")
            return False

    @property
    def ready(self) -> bool:
        """Ready."""
        return self._ready

    @property
    def backend(self) -> str:
        """Backend."""
        return self._backend

    def _generate_sync(
        self,
        messages: List[Dict],
        max_tokens: int = 512,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Génération synchrone. on_token appelé à chaque token si fourni (streaming).
        """
        import onnxruntime_genai as og

        prompt = _build_phi35_prompt(messages)
        tokens = self._tokenizer.encode(prompt)

        params = og.GeneratorParams(self._model)
        params.max_length = len(tokens) + max_tokens
        params.input_ids = tokens

        generator = og.Generator(self._model, params)
        output = []

        while not generator.is_done():
            generator.compute_logits()
            generator.generate_next_token()
            new_tok = generator.get_next_tokens()
            if new_tok is not None and len(new_tok) > 0:
                text = self._tokenizer.decode(new_tok)
                # Filtrer les tokens spéciaux de fin
                if any(t in text for t in (_PHI35_END_TOKEN, "<|endoftext|>")):
                    break
                output.append(text)
                if on_token:
                    on_token(text)

        return "".join(output).strip()

    async def generate(
        self,
        messages: List[Dict],
        max_tokens: int = 512,
    ) -> str:
        """Version async non-streaming."""
        if not self._ready:
            raise RuntimeError("OnnxGenerator non chargé")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self._generate_sync(messages, max_tokens, None))

    async def stream(
        self,
        messages: List[Dict],
        on_token: Callable[[str], None],
        on_done: Callable[[], None],
        max_tokens: int = 1024,
    ) -> str:
        """
        Version async streaming — compatible interface ollama_stream.
        on_token(text) appelé à chaque token produit.
        on_done() appelé à la fin.
        """
        if not self._ready:
            raise RuntimeError("OnnxGenerator non chargé")

        # Génération dans un thread pour ne pas bloquer asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: self._generate_sync(messages, max_tokens, on_token))
        on_done()
        return result

    def unload(self) -> None:
        """
        Libère explicitement le modèle et le tokenizer.
        À appeler avant la fermeture de l app pour éviter les leaks OGA.
        """
        try:
            if self._model is not None:
                del self._model
                self._model = None
            if self._tokenizer is not None:
                del self._tokenizer
                self._tokenizer = None
            self._ready = False
            logger.debug("OnnxGenerator déchargé proprement")
        except Exception as e:
            logger.debug(f"OnnxGenerator.unload : {e}")

    def __del__(self) -> None:
        """del  ."""
        self.unload()


# =============================================================================
# INTERFACE PUBLIQUE — fonctions drop-in replacement
# =============================================================================

# Singletons (initialisés au démarrage via init_onnx_backend())
_embedder: Optional[OnnxEmbedder] = None
_generator: Optional[OnnxGenerator] = None


def init_onnx_backend(
    load_generator: bool = os.getenv("LAFORGE_PHI35", "false").lower()
    == "true",  # activer via LAFORGE_PHI35=true dans .env
    auto_launch: bool = False,
) -> Dict[str, bool]:
    """
    Initialise les backends ONNX + tree-sitter via le sidecar.
    À appeler une fois au démarrage (dans on_mount ou avant).

    Si auto_launch=True, lance brain_worker.py en subprocess si non déjà actif.
    MAIS attend d'abord quelques secondes au cas où le .bat l'a déjà lancé.

    Retourne {"embedder": bool, "generator": bool, "tree_sitter": bool}.
    """
    global _brain, _sidecar_process
    import time as _t

    _brain = BrainClient(port=BRAIN_PORT)
    emb_ok = False
    gen_ok = False
    ts_ok = False

    # ── Phase 1 : tenter la connexion avec retries ────────────────────────
    # Le .bat lance brain_worker AVANT Nokido, mais le chargement ML prend
    # quelques secondes. On retente 5 fois (5s) avant de conclure "absent".
    for attempt in range(20):
        if _brain.connect():
            emb_ok = _brain.embedder_ready
            gen_ok = _brain.generator_ready and load_generator
            ts_ok = _brain.tree_sitter_ready
            logger.info(f"Sidecar trouvé (tentative {attempt + 1}/20)")
            return {"embedder": emb_ok, "generator": gen_ok, "tree_sitter": ts_ok}
        if attempt < 19:
            _t.sleep(1)
    logger.debug("Sidecar absent après 20 tentatives — passage phase 2")

    # ── Phase 2 : auto-launch si personne n'écoute ───────────────────────
    if auto_launch:
        # Vérifier que le port n'est pas déjà pris (process zombie / crash)
        if _is_port_in_use(BRAIN_PORT):
            logger.warning(
                f"Port {BRAIN_PORT} déjà occupé mais ne répond pas au ping. "
                f"Un brain_worker fantôme est peut-être en cours."
            )
            return {"embedder": False, "generator": False, "tree_sitter": False}

        logger.info("Sidecar absent après 5s — lancement automatique de brain_worker.py…")
        _sidecar_process = _launch_sidecar(load_generator)
        if _sidecar_process is not None:
            # Attente ping (max 15s pour le chargement des modèles ML)
            for attempt in range(15):
                _t.sleep(1)
                if _brain.connect():
                    emb_ok = _brain.embedder_ready
                    gen_ok = _brain.generator_ready and load_generator
                    ts_ok = _brain.tree_sitter_ready
                    logger.info(f"Sidecar auto-lancé OK (tentative {attempt + 1}/15)")
                    return {"embedder": emb_ok, "generator": gen_ok, "tree_sitter": ts_ok}
            logger.warning("Sidecar lancé mais ne répond pas après 15s")

    return {"embedder": emb_ok, "generator": gen_ok, "tree_sitter": ts_ok}


def _is_port_in_use(port: int) -> bool:
    """Vérifie si un process écoute déjà sur le port (évite double-lancement)."""
    import socket as _sock

    with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ── Lancement automatique du sidecar ─────────────────────────────────────────

import subprocess as _subprocess_rt

_sidecar_process = None  # subprocess.Popen si lancé par nous


def _launch_sidecar(load_generator: bool = True) -> Optional[_subprocess_rt.Popen]:
    """
    Lance brain_worker.py dans un subprocess détaché.
    Retourne le Popen ou None si brain_worker.py introuvable.
    """
    brain_script = Path(__file__).parent / "brain_worker.py"
    if not brain_script.exists():
        logger.info(f"brain_worker.py non trouvé dans {brain_script.parent}")
        return None

    cmd = [_sys_rt.executable, str(brain_script), "--port", str(BRAIN_PORT)]
    if not load_generator:
        cmd.append("--no-generator")

    try:
        # Windows : CREATE_NO_WINDOW pour ne pas ouvrir de console
        # Linux/Mac : process normal
        creation_flags = 0
        if _sys_rt.platform == "win32":
            creation_flags = _subprocess_rt.CREATE_NO_WINDOW

        proc = _subprocess_rt.Popen(
            cmd,
            creationflags=creation_flags,
            cwd=str(brain_script.parent),
            stdout=_subprocess_rt.DEVNULL,
            stderr=_subprocess_rt.DEVNULL,
        )
        logger.info(f"brain_worker.py lancé (PID {proc.pid})")
        return proc
    except Exception as e:
        logger.warning(f"Impossible de lancer brain_worker.py : {e}")
        return None


def get_embedder() -> Optional[OnnxEmbedder]:
    """Get embedder."""
    return _brain if (_brain and _brain.embedder_ready) else None


def get_generator() -> Optional[OnnxGenerator]:
    """Get generator."""
    return _brain if (_brain and _brain.generator_ready) else None


def get_brain() -> Optional[BrainClient]:
    """Accès direct au BrainClient (pour audit/surgery)."""
    return _brain if (_brain and _brain.connected) else None


async def onnx_get_embeddings(texts: List[str]) -> Optional[List[List[float]]]:
    """
    Embeddings via MiniLM ONNX.
    Drop-in replacement pour les appels Ollama embeddings dans RAGEngine.
    Retourne None si ONNX non disponible (→ fallback Ollama).
    """
    emb = get_embedder()
    if emb is None:
        return None
    result = await emb.embed(texts)
    return result if result else None


async def onnx_call(
    messages: List[Dict],
    max_tokens: int = 512,
) -> str:
    """
    Génération via Phi-3.5 ONNX (non-streaming).
    Drop-in replacement pour ollama_call().
    Lève RuntimeError si ONNX non dispo → l'appelant fait fallback Ollama.
    """
    logger.debug(f"[onnx_call] {len(messages)} messages")
    brain = get_generator()
    if brain is None:
        raise RuntimeError("OnnxGenerator non disponible")
    return await brain.generate(messages, max_tokens)


async def onnx_stream(
    messages: List[Dict],
    on_token: Callable[[str], None],
    on_done: Callable[[], None],
    max_tokens: int = 1024,
) -> str:
    """
    Génération streaming via Phi-3.5 ONNX.
    Drop-in replacement pour ollama_stream().
    """
    logger.debug(f"[onnx_call] {len(messages)} messages")
    brain = get_generator()
    if brain is None:
        raise RuntimeError("OnnxGenerator non disponible")
    return await brain.stream(messages, on_token, on_done, max_tokens)


def shutdown_onnx_backend() -> None:
    """
    Libère proprement tous les backends ONNX + arrête le sidecar si lancé par nous.
    À appeler dans on_unmount de l'app Textual.

    Si le sidecar a été lancé par le .bat (externe), on se déconnecte sans le tuer.
    Si c'est nous qui l'avons lancé (auto_launch), on envoie shutdown + terminate.
    """
    global _brain, _sidecar_process
    launched_by_us = _sidecar_process is not None

    if _brain is not None:
        try:
            # Envoyer shutdown UNIQUEMENT si c'est nous qui l'avons lancé
            if _brain.connected and launched_by_us:
                _brain._call_sync({"cmd": "shutdown"})
        except Exception:
            pass
        _brain.disconnect()
        _brain = None

    # Tuer le process seulement si on l'a lancé nous-mêmes
    if launched_by_us:
        try:
            _sidecar_process.terminate()
            _sidecar_process.wait(timeout=3)
        except Exception:
            try:
                _sidecar_process.kill()
            except Exception:
                pass
        _sidecar_process = None
    logger.debug("ONNX backend + sidecar shutdown complet")


# ── Wrappers tree-sitter (synchrones) ────────────────────────────────────────


def ts_audit(code: str) -> dict:
    """Audit sécurité via tree-sitter sidecar. Retourne {"safe", "message", "violations"}."""
    brain = get_brain()
    if brain is None:
        return {"safe": True, "message": "sidecar absent — audit ignoré", "violations": []}
    return brain.audit_sync(code)


def ts_surgery(source: str, target_name: str, new_code: str) -> dict:
    """Chirurgie bytewise via tree-sitter sidecar. Retourne {"success", "message", "result", "backup"}."""
    brain = get_brain()
    if brain is None:
        return {"success": False, "message": "sidecar absent", "result": "", "backup": ""}
    return brain.surgery_sync(source, target_name, new_code)


def ts_locate(source: str, target_name: str) -> Optional[dict]:
    """Localise une fonction via tree-sitter. Retourne le nœud ou None."""
    brain = get_brain()
    if brain is None:
        return None
    return brain.locate_sync(source, target_name)


def ml_analyze(code: str) -> dict:
    """Analyse enrichie ML via sidecar. Retourne complexité, libs, score sécu."""
    brain = get_brain()
    if brain is None:
        return {}
    return brain.analyze_sync(code)


def ml_score(code: str) -> dict:
    """Score de confiance composite via sidecar."""
    brain = get_brain()
    if brain is None:
        return {"confidence": 0.5}
    return brain.score_sync(code)


def stm_push(session: str, code: str, error: str) -> int:
    """Pousse un échec dans la Short-Term Memory du sidecar."""
    brain = get_brain()
    return brain.stm_push(session, code, error) if brain else 0


def stm_get(session: str) -> list:
    """Récupère l'historique STM."""
    brain = get_brain()
    return brain.stm_get(session) if brain else []


def stm_clear(session: str) -> None:
    """Vide la STM d'une session."""
    brain = get_brain()
    if brain:
        brain.stm_clear(session)


def onnx_status() -> str:
    """Résumé lisible de l'état des backends ONNX + tree-sitter."""
    lines = []
    brain = _brain

    if brain and brain.embedder_ready:
        lines.append(f"✅ Embeddings  : MiniLM-L6-v2 (dim={brain.dim}) [sidecar]")
    else:
        lines.append("❌ Embeddings  : brain_worker absent → Ollama bge-m3")

    if brain and brain.generator_ready:
        lines.append(f"✅ Génération  : Phi-3.5 [{brain.backend.upper()}] [sidecar]")
    else:
        lines.append("❌ Génération  : brain_worker absent → Ollama")

    if brain and brain.tree_sitter_ready:
        lines.append("✅ Sentinelle  : tree-sitter actif [sidecar]")
    else:
        err = _TS_ERROR
        if err:
            lines.append(f"⚠ Sentinelle  : tree-sitter inactif ({err})")
        else:
            lines.append("⚠ Sentinelle  : tree-sitter non disponible")

    return "\n".join(lines)


# =============================================================================
# § 2 — VERSIONNEMENT  (ex-version_manager.py adaptateur)
# =============================================================================

# =============================================================================
# GESTIONNAIRE DE VERSIONS — délègue à version_manager.py
# =============================================================================
# Prérequis : version_manager.py doit être dans le même dossier que Nokido.py
#
# Pour installer Git (si pas encore fait) :
#   https://git-scm.com/download/win
#
# Ce bloc remplace entièrement l'ancien VersionManager intégré.
# Il ne contient AUCUNE logique dupliquée — tout est dans version_manager.py
# =============================================================================

try:
    from version_manager import VersionManager as _VersionManager, ChangeType

    _VM_AVAILABLE = True
except ImportError:
    _VM_AVAILABLE = False
    # Silencieux : Nokido.py utilise son VersionManager interne
    logger.debug("forge_runtime: version_manager.py absent — mode dégradé silencieux")


class VersionManagerAdapter:
    """
    Adaptateur léger entre Nokido.py et version_manager.py.

    Rôle : traduire les appels de l'ancien code (prepare_patch, get_current_code)
    vers la nouvelle API (apply_patch, current_code) sans rien casser.

    Si version_manager.py est absent, tombe en mode dégradé silencieux.
    """

    def __init__(self) -> None:
        """Initialise."""
        if _VM_AVAILABLE:
            # Initialiser avec le fichier source courant (Nokido.py lui-même)
            self._vm = _VersionManager(
                source_file=Path(__file__).resolve().parent / "Nokido.py",
                author=os.getenv("VM_AUTHOR", "OctoDevOps"),
                use_git=os.getenv("VM_USE_GIT", "true").lower() == "true",
            )
            logger.info(
                f"VersionManager prêt — v{self._vm.current_version} "
                f"| git={'activé' if self._vm.use_git else 'désactivé'}"
            )
        else:
            self._vm = None

    # ------------------------------------------------------------------
    # API PUBLIQUE (appelée par @apply et @estim dans DevOpsApp)
    # ------------------------------------------------------------------

    async def prepare_patch(
        self,
        new_code: str,
        description: str,
        major: bool = False,
    ) -> Optional[Path]:
        """
        Point d'entrée unique pour appliquer un patch depuis le TUI.

        - major=False → ChangeType.PATCH  (@apply, corrections)
        - major=True  → ChangeType.MINOR  (@estim, nouvelles features)

        Retourne le chemin du nouveau fichier, ou None si échec / non disponible.
        """
        if self._vm is None:
            logger.warning("Versionnement non disponible — patch ignoré")
            return None

        # Traduire le flag booléen en ChangeType SemVer propre
        change_type = ChangeType.MINOR if major else ChangeType.PATCH

        return await self._vm.apply_patch(
            new_code=new_code,
            description=description,
            change_type=change_type,
        )

    def get_current_code(self) -> str:
        """
        Retourne le code actif (workspace) ou le source si VM indisponible.
        Utilisé par @audit et @estim pour lire le code à analyser.
        """
        if self._vm is not None:
            return self._vm.current_code

        # Fallback : lire le source directement
        logger.warning("VM indisponible — lecture du source original")
        return Path(__file__).read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # UTILITAIRES (accessibles via @version dans le TUI)
    # ------------------------------------------------------------------

    def history_summary(self, limit: int = 10) -> str:
        """Tableau lisible des dernières versions."""
        if self._vm is None:
            return "Versionnement non disponible."
        return self._vm.get_history_summary(limit)

    def diff(self, version_a: str, version_b: str) -> str:
        """Diff textuel entre deux versions."""
        if self._vm is None:
            return "Versionnement non disponible."
        return self._vm.diff_versions(version_a, version_b)

    def rollback(self, version: str) -> bool:
        """Restaure une version précédente comme copie active."""
        if self._vm is None:
            logger.error("Rollback impossible — version_manager.py absent")
            return False
        return self._vm.rollback(version)

    @property
    def current_version(self) -> str:
        """Version courante sous forme 'x.y.z'."""
        if self._vm is None:
            return "?.?.?"
        return self._vm.current_version

    @property
    def work_path(self) -> Optional[Path]:
        """Chemin du fichier de travail actif (pour compatibilité)."""
        if self._vm is None:
            return None
        return self._vm._get_workspace_file()


# Instance globale — remplace l'ancien `version_manager = VersionManager()`
version_manager = VersionManagerAdapter()


__all__ = [
    "init_onnx_backend",
    "get_embedder",
    "get_generator",
    "onnx_get_embeddings",
    "onnx_call",
    "onnx_stream",
    "onnx_status",
    "shutdown_onnx_backend",
    "get_brain",
    "ts_audit",
    "ts_surgery",
    "ts_locate",
    "ml_analyze",
    "ml_score",
    "stm_push",
    "stm_get",
    "stm_clear",
    "VersionManagerAdapter",
]
