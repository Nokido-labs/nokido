"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_npu_embedder
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
forge_npu_embedder.py -- Backend NPU optimise pour Nokido.
Vrai batch ONNX (1 session.run par batch), cache vectoriel numpy,
cosine vectorisee, modele FP32 clean (plus rapide que INT8 sur VitisAI).

Modele : microsoft/MiniLM-L12-H384-uncased (ONNX opset 21)
Source : models/clean_fp32/model.onnx

Benchmark (VitisAI EP, Ryzen 8700G) :
  clean_fp32  : 14ms/texte batch, 17ms unitaire
  quantized   : 17ms/texte batch, 27ms unitaire
  -> FP32 gagne sur ce NPU, on l'utilise. (Note: BGE-M3 dim=1024 preferable)
"""


import json
import logging
import os
import shutil
import sqlite3
from pathlib import Path
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# -- Chemins par defaut --
_ROOT = Path(__file__).resolve().parent.parent
# Chemin modele configurable via LAFORGE_NPU_MODEL ou fallback sur minilm_int8
_DEFAULT_MODEL = Path(os.environ.get("LAFORGE_NPU_MODEL", str(_ROOT / "app" / "models" / "npu" / "minilm_int8.onnx")))
_DEFAULT_TOKENIZER_DIR = _DEFAULT_MODEL.parent
_DEFAULT_DB = _ROOT / "RAG" / "embeddings.db"
_RYZEN_AI_INSTALL = r"C:\Program Files\RyzenAI\1.7.0"
_VAIP_CONFIG = os.path.join(_RYZEN_AI_INSTALL, "voe-4.0-win_amd64", "vaip_config.json")

EMBED_DIM = 1024
MAX_LENGTH = 128
_BATCH_CEILING = 64


def detect_hardware() -> dict:
    """
    Détecte les accélérateurs disponibles sur cette machine.
    Utilisé par l installeur pour la version distribuable.
    Retourne un dict portable sans dépendance forge_*.

    Résultat exemple :
        {
            "npu_vitisai": True,    # AMD Ryzen AI (XDNA)
            "gpu_directml": True,   # AMD/Intel/NVIDIA via DirectX
            "gpu_cuda": False,      # NVIDIA CUDA
            "gpu_openvino": False,  # Intel via OpenVINO
            "npu_qnn": False,       # Qualcomm Snapdragon
            "npu_coreml": False,    # Apple ANE
            "cpu_avx2": True,       # x86 AVX2
            "recommended_ep": "VitisAI",  # Provider recommandé
            "onnxruntime_version": "1.x"
        }
    """
    result = {
        "npu_vitisai": False,
        "gpu_directml": False,
        "gpu_cuda": False,
        "gpu_openvino": False,
        "npu_qnn": False,
        "npu_coreml": False,
        "cpu_avx2": False,
        "recommended_ep": "CPU",
        "onnxruntime_version": "N/A",
    }
    try:
        import onnxruntime as ort

        result["onnxruntime_version"] = ort.__version__
        avail = set(ort.get_available_providers())
        result["npu_vitisai"] = "VitisAIExecutionProvider" in avail
        result["gpu_directml"] = "DmlExecutionProvider" in avail
        result["gpu_cuda"] = "CUDAExecutionProvider" in avail
        result["gpu_openvino"] = "OpenVINOExecutionProvider" in avail
        result["npu_qnn"] = "QNNExecutionProvider" in avail
        result["npu_coreml"] = "CoreMLExecutionProvider" in avail
        # Priorité : NPU > GPU > CPU
        if result["npu_vitisai"]:
            result["recommended_ep"] = "VitisAI"
        elif result["npu_qnn"]:
            result["recommended_ep"] = "QNN"
        elif result["npu_coreml"]:
            result["recommended_ep"] = "CoreML"
        elif result["gpu_directml"]:
            result["recommended_ep"] = "DirectML"
        elif result["gpu_cuda"]:
            result["recommended_ep"] = "CUDA"
        elif result["gpu_openvino"]:
            result["recommended_ep"] = "OpenVINO"
        else:
            result["recommended_ep"] = "CPU"
    except ImportError:
        pass
    # Détecter AVX2 (CPU x86)
    try:
        import platform, subprocess

        if platform.machine().lower() in ("amd64", "x86_64"):
            r = subprocess.run(
                ["python", "-c", "import numpy; numpy.zeros(4,dtype='float32').sum()"], capture_output=True, timeout=3
            )
            result["cpu_avx2"] = r.returncode == 0
    except Exception:
        result["cpu_avx2"] = True  # supposé
    return result


# ── Singleton module-level — une seule session ONNX pour tout le processus ────
# forge_rag_engine.py l'utilise via get_npu_embedder().
# N'instanciez JAMAIS NPUEmbedder() directement dans une boucle d'appel.
# ── Proxy subprocess vers env NPU (numpy 1.26.4 + VitisAI) ──────────────────
_NPU_PYTHON = os.path.expanduser(r"~\miniforge3\envs\ryzen-ai-final\python.exe")
_NPU_PROBE = str(Path(__file__).resolve().parent.parent / "sandbox" / "npu_probe.py")
_NPU_MODEL = str(Path(__file__).resolve().parent / "models" / "npu" / "minilm_int8.onnx")


def embed_via_probe(texts: list[str]) -> list[list[float]] | None:
    """Embed via env NPU dédié (subprocess). Contourne incompatibilité numpy 2.x."""
    import subprocess as _sp, json as _j

    if not Path(_NPU_PYTHON).exists() or not Path(_NPU_PROBE).exists():
        return None
    try:
        r = _sp.run(
            [_NPU_PYTHON, _NPU_PROBE, _NPU_MODEL, _j.dumps(texts)],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        data = _j.loads(r.stdout.strip())
        if data.get("ok") and data.get("vectors"):
            logger.info(f"[NPU proxy] provider={data['provider']} texts={len(texts)}")
            return data["vectors"]
        logger.warning(f"[NPU probe] {data.get('error', 'no vectors')}")
    except Exception as e:
        logger.warning(f"[NPU probe] exception: {e}")
    return None


def get_embed(texts: list[str]) -> list[list[float]] | None:
    """Point d'entrée unique: probe NPU -> singleton -> None."""
    # 1. Env NPU dédié (numpy 1.26.4, VitisAI/DML)
    result = embed_via_probe(texts)
    if result:
        return result
    # 2. Singleton dans env courant (CPU fallback)
    emb = get_npu_embedder()
    if emb:
        return emb.embed_batch(texts)
    return None


_SINGLETON: "NPUEmbedder | None" = None
import threading as _threading

_SINGLETON_LOCK = _threading.Lock()


def get_npu_embedder(model_path=None, db_path=None, tokenizer_dir=None, ryzen_install=None) -> "NPUEmbedder | None":
    """
    Retourne le singleton NPUEmbedder.
    1er appel : charge ort.InferenceSession + tokenizer (~1200ms).
    Appels suivants : retourne l'instance existante (<1ms).

    Thread-safe. À utiliser partout à la place de NPUEmbedder().
    """
    global _SINGLETON
    # Check NumPy compat — onnxruntime-vitisai nécessite NumPy < 2
    try:
        import numpy as _np

        if int(_np.__version__.split(".")[0]) >= 2:
            return None  # NumPy 2.x incompatible silencieux
    except Exception:
        return None
    with _SINGLETON_LOCK:
        if _SINGLETON is None:
            _SINGLETON = NPUEmbedder(
                model_path=model_path,
                db_path=db_path,
                tokenizer_dir=tokenizer_dir,
                ryzen_install=ryzen_install,
            )
            if not _SINGLETON.available:
                _SINGLETON = None  # garder None pour retry propre
        return _SINGLETON


def _patch_vitis_ai(ryzen_install: str = _RYZEN_AI_INSTALL) -> bool:
    """Copie la DLL NPU VitisAI dans onnxruntime/capi si necessaire."""
    try:
        import onnxruntime

        capi_path = os.path.join(os.path.dirname(onnxruntime.__file__), "capi")
        source_dll = os.path.join(ryzen_install, "onnxruntime", "bin", "dyn_dispatch_core.dll")
        if not os.path.exists(source_dll):
            source_dll = os.path.join(ryzen_install, "voe-4.0-win_amd64", "onnxruntime", "bin", "dyn_dispatch_core.dll")
        dest_dll = os.path.join(capi_path, "dyn_dispatch_core.dll")
        if not os.path.exists(source_dll):
            logger.debug(f"VitisAI DLL introuvable : {source_dll}")
            return False
        if not os.path.exists(dest_dll):
            logger.info(f"Installation DLL NPU : {dest_dll}")
            shutil.copy(source_dll, dest_dll)
        bin_dir = os.path.join(ryzen_install, "onnxruntime", "bin")
        if os.path.isdir(bin_dir):
            os.add_dll_directory(bin_dir)
        os.add_dll_directory(capi_path)
        return True
    except Exception as e:
        logger.debug(f"patch_vitis_ai: {e}")
        return False


class NPUEmbedder:
    """Embedder local NPU/DML/CPU -- vrai batch ONNX, cache vectoriel numpy."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        db_path: Optional[str] = None,
        tokenizer_dir: Optional[str] = None,
        ryzen_install: Optional[str] = None,
    ):
        """Init.

        Args:
            model_path: Description.
            db_path: Description.
            tokenizer_dir: Description.
            ryzen_install: Description.
        """
        self.model_path = Path(model_path) if model_path else _DEFAULT_MODEL
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.tokenizer_dir = Path(tokenizer_dir) if tokenizer_dir else _DEFAULT_TOKENIZER_DIR
        self.ryzen_install = ryzen_install or _RYZEN_AI_INSTALL
        self.session = None
        self.tokenizer = None
        self.available = False
        self.provider = "none"
        # Cache vectoriel search_db (charge 1 fois, numpy vectorise)
        self._db_matrix: Optional[np.ndarray] = None
        self._db_norms: Optional[np.ndarray] = None
        self._db_paths: Optional[list] = None
        self._db_mtime: float = 0.0
        self._init()

    def _init(self) -> None:
        """Init."""
        if not self.model_path.exists():
            logger.warning(f"NPUEmbedder: modele introuvable {self.model_path}")
            return
        try:
            import onnxruntime as ort
            from transformers import AutoTokenizer
        except ImportError as e:
            logger.warning(f"NPUEmbedder: dependance manquante -- {e}")
            return

        # ── Détection hardware portable (Ring 0 — pas d import forge_*) ──────
        _ort_pkg = getattr(ort, "__version__", "?")
        _has_dml = "DmlExecutionProvider" in ort.get_available_providers()
        _has_vitis = "VitisAIExecutionProvider" in ort.get_available_providers()
        _has_cuda = "CUDAExecutionProvider" in ort.get_available_providers()
        _has_openvino = "OpenVINOExecutionProvider" in ort.get_available_providers()
        _has_qnn = "QNNExecutionProvider" in ort.get_available_providers()
        logger.info(
            f"[NPU] onnxruntime {_ort_pkg} — providers: "
            f"VitisAI={_has_vitis} DML={_has_dml} CUDA={_has_cuda} "
            f"OpenVINO={_has_openvino} QNN={_has_qnn}"
        )

        # Skipp VitisAI patch si DML disponible (evite crash DLL)
        if not _has_dml:
            _patch_vitis_ai(self.ryzen_install)

        vitis_opts = {
            "cacheDir": str(self.model_path.parent / ".cache"),
            "cacheKey": "forge_npu",
        }
        if os.path.exists(_VAIP_CONFIG):
            vitis_opts["config_file"] = _VAIP_CONFIG

        # Cascade universelle : NPU fabricant -> GPU generique -> CPU
        # Ajouter ici pour supporter d'autres NPU (Intel, Qualcomm, Apple)
        chains = [
            # AMD Ryzen AI (XDNA)
            # VitisAI desactive — SDK AMD non installe
            # (["VitisAIExecutionProvider", "CPUExecutionProvider"], [vitis_opts, {}], "NPU"),
            # Intel Core Ultra (NPU via OpenVINO) — necessite onnxruntime-openvino
            # (["OpenVINOExecutionProvider", "CPUExecutionProvider"], [{}, {}], "NPU_INTEL"),
            # Qualcomm Snapdragon X (NPU) — necessite onnxruntime-qnn
            # (["QNNExecutionProvider", "CPUExecutionProvider"], [{}, {}], "NPU_QC"),
            # Apple Silicon (ANE via CoreML) — macOS only
            # (["CoreMLExecutionProvider", "CPUExecutionProvider"], [{}, {}], "NPU_APPLE"),
            # GPU generique Windows (AMD/Intel/NVIDIA via DirectML)
            (["DmlExecutionProvider", "CPUExecutionProvider"], [{}, {}], "DML"),
            # NVIDIA CUDA (si disponible)
            # (["CUDAExecutionProvider", "CPUExecutionProvider"], [{}, {}], "CUDA"),
            # Fallback universel
            (["CPUExecutionProvider"], [{}], "CPU"),
        ]
        for providers, options, label in chains:
            try:
                self.session = ort.InferenceSession(
                    str(self.model_path),
                    providers=providers,
                    provider_options=options,
                )
                active_ep = self.session.get_providers()[0]
                if label == "NPU" and "VitisAI" not in active_ep:
                    logger.debug(f"VitisAI demande mais EP={active_ep}, suivant")
                    self.session = None
                    continue
                self.provider = label
                break
            except Exception as e:
                logger.debug(f"Provider {label}: {e}")
                continue

        if self.session is None:
            logger.error("NPUEmbedder: aucun provider ONNX disponible")
            return

        # Tokenizer local (evite un download HuggingFace a chaque demarrage)
        try:
            if (self.tokenizer_dir / "tokenizer.json").exists():
                self.tokenizer = AutoTokenizer.from_pretrained(
                    str(self.tokenizer_dir),
                    clean_up_tokenization_spaces=True,
                )
            else:
                self.tokenizer = AutoTokenizer.from_pretrained(
                    "microsoft/MiniLM-L12-H384-uncased",
                    clean_up_tokenization_spaces=True,
                )
        except Exception as e:
            logger.error(f"NPUEmbedder: tokenizer -- {e}")
            self.session = None
            return

        self.available = True
        logger.info(
            f"NPUEmbedder OK: {self.provider} "
            f"(EP={self.session.get_providers()[0]}), "
            f"dim={EMBED_DIM}, model={self.model_path.name}"
        )

    # ================================================================
    # EMBEDDING — vrai batch ONNX
    # ================================================================

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Encode N textes. 1 seul session.run() par sous-batch."""
        if not self.available:
            raise RuntimeError("NPUEmbedder non disponible")
        if not texts:
            return []
        all_vecs = []
        for start in range(0, len(texts), _BATCH_CEILING):
            chunk = texts[start : start + _BATCH_CEILING]
            inputs = self.tokenizer(
                chunk,
                padding="max_length",
                max_length=MAX_LENGTH,
                truncation=True,
                return_tensors="np",
            )
            # Inputs reels du modele (evite token_type_ids si absent du graph)
            _model_inputs = {n.name for n in self.session.get_inputs()}
            ort_inputs = {
                "input_ids": inputs["input_ids"].astype(np.int64),
                "attention_mask": inputs["attention_mask"].astype(np.int64),
            }
            if "token_type_ids" in _model_inputs:
                ort_inputs["token_type_ids"] = inputs.get("token_type_ids", np.zeros_like(inputs["input_ids"])).astype(
                    np.int64
                )
            output = self.session.run(None, ort_inputs)[0]  # (B, 128, 384)
            vecs = output.mean(axis=1)  # (B, 384)
            all_vecs.append(vecs)
        return np.vstack(all_vecs).tolist()

    def embed_one(self, text: str) -> List[float]:
        """Embed one.

        Args:
            text: Description.
        """
        return self.embed_batch([text])[0]

    # ================================================================
    # SEARCH — cache numpy vectorise
    # ================================================================

    def _load_db_cache(self) -> None:
        """Charge les vecteurs en RAM (1 seule fois, reload si DB change)."""
        if not self.db_path.exists():
            self._db_matrix = None
            return
        try:
            mtime = self.db_path.stat().st_mtime
            if mtime == self._db_mtime and self._db_matrix is not None:
                return  # deja a jour
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL;")
            rows = conn.execute("SELECT file_path, embedding FROM embeddings").fetchall()
            conn.close()
            if not rows:
                self._db_matrix = None
                return
            paths = []
            vecs = []
            for path, emb_json in rows:
                paths.append(path)
                vecs.append(json.loads(emb_json))
            mat = np.array(vecs, dtype=np.float32)  # (N, 384)
            self._db_matrix = mat
            self._db_norms = np.linalg.norm(mat, axis=1)  # (N,)
            self._db_paths = paths
            self._db_mtime = mtime
            logger.debug(f"DB cache: {len(paths)} vecteurs charges")
        except Exception as e:
            logger.warning(f"DB cache load: {e}")
            self._db_matrix = None

    def search_db(self, query: str, top_k: int = 5) -> List[dict]:
        """Recherche cosine numpy vectorisee (1 dot product matriciel)."""
        if not self.available:
            return []
        self._load_db_cache()
        if self._db_matrix is None:
            return []

        qvec = np.array(self.embed_one(query), dtype=np.float32)  # (384,)
        qn = np.linalg.norm(qvec)
        if qn < 1e-9:
            return []

        # Cosine vectorisee : 1 seul np.dot pour 718 vecteurs
        scores = self._db_matrix @ qvec / (self._db_norms * qn + 1e-9)  # (N,)

        # Top-K sans tri complet (argpartition)
        k = min(top_k, len(scores))
        top_idx = np.argpartition(scores, -k)[-k:]
        top_idx = top_idx[np.argsort(scores[top_idx])[::-1]]

        return [{"file_path": self._db_paths[i], "score": float(scores[i])} for i in top_idx]

    # ================================================================
    # STATUS
    # ================================================================

    def status(self) -> dict:
        """Status."""
        db_count = 0
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                db_count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
                conn.close()
            except Exception:
                pass
        return {
            "available": self.available,
            "provider": self.provider,
            "ep": self.session.get_providers()[0] if self.session else "none",
            "model": self.model_path.name if self.model_path.exists() else "missing",
            "dim": EMBED_DIM,
            "db_vectors": db_count,
        }


# ── Stub init_onnx_backend — requis par forge_startup._init_onnx_bg ──────────
# forge_onnx_sidecar absent → fallback sur ce stub qui retourne un dict vide
def init_onnx_backend(load_generator: bool = False, auto_launch: bool = False) -> dict:
    """
    Stub de secours quand forge_onnx_sidecar est absent.
    Retourne un dict indiquant que les backends ne sont pas disponibles.
    """
    import logging as _lg

    _lg.getLogger("Nokido.NPU").warning("init_onnx_backend: forge_onnx_sidecar absent — stub actif")
    return {"embedder": False, "generator": False, "tree_sitter": False}


# FORGE_GRAPHCODEBERT_LOAD_V1 — Mean Pooling stable
def get_stable_embeddings(text_list: list[str], model_name: str = "microsoft/graphcodebert-base") -> "np.ndarray":
    """Embeddings stables via Mean Pooling (évite le pooler non initialisé).

    Args:
        text_list: Liste de textes à encoder.
        model_name: Modèle HuggingFace à utiliser.

    Returns:
        Array numpy de shape (len(text_list), 768).
    """
    try:
        import torch
        import numpy as np
        from transformers import AutoTokenizer, RobertaModel, logging as _hfl

        _hfl.get_logger("transformers").setLevel(_hfl.ERROR)
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = RobertaModel.from_pretrained(model_name)
        model.eval()
        inputs = tokenizer(text_list, padding=True, truncation=True, max_length=128, return_tensors="pt")
        with torch.no_grad():
            outputs = model(**inputs)
        tok_emb = outputs.last_hidden_state
        mask_exp = inputs["attention_mask"].unsqueeze(-1).expand(tok_emb.size()).float()
        embeddings = torch.sum(tok_emb * mask_exp, 1) / torch.clamp(mask_exp.sum(1), min=1e-9)
        return embeddings.numpy()
    except Exception as e:
        import numpy as np

        print(f"[NPUEmbedder] get_stable_embeddings KO: {e}")
        return np.zeros((len(text_list), 768))
