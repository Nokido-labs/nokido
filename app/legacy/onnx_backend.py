"""
onnx_backend.py — Backend d'inférence ONNX pour OctoDevOps
===========================================================
Deux rôles distincts :

1. EMBEDDINGS  → all-MiniLM-L6-v2 via sentence-transformers
   - ~2ms par batch vs 200-500ms via Ollama
   - Synchrone mais rapide → wrappé en run_in_executor

2. GÉNÉRATION  → Phi-3.5 Mini Instruct ONNX via onnxruntime-genai
   - DirectML pour iGPU/NPU (Radeon 780M + Ryzen AI NPU)
   - Fallback CPU si DirectML indisponible
   - Interface compatible avec ollama_call / ollama_stream

Architecture :
  OnnxEmbedder   → get_embeddings(texts)  → List[List[float]]
  OnnxGenerator  → generate(messages)     → str
  OnnxGenerator  → stream(messages, cb)   → str  (token par token)

Fallback automatique vers Ollama si ONNX non disponible.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# DÉTECTION DES DÉPENDANCES
# =============================================================================

HAS_SENTENCE_TRANSFORMERS = False
HAS_ONNXRUNTIME_GENAI = False

try:
    from sentence_transformers import SentenceTransformer

    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    pass

try:
    import onnxruntime_genai as og

    HAS_ONNXRUNTIME_GENAI = True
except ImportError:
    pass

# =============================================================================
# CONFIGURATION — CHEMINS MODÈLES
# =============================================================================

# Chemin du dossier models/ : dans app/, models/ est à la racine (parent)
_BASE = Path(__file__).resolve().parent.parent

# all-MiniLM-L6-v2 : téléchargé dans le cache HuggingFace automatiquement
MINILM_MODEL_ID = "all-MiniLM-L6-v2"

# Phi-3.5 Mini : dossier local téléchargé via huggingface-cli
# Cherche d'abord DirectML (NPU/iGPU), puis CPU
PHI35_DIRECTML_PATH = _BASE / "models" / "phi3.5" / "directml" / "directml-int4-awq-block-128"
PHI35_CPU_PATH = _BASE / "models" / "phi3.5" / "cpu_and_mobile" / "cpu-int4-rtn-block-32-acc-level-4"


def _find_phi35_path() -> Optional[Path]:
    """Retourne le chemin Phi-3.5 disponible (DirectML prioritaire)."""
    if PHI35_DIRECTML_PATH.exists():
        logger.info(f"Phi-3.5 DirectML trouvé : {PHI35_DIRECTML_PATH}")
        return PHI35_DIRECTML_PATH
    if PHI35_CPU_PATH.exists():
        logger.info(f"Phi-3.5 CPU trouvé : {PHI35_CPU_PATH}")
        return PHI35_CPU_PATH
    # Cherche n'importe quel dossier phi3.5 présent
    phi_base = _BASE / "models" / "phi3.5"
    if phi_base.exists():
        for p in phi_base.rglob("*.onnx"):
            logger.info(f"Phi-3.5 trouvé (auto) : {p.parent}")
            return p.parent
    return None


# =============================================================================
# EMBEDDINGS — all-MiniLM-L6-v2
# =============================================================================


class OnnxEmbedder:
    """
    Embeddings synchrones via sentence-transformers (all-MiniLM-L6-v2).
    Dimension de sortie : 384.
    Latence typique : 1-3ms pour un batch de 32 textes.
    """

    _instance: Optional["OnnxEmbedder"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._model: Optional[SentenceTransformer] = None
        self._ready = False
        self._dim = 384
        self._fail_reason: str = ""

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
            self._fail_reason = "sentence-transformers non installé → pip install sentence-transformers"
            logger.warning(self._fail_reason)
            return False
        try:
            t0 = time.monotonic()
            self._model = SentenceTransformer(MINILM_MODEL_ID)
            self._dim = self._model.get_sentence_embedding_dimension()
            self._ready = True
            logger.info(f"OnnxEmbedder chargé : {MINILM_MODEL_ID} dim={self._dim} en {time.monotonic() - t0:.2f}s")
            return True
        except Exception as e:
            self._fail_reason = f"Erreur chargement : {e}"
            logger.error(f"Erreur chargement OnnxEmbedder : {e}")
            return False

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def dim(self) -> int:
        return self._dim

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Encode une liste de textes → liste d'embeddings (synchrone)."""
        if not self._ready or not texts:
            return []
        try:
            vecs = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
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

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._ready = False
        self._path: Optional[Path] = None
        self._backend = "none"  # "directml" | "cpu" | "none"
        self._fail_reason: str = ""

    @classmethod
    def get(cls) -> "OnnxGenerator":
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
            self._fail_reason = "onnxruntime-genai non installé → pip install onnxruntime-genai"
            logger.warning(self._fail_reason)
            return False

        path = _find_phi35_path()
        if path is None:
            # Chercher ce qui existe vraiment sous models/ pour donner un diagnostic utile
            _models_dir = _BASE / "models"
            _found_hint = ""
            if _models_dir.exists():
                _subdirs = [p.name for p in _models_dir.iterdir() if p.is_dir()]
                if _subdirs:
                    _found_hint = f" (trouvé dans models/ : {', '.join(_subdirs[:5])})"
                    _found_hint += " — renommez le dossier en models/phi3.5/"
            self._fail_reason = (
                f"Phi-3.5 non trouvé dans models/phi3.5/{_found_hint}\n"
                "   → Structure attendue : models/phi3.5/directml/directml-int4-awq-block-128/\n"
                "   → Ou CPU            : models/phi3.5/cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/\n"
                "   → Télécharger via   : huggingface-cli download microsoft/Phi-3.5-mini-instruct-onnx "
                "--include 'directml/*' --local-dir ./models/phi3.5"
            )
            logger.warning(self._fail_reason)
            return False

        try:
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
            self._fail_reason = f"Erreur chargement Phi-3.5 : {e}"
            logger.error(self._fail_reason)
            return False

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def backend(self) -> str:
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

    def __del__(self):
        self.unload()


# =============================================================================
# INTERFACE PUBLIQUE — fonctions drop-in replacement
# =============================================================================

# Singletons (initialisés au démarrage via init_onnx_backend())
_embedder: Optional[OnnxEmbedder] = None
_generator: Optional[OnnxGenerator] = None


def init_onnx_backend(load_generator: bool = True) -> Dict[str, bool]:
    """
    Initialise les backends ONNX.
    À appeler une fois au démarrage (dans on_mount ou avant).
    Retourne {"embedder": bool, "generator": bool}.
    """
    global _embedder, _generator

    _embedder = OnnxEmbedder.get()
    emb_ok = _embedder.load()

    gen_ok = False
    if load_generator:
        _generator = OnnxGenerator.get()
        gen_ok = _generator.load()

    return {"embedder": emb_ok, "generator": gen_ok}


def get_embedder() -> Optional[OnnxEmbedder]:
    return _embedder if (_embedder and _embedder.ready) else None


def get_generator() -> Optional[OnnxGenerator]:
    return _generator if (_generator and _generator.ready) else None


async def onnx_get_embeddings(texts: List[str]) -> Optional[List[List[float]]]:
    """
    Embeddings via MiniLM ONNX.
    Drop-in replacement pour les appels Ollama embeddings dans RAGEngine.
    Retourne None si ONNX non disponible (→ fallback Ollama).
    """
    emb = get_embedder()
    if emb is None:
        return None
    result = await emb.encode_async(texts)
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
    gen = get_generator()
    if gen is None:
        raise RuntimeError("OnnxGenerator non disponible")
    return await gen.generate(messages, max_tokens)


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
    gen = get_generator()
    if gen is None:
        raise RuntimeError("OnnxGenerator non disponible")
    return await gen.stream(messages, on_token, on_done, max_tokens)


def shutdown_onnx_backend() -> None:
    """
    Libère proprement tous les backends ONNX.
    À appeler dans on_unmount de l app Textual.
    Évite les warnings "OGA Error: N instances leaked".
    """
    global _embedder, _generator
    if _generator is not None:
        _generator.unload()
    # SentenceTransformer se nettoie seul via GC, pas de unload nécessaire
    _embedder = None
    _generator = None
    logger.debug("ONNX backend shutdown complet")


def onnx_status() -> str:
    """Résumé lisible de l'état des backends ONNX avec diagnostic d'échec."""
    lines = []
    emb = get_embedder()
    gen = get_generator()

    if emb:
        lines.append(f"✅ Embeddings  : MiniLM-L6-v2 (dim={emb.dim})")
    else:
        reason = getattr(_embedder, "_fail_reason", "") if _embedder else ""
        if reason:
            lines.append(f"❌ Embeddings  : {reason}")
        else:
            lines.append("❌ Embeddings  : non initialisé (init_onnx_backend() non appelé ?)")

    if gen:
        lines.append(f"✅ Génération  : Phi-3.5 Mini [{gen.backend.upper()}]")
    else:
        reason = getattr(_generator, "_fail_reason", "") if _generator else ""
        if reason:
            # Multilignes → indentation propre dans le TUI
            reason_lines = reason.split("\n")
            lines.append(f"❌ Génération  : {reason_lines[0]}")
            for rl in reason_lines[1:]:
                lines.append(f"               {rl}")
        else:
            lines.append("❌ Génération  : non initialisé (init_onnx_backend() non appelé ?)")

    return "\n".join(lines)
