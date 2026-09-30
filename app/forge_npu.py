"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_053059_groqcerber
#FORGE:[score:90|agent:groq-cerberus|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: docstrings Google-style complets
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:90|agent:groq-cerberus|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
forge_npu.py — Gestion NPU / Execution Providers pour La Forge
===============================================================
Ryzen 7 8700G (Phoenix) :
  - NPU  XDNA gen1  ~16 TOPS  → onnxruntime-vitisai (VitisAI EP)
  - iGPU Radeon 780M RDNA3    → onnxruntime-directml (DirectML EP)
  - CPU  Zen4 8c/16t           → onnxruntime (CPU EP, fallback)

Cascade de sélection :
  NPU (VitisAI) > iGPU (DirectML) > CPU

Usage dans brain_worker.py :
    from forge_npu import NPUManager, EP
    npu = NPUManager()
    best = npu.best_ep()         # "npu" | "directml" | "cpu"
    sess = npu.create_session(model_path)  # OrtSession avec le bon EP
    status = npu.status_report()

Install guide (résumé) :
  DirectML (iGPU 780M) — dispo maintenant :
    pip install onnxruntime-directml

  NPU complet (XDNA) — nécessite AMD Ryzen AI SDK :
    1. https://ryzenai.docs.amd.com/en/latest/inst.html
    2. Installer AMD Ryzen AI Software (inclut VitisAI EP + librairies NPU)
    3. pip install ryzenai-onnxruntime  (ou via le SDK AMD)
    4. Télécharger le vaip_config.json AMD fourni dans le SDK
"""


import logging
import os
import time
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTES
# =============================================================================

# Nom PCI du NPU AMD Phoenix (VEN_1022 = AMD, DEV_1502 = IPU/NPU Phoenix)
_NPU_PCI_ID = "VEN_1022&DEV_1502"

# Chemin config VitisAI (fourni par AMD Ryzen AI SDK)
_VITISAI_CONFIG_CANDIDATES = [
    Path(os.environ.get("RYZEN_AI_INSTALLER_PATH", "")) / "voe-4.0-win_amd64" / "vaip_config.json",
    Path("C:/Program Files/RyzenAI/1.7.0/voe-4.0-win_amd64/vaip_config.json"),
    Path("C:/Program Files/AMD/RyzenAI SDK/vaip_config.json"),
    Path(__file__).parent / "models" / "npu" / "vaip_config.json",
    Path(__file__).parent.parent / "data" / "vaip_config.json",
]

# BGE-M3 ONNX (1024d) — compatible avec embeddings existants en DB
_ONNX_EMBED_MODEL_PATH = Path(__file__).parent.parent / "models" / "bge_m3_onnx" / "model.onnx"
_ONNX_EMBED_CPU_PATH = Path(__file__).parent.parent / "models" / "bge_m3_onnx" / "model.onnx"


# =============================================================================
# DÉTECTION EXECUTION PROVIDERS
# =============================================================================


class EP(str, Enum):
    """Execution Providers disponibles, par ordre de préférence."""

    NPU = "npu"  # VitisAI EP — XDNA gen1
    DIRECTML = "directml"  # DirectML EP — Radeon 780M
    CPU = "cpu"  # CPU EP — fallback universel

    def __str__(self) -> str:
        """
        Returns:
            str:
        """
        return self.value


class NPUManager:
    """
    Gestionnaire des Execution Providers ONNX pour Ryzen 8700G.
    Détecte automatiquement les capacités disponibles et crée
    les sessions ONNX avec le meilleur EP.
    """

    def __init__(self) -> None:
        """
        Initializes the NPUManager.
        """
        self._npu_available: bool = False
        self._directml_available: bool = False
        self._ort_available: bool = False
        self._vitisai_config: Path | None = None
        self._best: EP = EP.CPU
        self._checked: bool = False

    # ── Détection ─────────────────────────────────────────────────────────────

    def detect(self) -> dict[str, any]:
        """
        Détecte tous les EPs disponibles. Appelé une seule fois.

        Returns:
            dict[str, any]:
        """
        if self._checked:
            return self.status_report()

        # 1. onnxruntime de base
        try:
            import onnxruntime as ort

            self._ort_available = True
            eps = ort.get_available_providers()
            logger.info(f"[NPU] onnxruntime {ort.__version__} — EPs: {eps}")
        except ImportError:
            logger.warning("[NPU] onnxruntime non installé")
            self._checked = True
            return self.status_report()

        # 2. DirectML EP (iGPU Radeon 780M)
        if "DmlExecutionProvider" in eps:
            self._directml_available = True
            logger.info("[NPU] DirectML EP disponible (Radeon 780M)")
        else:
            # Tenter import explicite
            try:
                import onnxruntime_directml  # noqa

                self._directml_available = True
                logger.info("[NPU] onnxruntime-directml importé")
            except ImportError:
                logger.info("[NPU] DirectML absent — pip install onnxruntime-directml")

        # 3. VitisAI EP (NPU XDNA)
        # Pré-diagnostic : xrt_coreutil.dll présent = XRT partiel installé
        # Manquant pour compléter : amd_ipu.dll + onnxruntime_vitisai_ep.dll + vaip_config.json
        # Chercher les DLLs dans les emplacements connus (pas System32)
        _ryzen_bin = Path("C:/Program Files/RyzenAI/1.7.0/onnxruntime/bin")
        _ryzen_depl = Path("C:/Program Files/RyzenAI/1.7.0/deployment")
        _xrt_partial = (
            Path("C:/Program Files/RyzenAI/1.7.0/xrt/xrt_coreutil.dll").exists()
            or Path("C:/Windows/System32/xrt_coreutil.dll").exists()
        )
        _amd_ipu = (_ryzen_depl / "amd_ipu.dll").exists() or Path("C:/Windows/System32/amd_ipu.dll").exists()
        _vitisai_dll = (_ryzen_bin / "onnxruntime_vitisai_ep.dll").exists()
        # Ajouter le dossier bin au chemin DLL si present
        if _ryzen_bin.exists():
            try:
                os.add_dll_directory(str(_ryzen_bin))
            except Exception:
                pass
        if _ryzen_depl.exists():
            try:
                os.add_dll_directory(str(_ryzen_depl))
            except Exception:
                pass

        if "VitisAIExecutionProvider" in eps:
            cfg = self._find_vitisai_config()
            if cfg:
                self._npu_available = True
                self._vitisai_config = cfg
                logger.info(f"[NPU] VitisAI EP disponible — config: {cfg}")
            else:
                logger.warning("[NPU] VitisAI EP trouve mais vaip_config.json manquant")
        else:
            try:
                import onnxruntime_vitisai  # noqa

                cfg = self._find_vitisai_config()
                if cfg:
                    self._npu_available = True
                    self._vitisai_config = cfg
                    logger.info("[NPU] onnxruntime-vitisai importe")
                else:
                    logger.info("[NPU] VitisAI import OK mais vaip_config.json manquant")
            except ImportError:
                if _xrt_partial and not _amd_ipu:
                    logger.info(
                        "[NPU] XRT partiel detecte (xrt_coreutil.dll present) "
                        "mais AMD Ryzen AI SDK manquant — "
                        "amd_ipu.dll + onnxruntime_vitisai_ep.dll absents. "
                        "Installer : https://ryzenai.docs.amd.com/en/latest/inst.html"
                    )
                elif not _xrt_partial:
                    logger.info("[NPU] VitisAI absent — voir AMD Ryzen AI SDK")
                else:
                    logger.info("[NPU] VitisAI absent — SDK incomplet")

        # 4. Sélection best EP
        if self._npu_available:
            self._best = EP.NPU
        elif self._directml_available:
            self._best = EP.DIRECTML
        else:
            self._best = EP.CPU

        self._checked = True
        logger.info(f"[NPU] Best EP sélectionné : {self._best.value.upper()}")
        return self.status_report()

    def _find_vitisai_config(self) -> Path | None:
        """
        Trouve le vaip_config.json AMD dans les emplacements connus.

        Returns:
            Path | None:
        """
        for p in _VITISAI_CONFIG_CANDIDATES:
            if p.exists():
                return p
        # Chercher dans PATH/RYZEN_AI_INSTALLER_PATH
        env_path = os.environ.get("RYZEN_AI_INSTALLER_PATH", "")
        if env_path:
            for f in Path(env_path).rglob("vaip_config.json"):
                return f
        return None

    # ── Session ONNX ──────────────────────────────────────────────────────────

    def create_session(
        self, model_path: str | Path, ep: EP | None = None, inter_op_threads: int = 1, intra_op_threads: int = 4
    ) -> any:
        """
        Crée une InferenceSession ONNX avec le meilleur EP disponible.
        Cascade automatique si l'EP cible échoue.

        Args:
            model_path (str | Path):
            ep (EP | None, optional):
            inter_op_threads (int, optional):
            intra_op_threads (int, optional):

        Returns:
            any:
        """
        if not self._checked:
            self.detect()

        try:
            import onnxruntime as ort
        except ImportError:
            logger.error("[NPU] onnxruntime non disponible")
            return None

        target = ep or self._best
        cascade = [target] + [e for e in EP if e != target]

        for attempt_ep in cascade:
            sess = self._try_create_session(ort, str(model_path), attempt_ep, inter_op_threads, intra_op_threads)
            if sess is not None:
                if attempt_ep != target:
                    logger.warning(f"[NPU] Fallback {target.value} → {attempt_ep.value}")
                else:
                    logger.info(f"[NPU] Session OK [{attempt_ep.value.upper()}] {Path(model_path).name}")
                return sess

        logger.error(f"[NPU] Impossible de créer une session pour {model_path}")
        return None

    def _try_create_session(self, ort, model_path: str, ep: EP, inter_op: int, intra_op: int) -> any:
        """
        Tente de créer une session avec un EP spécifique.

        Args:
            ort:
            model_path (str):
            ep (EP):
            inter_op (int):
            intra_op (int):

        Returns:
            any:
        """
        try:
            opts = ort.SessionOptions()
            opts.inter_op_num_threads = inter_op
            opts.intra_op_num_threads = intra_op
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

            if ep == EP.NPU and self._npu_available and self._vitisai_config:
                # VitisAI EP — config JSON requis par AMD
                providers = [
                    (
                        "VitisAIExecutionProvider",
                        {
                            "config_file": str(self._vitisai_config),
                        },
                    ),
                    "CPUExecutionProvider",
                ]
                return ort.InferenceSession(model_path, sess_options=opts, providers=providers)

            elif ep == EP.DIRECTML and self._directml_available:
                # DirectML EP — device_id 0 = première iGPU/GPU
                providers = [
                    ("DmlExecutionProvider", {"device_id": 0}),
                    "CPUExecutionProvider",
                ]
                return ort.InferenceSession(model_path, sess_options=opts, providers=providers)

            else:
                # CPU EP — toujours disponible
                opts.intra_op_num_threads = max(intra_op, 4)
                return ort.InferenceSession(model_path, sess_options=opts, providers=["CPUExecutionProvider"])

        except Exception as e:
            logger.debug(f"[NPU] {ep.value} session failed: {e}")
            return None

    # ── Export modèle ONNX ────────────────────────────────────────────────────

    def export_minilm_to_onnx(self, output_dir: Path | None = None, quantize: bool = True) -> Path | None:
        """
        Exporte all-MiniLM-L6-v2 en ONNX (int8 si quantize=True).
        Requis pour utiliser DirectML ou NPU (sentence-transformers utilise PyTorch).

        Args:
            output_dir (Path | None, optional):
            quantize (bool, optional):

        Returns:
            Path | None:
        """
        out = output_dir or Path(__file__).parent / "models" / ("npu" if quantize else "cpu")
        out.mkdir(parents=True, exist_ok=True)
        target = out / ("minilm_int8.onnx" if quantize else "minilm.onnx")

        if target.exists():
            logger.info(f"[NPU] MiniLM ONNX déjà présent : {target}")
            return target

        logger.info(f"[NPU] Export MiniLM → ONNX {'int8' if quantize else 'fp32'}…")
        t0 = time.monotonic()

        try:
            # torch.onnx.export — méthode directe (onnxscript requis, dispo)
            # optimum retiré : incompatible avec onnxruntime-directml
            from sentence_transformers import SentenceTransformer
            import torch

            logger.info("[NPU] Chargement MiniLM pour export…")
            model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
            transformer = model[0].auto_model
            tokenizer = model.tokenizer

            enc = tokenizer(
                "analyse de code Python",
                return_tensors="pt",
                padding="max_length",
                max_length=128,
                truncation=True,
            )

            fp32_path = out / "minilm_fp32.onnx"

            # Wrapper qui n'expose que input_ids + attention_mask
            # (token_type_ids ignoré — MiniLM ne l'utilise pas)
            class _Wrapper(torch.nn.Module):
                def __init__(self, m) -> None:
                    """
                    Initializes the _Wrapper.

                    Args:
                        m:
                    """
                    super().__init__()
                    self.m = m

                def forward(self, input_ids, attention_mask) -> object:
                    """
                    Args:
                        input_ids:
                        attention_mask:

                    Returns:
                        object:
                    """
                    return self.m(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state

            wrapper = _Wrapper(transformer)
            wrapper.eval()

            with torch.no_grad():
                torch.onnx.export(
                    wrapper,
                    (enc["input_ids"], enc["attention_mask"]),
                    str(fp32_path),
                    input_names=["input_ids", "attention_mask"],
                    output_names=["last_hidden_state"],
                    dynamic_axes={
                        "input_ids": {0: "batch", 1: "seq_len"},
                        "attention_mask": {0: "batch", 1: "seq_len"},
                        "last_hidden_state": {0: "batch", 1: "seq_len"},
                    },
                    opset_version=18,
                    do_constant_folding=True,
                )
            logger.info(f"[NPU] Export torch.onnx fp32 OK : {fp32_path}")

            # Quantification int8 dynamique
            if quantize and fp32_path.exists():
                try:
                    from onnxruntime.quantization import quantize_dynamic, QuantType

                    quantize_dynamic(
                        str(fp32_path),
                        str(target),
                        weight_type=QuantType.QInt8,
                    )
                    fp32_path.unlink(missing_ok=True)
                    logger.info(f"[NPU] Quantification int8 OK : {target}")
                except Exception as eq:
                    logger.warning(f"[NPU] Quantification échouée ({eq}) — fp32 conservé")
                    fp32_path.rename(target)
            elif fp32_path.exists():
                fp32_path.rename(target)

            logger.info(f"[NPU] MiniLM exporté en {time.monotonic() - t0:.1f}s -> {target}")
            return target

        except ImportError as e:
            logger.error(f"[NPU] Export impossible ({e})")
            return None
        except Exception as e:
            logger.error(f"[NPU] Export échoué : {e}")
            return None

    # ── Status ────────────────────────────────────────────────────────────────

    def best_ep(self) -> EP:
        """
        Returns:
            EP:
        """
        if not self._checked:
            self.detect()
        return self._best

    def status_report(self) -> dict[str, any]:
        """
        Returns:
            dict[str, any]:
        """
        return {
            "best_ep": self._best.value,
            "npu": self._npu_available,
            "directml": self._directml_available,
            "cpu": self._ort_available,
            "vitisai_config": str(self._vitisai_config) if self._vitisai_config else None,
        }

    def status_str(self) -> str:
        """
        Résumé lisible pour le TUI.

        Returns:
            str:
        """
        if not self._checked:
            self.detect()
        lines = []
        if self._npu_available:
            lines.append(
                f"[NPU] XDNA gen1 VitisAI EP OK (config: {self._vitisai_config.name if self._vitisai_config else '?'})"
            )
        else:
            xrt = (
                Path("C:/Program Files/RyzenAI/1.7.0/xrt/xrt_coreutil.dll").exists()
                or Path("C:/Windows/System32/xrt_coreutil.dll").exists()
            )
            ipu = (
                Path("C:/Program Files/RyzenAI/1.7.0/deployment/amd_ipu.dll").exists()
                or Path("C:/Windows/System32/amd_ipu.dll").exists()
            )
            if xrt and not ipu:
                lines.append("[NPU] XRT partiel present — AMD Ryzen AI SDK requis (amd_ipu.dll manquant)")
                lines.append("[NPU]   => https://ryzenai.docs.amd.com/en/latest/inst.html")
            else:
                lines.append("[NPU] XDNA absent — AMD Ryzen AI SDK requis")
        if self._directml_available:
            lines.append("[DML] Radeon 780M DirectML EP OK")
        else:
            lines.append("[DML] DirectML absent — pip install onnxruntime-directml")
        lines.append("[CPU] Zen4 fallback OK")
        lines.append(f" => Best EP actif : {self._best.value.upper()}")
        return "\n".join(lines)


# =============================================================================
# EMBEDDER ONNX (remplace sentence-transformers sur NPU/DirectML)
# =============================================================================


class OnnxEmbedderNPU:
    """
    Embedder MiniLM tournant via ONNX Runtime avec EP NPU/DirectML/CPU.
    Interface identique à Embedder (sentence-transformers) dans brain_worker.py.
    Requis : export MiniLM en ONNX via NPUManager.export_minilm_to_onnx()
    """

    def __init__(self, npu: NPUManager) -> None:
        """
        Initializes the OnnxEmbedderNPU.

        Args:
            npu (NPUManager):
        """
        self._npu = npu
        self._session = None
        self._tok = None
        self._ready = False
        self._dim = 1024
        self._ep = EP.CPU
        self._lock = __import__("threading").Lock()

    def load(self) -> bool:
        """
        Returns:
            bool:
        """
        if self._ready:
            return True

        # 1. Vérifier/exporter le modèle ONNX
        model_path = _ONNX_EMBED_MODEL_PATH
        if not model_path.exists():
            logger.info("[OnnxEmbedderNPU] Modèle absent — export en cours…")
            exported = self._npu.export_minilm_to_onnx(quantize=True)
            if exported is None:
                # Fallback fp32 CPU
                exported = self._npu.export_minilm_to_onnx(
                    output_dir=Path(__file__).parent / "models" / "cpu", quantize=False
                )
            if exported is None:
                logger.warning("[OnnxEmbedderNPU] Export échoué — fallback sentence-transformers")
                return False
            model_path = exported

        # 2. Créer la session ONNX avec le meilleur EP
        try:
            self._session = self._npu.create_session(model_path)
            if self._session is None:
                return False
            self._ep = self._npu.best_ep()

            # Déduire dim réel depuis le modèle (évite hardcode 384 vs 1024)
            out_shape = self._session.get_outputs()[0].shape
            self._dim = int(out_shape[-1]) if out_shape and out_shape[-1] else 1024

            # 3. Charger le tokenizer (local d'abord, HuggingFace fallback)
            from transformers import AutoTokenizer

            _tok_dir = _ONNX_EMBED_MODEL_PATH.parent
            if (_tok_dir / "tokenizer.json").exists():
                self._tok = AutoTokenizer.from_pretrained(str(_tok_dir), use_fast=True)
            else:
                self._tok = AutoTokenizer.from_pretrained("microsoft/MiniLM-L12-H384-uncased", use_fast=True)
            self._ready = True
            logger.info(f"[OnnxEmbedderNPU] OK [{self._ep.value.upper()}] dim={self._dim}")
            return True
        except Exception as e:
            logger.error(f"[OnnxEmbedderNPU] load échoué : {e}")
            return False

    def encode(self, texts: list[str]) -> list[list[float]]:
        """
        Args:
            texts (list[str]):

        Returns:
            list[list[float]]:
        """
        if not self._ready or not texts:
            return []
        import numpy as np

        with self._lock:
            try:
                enc = self._tok(
                    texts,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="np",
                )
                outputs = self._session.run(
                    None,
                    {
                        "input_ids": enc["input_ids"].astype(np.int64),
                        "attention_mask": enc["attention_mask"].astype(np.int64),
                    },
                )
                # BGE-M3 dense = pooling CLS (token 0), PAS mean pooling.
                # Bug historique : encode() a garde le mean-pooling de l'ere
                # MiniLM apres le swap MiniLM->bge-m3 (le path a ete mis a
                # jour, pas le pooling) -> vecteurs hors espace canonique
                # bge-m3 (cosine ~0.77 vs bge-m3 standard / cloud).
                hidden = outputs[0]  # (batch, seq, dim)
                pooled = hidden[:, 0]  # token [CLS]

                # Normalisation L2
                norms = np.linalg.norm(pooled, axis=1, keepdims=True)
                normed = pooled / np.maximum(norms, 1e-9)

                return normed.tolist()
            except Exception as e:
                logger.error(f"[OnnxEmbedderNPU] encode : {e}")
                return []

    @property
    def ready(self) -> bool:
        """
        Returns:
            bool:
        """
        return self._ready

    @property
    def dim(self) -> int:
        """
        Returns:
            int:
        """
        return self._dim

    @property
    def ep(self) -> str:
        """
        Returns:
            str:
        """
        return self._ep.value


# =============================================================================
# SINGLETON GLOBAL
# =============================================================================

_npu_manager: NPUManager | None = None


def get_npu_manager() -> NPUManager:
    """
    Returns:
        NPUManager:
    """
    global _npu_manager
    if _npu_manager is None:
        _npu_manager = NPUManager()
        _npu_manager.detect()
    return _npu_manager


# =============================================================================
# INSTALL GUIDE — affiché si NPU absent
# =============================================================================

INSTALL_GUIDE = """
=== Activer le NPU AMD XDNA (Ryzen 7 8700G) pour La Forge ===

ETAPE 1 — DirectML (iGPU Radeon 780M) — DISPONIBLE MAINTENANT :
  pip install onnxruntime-directml
  => Remplace onnxruntime CPU (incompatible, désinstaller d'abord)
  pip uninstall onnxruntime
  pip install onnxruntime-directml

ETAPE 2 — NPU XDNA complet :
  1. Installer AMD Ryzen AI Software :
     https://ryzenai.docs.amd.com/en/latest/inst.html
  2. Télécharger + installer le package (inclut VitisAI EP + vaip_config.json)
  3. pip install ryzenai-onnxruntime  (ou via le SDK AMD)
  4. Ajouter RYZEN_AI_INSTALLER_PATH dans Nokido.env :
     RYZEN_AI_INSTALLER_PATH=C:/AMD/RyzenAI-1.x.x/

MODELE CODE (optionnel — meilleure qualité) :
  huggingface-cli download microsoft/codebert-base-onnx --local-dir ./models/npu/
"""

__all__ = [
    "EP",
    "NPUManager",
    "OnnxEmbedderNPU",
    "get_npu_manager",
    "INSTALL_GUIDE",
]


# ── XDNA_FORCED_PROBE_V1 ─────────────────────────────────────────────────────
VAIP_CONFIG = str(Path("C:/Program Files/RyzenAI/1.7.0/voe-4.0-win_amd64/vaip_config.json"))
VITIS_CACHE = str(Path(__file__).parent.parent / ".cache" / "vitis_cache")

# Options Phoenix (8700G XDNA gen1) — target X1 ou RyzenAI_llm_phi3
VITIS_OPTIONS_PHX = {
    "config_file": VAIP_CONFIG,
    "cacheDir": VITIS_CACHE,
    "cacheKey": "nokido_npu_v1",
}


def check_npu_availability(verbose: bool = True) -> dict[str, str]:
    """
    XDNA_FORCED_PROBE_V1 — test d'instanciation reelle VitisAI EP.
    Ne se contente pas de verifier la presence du provider.
    Retourne {"available": bool, "provider": str, "error": str}.

    Args:
        verbose (bool, optional):

    Returns:
        dict[str, str]:
    """
    import onnxruntime as ort

    providers = ort.get_available_providers()
    result = {"available": False, "provider": "none", "error": ""}

    if "VitisAIExecutionProvider" not in providers:
        result["error"] = "VitisAI EP absent — verif install VOE 1.7.0"
        if verbose:
            print(f"[NPU] {result['error']}")
        return result

    # Test session reelle sur un modele ONNX minimal
    try:
        # Chercher un modele ONNX existant pour le test
        test_models = [
            Path(__file__).parent.parent / "app" / "models" / "npu" / "minilm_base.onnx",
            Path(__file__).parent.parent / "app" / "models" / "npu" / "minilm_int8.onnx",
        ]
        test_model = next((str(m) for m in test_models if m.exists()), None)
        if not test_model:
            result["error"] = "Aucun modele ONNX de test disponible"
            if verbose:
                print(f"[NPU] {result['error']}")
            return result

        Path(VITIS_CACHE).mkdir(parents=True, exist_ok=True)
        sess = ort.InferenceSession(
            test_model,
            providers=["VitisAIExecutionProvider", "CPUExecutionProvider"],
            provider_options=[VITIS_OPTIONS_PHX, {}],
        )
        result["available"] = True
        result["provider"] = "VitisAIExecutionProvider"
        if verbose:
            print(f"[NPU] VitisAI XDNA Phoenix ACTIF — {Path(test_model).name}")
    except Exception as e:
        result["error"] = str(e)[:200]
        if verbose:
            print(f"[NPU] VitisAI inactif: {result['error'][:100]}")
        if verbose:
            print("[NPU] Fallback DirectML disponible")
    return result
