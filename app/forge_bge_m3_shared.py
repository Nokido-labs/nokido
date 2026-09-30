"""forge_bge_m3_shared.py - In-process BGE-M3 shared session (Niveau 2 pattern).

DESIGN
======
Stratégie 3-niveaux selon dispo wheels cp314t :

- **Niveau 1 (NOW)** : `tools/brain_worker.py :5557 ZMQ` daemon = process séparé,
  modèle chargé une fois, clients pushent texts via ZMQ msgpack. Round-trip ~50ms.
  Aucune duplication mémoire. Fonctionne sur GIL + free-threaded.

- **Niveau 2 (cp314t onnxruntime dispo)** : ce module. ONNX `InferenceSession`
  singleton in-process avec double-checked locking. Threads partagent un seul
  modèle (~2.5GB BGE-M3) en RAM. ONNX Runtime `.run()` est thread-safe pour
  exécutions concurrentes (Microsoft docs). Lock UNIQUEMENT à l'initialisation.
  Tokenizer HuggingFace via `threading.local()` (encode() pas garanti thread-safe).

- **Niveau 3 (cp314t torch dispo)** : sentence-transformers natif + `torch.share_memory_()`
  pour les weights. Gain ~30% vs ONNX. Bloqué par PyTorch cp314t (Q4 2026 estimé).

UTILISATION
===========
Aujourd'hui (2026-07-07, lot #8 clos) :
    from forge_bge_m3_shared import embed_parallel
    vecs = embed_parallel(["text1", "text2", ...])
    # -> delegue a forge_embed_router.embed (:8099 llama GGUF en tete,
    #    brain_worker :5557 mort 06-03 garde en fallback si reactive)

Quand onnxruntime cp314t arrive :
    LAFORGE_BGE_M3_INPROCESS=1 dans .env
    from forge_bge_m3_shared import embed_parallel
    vecs = embed_parallel(texts)  # -> InferenceSession partagée

SÉCURITÉ THREAD
===============
- `_session` : init via double-checked locking + RLock → 1 instance garantie
- `_tok_local` : `threading.local()` → tokenizer dédié par thread
- ONNX `.run()` : ré-entrant, pas de lock côté Python
- DirectML provider iGPU : driver WDDM sérialise au niveau matériel → cap à 1-2 threads
- CPU provider : ONNX threadpool interne (intra_op_num_threads), cap Python à 1-2

Pattern Gemini Web 2026-05-29 validé.

REFS
====
- Microsoft ONNX Runtime threading: https://onnxruntime.ai/docs/api/python/api_summary.html
- PEP 703 free-threading: https://peps.python.org/pep-0703/
- HuggingFace tokenizers thread-safety: tokenizers >=0.21 = thread-safe encode,
  mais legacy tokenizers (slow) pas garantis → threading.local() défensif.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from nokido_agent.app.forge_python_runtime import IS_NOGIL, recommended_worker_count

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

if TYPE_CHECKING:
    from onnxruntime import InferenceSession  # noqa: F401

logger = logging.getLogger("forge_bge_m3_shared")

# ── Config ────────────────────────────────────────────────────────────────────

# Activé via env. Sinon redirige vers brain_worker ZMQ.
INPROCESS_ENABLED: bool = os.environ.get("LAFORGE_BGE_M3_INPROCESS", "0") == "1"
# Tete de pooling du vecteur dense : "cls" (tete officielle de BGE-M3, DEFAUT depuis le
# 2026-09-06) ou "mean" (historique de ce module). Elle determine l'ESPACE vectoriel
# produit -- deux valeurs, deux espaces incompatibles.
# LE DEFAUT A CHANGE SUR PREUVE, pas sur lecture de documentation : contre les vecteurs
# deja stockes dans rag_chunks, sur les MEMES huit textes, mesure par
# tools/forge_embed_onnx_mesure.py --env ryzen-ai-final :
#     cls  -> cos 1.0000, etendue 0.0000   (identite parfaite)
#     mean -> cos 0.6913, etendue 0.0070   (transformation systematique)
# Le module poolait en moyenne : tout vecteur qu'il aurait ecrit aurait ete SILENCIEUSEMENT
# hors de l'espace de la base. Aucune erreur n'aurait ete levee -- la colonne accepte
# 1024 flottants quels qu'ils soient.
POOLING: str = os.environ.get("LAFORGE_BGE_M3_POOLING", "cls").strip().lower()

# Path modèle BGE-M3 ONNX
MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "bge_m3_onnx" / "model.onnx"

# Per-worker RAM footprint (GB) — utilisé pour cap RAM via recommended_worker_count
MODEL_SIZE_GB: float = 2.5

# Provider preference : DirectML iGPU > CPU > NPU
PROVIDERS_PREFERENCE: list[str] = [
    "DmlExecutionProvider",
    "CPUExecutionProvider",
]

# ── State singleton ──────────────────────────────────────────────────────────

_session_lock = threading.RLock()
_session: "Optional[InferenceSession]" = None
_tok_local = threading.local()


def _build_session_opts():
    """SessionOptions thread-safe + intra_op_num_threads tuned for free-threaded."""
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    # Intra-op = parallélisme INTERNE à un seul .run() call.
    # Free-threaded mode = on appelle .run() depuis N threads Python → intra_op
    # doit rester modeste pour éviter sur-souscription. Cap à 2.
    opts.intra_op_num_threads = 2 if IS_NOGIL else 4
    opts.inter_op_num_threads = 1  # tasks parallèles intra-modèle, rare pour BGE-M3
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return opts


def _get_session():
    """Double-checked locking pour session singleton (~2.5GB BGE-M3 ONNX)."""
    global _session
    if _session is not None:
        return _session
    with _session_lock:
        if _session is None:  # vérif après acquisition lock
            try:
                import onnxruntime as ort
            except ImportError as e:
                raise RuntimeError(
                    f"onnxruntime not installed (cp{__import__('sys').version_info.major}"
                    f"{__import__('sys').version_info.minor}t wheels not available yet?). "
                    f"Fall back to brain_worker ZMQ. {e}"
                ) from e

            if not MODEL_PATH.exists():
                raise FileNotFoundError(f"BGE-M3 ONNX model missing: {MODEL_PATH}")

            available = ort.get_available_providers()
            providers = [p for p in PROVIDERS_PREFERENCE if p in available] or ["CPUExecutionProvider"]
            logger.info(f"[bge_m3_shared] loading {MODEL_PATH} providers={providers}")
            _session = ort.InferenceSession(
                str(MODEL_PATH), sess_options=_build_session_opts(), providers=providers
            )
    return _session


def _get_tokenizer():
    """Tokenizer per-thread via threading.local() (encode() pas toujours thread-safe)."""
    tok = getattr(_tok_local, "tok", None)
    if tok is None:
        from transformers import AutoTokenizer

        # Le modele est charge en LOCAL (MODEL_PATH) mais le tokenizer l'etait par NOM de
        # depot : sous un compte sans egress, `from_pretrained("BAAI/bge-m3")` leve
        # OSError et tout le chemin ONNX parait mort alors que les fichiers tokenizer sont
        # sur disque a cote du modele (tokenizer.json, sentencepiece.bpe.model,
        # tokenizer_config.json, special_tokens_map.json). Mesure 2026-09-06.
        # Le dossier local PRIME ; le nom du depot reste un repli explicite.
        _local = MODEL_PATH.parent
        try:
            tok = AutoTokenizer.from_pretrained(str(_local), use_fast=True,
                                                local_files_only=True)
        except Exception as _e_local:
            logger.warning(
                "[bge_m3_shared] tokenizer local indisponible dans %s (%s: %s) -- "
                "repli sur le depot distant, qui exige un acces reseau",
                _local, type(_e_local).__name__, _e_local)
            tok = AutoTokenizer.from_pretrained("BAAI/bge-m3", use_fast=True)
        _tok_local.tok = tok
    return tok


# ── API publique ──────────────────────────────────────────────────────────────


def embed_parallel(texts: list[str], max_workers: Optional[int] = None) -> list[list[float]]:
    """Embed une liste de texts en BGE-M3 1024D, exécution thread-safe parallèle.

    Args:
        texts: textes à embedder.
        max_workers: threads concurrents. None = auto (recommended_worker_count RAM-aware).

    Returns:
        Liste de vecteurs float (1024D) dans le MEME ordre que `texts`.

    Note:
        Si INPROCESS_ENABLED=False ou wheels manquantes → délègue à brain_worker ZMQ.
    """
    if not INPROCESS_ENABLED:
        return _delegate_to_brain_worker(texts)

    try:
        sess = _get_session()
    except (RuntimeError, FileNotFoundError, ImportError) as e:
        logger.warning(f"[bge_m3_shared] in-process unavailable, falling back ZMQ: {e}")
        return _delegate_to_brain_worker(texts)

    if max_workers is None:
        max_workers = recommended_worker_count(io_bound=False, model_size_gb=MODEL_SIZE_GB)

    # Single-thread fast-path : pas de overhead ThreadPool si max_workers <= 1
    if max_workers <= 1 or len(texts) <= 4:
        return _embed_batch(sess, texts)

    # Multi-thread : chunks équilibrés
    from concurrent.futures import ThreadPoolExecutor

    chunks_per_worker = max(1, len(texts) // max_workers)
    batches = [texts[i : i + chunks_per_worker] for i in range(0, len(texts), chunks_per_worker)]

    results: list[list[list[float]]] = [[] for _ in batches]
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="bge_m3") as pool:
        futures = {pool.submit(_embed_batch, sess, b): i for i, b in enumerate(batches)}
        for fut in futures:
            i = futures[fut]
            results[i] = fut.result()

    # Concat dans l'ordre des batches
    flat = []
    for r in results:
        flat.extend(r)
    return flat


def _embed_batch(sess, batch: list[str]) -> list[list[float]]:
    """Inférence ONNX d'un batch. session.run() = thread-safe (Microsoft confirmed)."""
    import numpy as np

    tok = _get_tokenizer()
    enc = tok(batch, padding=True, truncation=True, max_length=512, return_tensors="np")
    inputs = {"input_ids": enc["input_ids"].astype("int64"), "attention_mask": enc["attention_mask"].astype("int64")}
    if "token_type_ids" in [i.name for i in sess.get_inputs()]:
        inputs["token_type_ids"] = enc.get("token_type_ids", np.zeros_like(enc["input_ids"])).astype("int64")

    outputs = sess.run(None, inputs)
    last_hidden = outputs[0]  # (B, T, 1024)

    # TETE DE POOLING — explicite, parce qu'elle DECIDE de l'espace vectoriel.
    # Comparaison des deux tetes sur une seule charge de session (le pooling ne touche que
    # la reduction des sorties) : cls rend cos 1.0000 contre la base, mean 0.6913. Le
    # defaut est donc cls. Cf. le commentaire de POOLING pour la mesure complete.
    if POOLING == "cls":
        pooled = last_hidden[:, 0]
    else:
        mask = inputs["attention_mask"].astype("float32")[..., None]
        summed = (last_hidden * mask).sum(axis=1)
        counts = mask.sum(axis=1).clip(min=1e-9)
        pooled = summed / counts
    norms = np.linalg.norm(pooled, axis=1, keepdims=True).clip(min=1e-9)
    normalized = pooled / norms
    return normalized.tolist()


def _delegate_to_brain_worker(texts: list[str]) -> list[list[float]]:
    """Fallback Niveau 1 : delegue au ROUTER embed (ordre local-first, :8099
    llama GGUF vivant en tete ; le nom historique brain_worker :5557 = 2e,
    mort 2026-06-03). Pas de stub : chemin VIVANT."""
    try:
        from nokido_agent.app.forge_embed_router import embed_batch
    except ImportError:
        logger.error("forge_embed_router unavailable -- cannot embed")
        return [[] for _ in texts]
    return embed_batch(texts)


def runtime_info() -> dict:
    """Diagnostic pour /health endpoint."""
    return {
        "inprocess_enabled": INPROCESS_ENABLED,
        "session_loaded": _session is not None,
        "model_path_exists": MODEL_PATH.exists(),
        "free_threaded": IS_NOGIL,
        "model_size_gb": MODEL_SIZE_GB,
        "recommended_workers": recommended_worker_count(io_bound=False, model_size_gb=MODEL_SIZE_GB),
    }


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(runtime_info(), indent=2))
    if "--smoke" in sys.argv:
        vecs = embed_parallel(["hello world", "second text", "third"])
        print(f"got {len(vecs)} vecs, dim={len(vecs[0]) if vecs and vecs[0] else 0}")
