from __future__ import annotations
from logging.handlers import RotatingFileHandler

"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_hardware_monitor
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
hardware_monitor.py — Service monitoring hardware Nokido (one-shot au boot)
=============================================================================
Lance UNE SEULE FOIS au démarrage. Détecte le hardware, écrit sandbox/hardware.json,
puis dort en attendant un signal d'arrêt.

Règle : PAS de scan hardware en boucle. PAS de subprocess répété.
Tout le code Nokido lit sandbox/hardware.json — jamais detect_hardware() directement.

NSSM config :
  nssm install NokidoHardware __import__("os").path.expanduser("~/miniforge3/python.exe")
  nssm set NokidoHardware AppParameters "-u app/hardware_monitor.py"
  nssm set NokidoHardware AppDirectory __import__("os").path.expanduser("~/Script python IA/LaForge")
  nssm set NokidoHardware Start SERVICE_DEMAND_START
  nssm set NokidoHardware AppExit 0 Exit
  nssm set NokidoHardware AppRestartDelay 86400000
"""

import json, logging, os, platform, signal, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HWFILE = ROOT / "sandbox" / "hardware.json"
LOGFILE = ROOT / "sandbox" / "hardware.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] hardware — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(LOGFILE, encoding="utf-8", maxBytes=10485760, backupCount=5),
    ],
)
logger = logging.getLogger("hardware")


def detect() -> dict:
    """
    Détecte le hardware une seule fois.
    Retourne un dict stable écrit dans sandbox/hardware.json.
    """
    result: dict = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 1,
        "recommended_ep": "CPU",
        "onnxruntime_version": None,
        "gpu_directml": False,
        "npu_vitisai": False,
        "vulkan_available": False,
        "llama_cpp_version": None,
        "llama_cpp_vulkan": False,
        "llamacpp_n_gpu_layers": -1,
        "warnings": [],
    }

    # ── onnxruntime ───────────────────────────────────────────────────────
    try:
        import onnxruntime as ort

        result["onnxruntime_version"] = ort.__version__
        providers = ort.get_available_providers()
        if "DmlExecutionProvider" in providers:
            result["gpu_directml"] = True
            result["recommended_ep"] = "DirectML"
        if "VitisAIExecutionProvider" in providers:
            result["npu_vitisai"] = True
            result["recommended_ep"] = "VitisAI"
    except ImportError:
        result["warnings"].append("onnxruntime non installé")
    except Exception as e:
        result["warnings"].append(f"onnxruntime erreur: {e}")

    # ── llama_cpp ─────────────────────────────────────────────────────────
    try:
        import llama_cpp

        result["llama_cpp_version"] = getattr(llama_cpp, "__version__", "unknown")
        # Vérifier ggml-vulkan.dll
        sp = Path(llama_cpp.__file__).parent
        vulkan_dll = sp / "lib" / "ggml-vulkan.dll"
        if not vulkan_dll.exists():
            vulkan_dll = sp / "ggml-vulkan.dll"
        result["llama_cpp_vulkan"] = vulkan_dll.exists()
        if result["llama_cpp_vulkan"]:
            result["vulkan_available"] = True
            result["llamacpp_n_gpu_layers"] = -1
            result["recommended_ep"] = "Vulkan"
    except ImportError:
        result["warnings"].append("llama_cpp non installé")
    except Exception as e:
        result["warnings"].append(f"llama_cpp erreur: {e}")

    # ── RAM ───────────────────────────────────────────────────────────────
    try:
        import psutil

        mem = psutil.virtual_memory()
        result["ram_total_gb"] = round(mem.total / 1024**3, 1)
        result["ram_avail_gb"] = round(mem.available / 1024**3, 1)
    except Exception:
        pass

    return result


def main() -> None:
    """Main."""
    logger.info("=== Hardware Monitor démarrage (one-shot) ===")

    hw = detect()

    HWFILE.parent.mkdir(parents=True, exist_ok=True)
    HWFILE.write_text(json.dumps(hw, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(f"EP recommandé    : {hw['recommended_ep']}")
    logger.info(f"llama_cpp        : {hw['llama_cpp_version']} vulkan={hw['llama_cpp_vulkan']}")
    logger.info(f"onnxruntime      : {hw['onnxruntime_version']} dml={hw['gpu_directml']}")
    logger.info(f"RAM              : {hw.get('ram_total_gb', '?')}GB total / {hw.get('ram_avail_gb', '?')}GB dispo")
    if hw["warnings"]:
        for w in hw["warnings"]:
            logger.warning(f"  {w}")

    logger.info(f"hardware.json écrit → {HWFILE}")
    logger.info("Détection terminée — service en attente d'arrêt (NSSM AppExit=0=Exit)")

    # Attente passive — NSSM verra exit code 0 et ne relancera pas (AppExit 0 Exit)
    # Si lancé manuellement, Ctrl+C pour quitter
    def _stop(sig, frame) -> None:
        """Stop.

        Args:
            sig: Description.
            frame: Description.
        """
        logger.info("Signal reçu — arrêt")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    sys.exit(0)


if __name__ == "__main__":
    main()
