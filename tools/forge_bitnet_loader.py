"""
forge_bitnet_loader.py — Détecteur de modèles BitNet ternaire (1.58-bit) locaux.

Phase 13 (2026-05-24). BitNet (Microsoft 2024) = LLM avec poids contraints
a 3 valeurs ({-1, 0, 1}). Resultat :
  - multiplication matricielle => additions/soustractions/no-op
  - RAM /5 vs FP16, /2 vs Q4_K_M
  - Latence inference x2-4 sur CPU pur (pas besoin GPU)

Cible APU Ryzen 7840U avec iGPU Radeon 780M : permet d'offload llama-server
depuis GPU vers CPU sans perte de throughput, libere VRAM pour autres tasks.

Ce module ne TELECHARGE PAS le modele (10-30 GB selon variante).
Il scan ROOT/data/llm_models/ pour fichiers bitnet*.gguf et expose
suggested_llama_args() compatible llama.cpp.

Tested with :
  - microsoft/bitnet-b1.58-2B-4T (GGUF via HuggingFace)
  - 1bitLLM/bitnet_b1_58-3B-q4_K_M.gguf (community fork)

Pour telecharger :
    cd LaForge/data/llm_models
    huggingface-cli download microsoft/bitnet-b1.58-2B-4T --local-dir .

Pour exposer comme service supervisor :
    1. Verifier "python tools/forge_bitnet_loader.py" retourne un model
    2. Activer entry NokidoLlamaBitnet dans services.toml (disabled=false)
    3. nssm restart LaForge-Master (admin)
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("forge_bitnet_loader")

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "data" / "llm_models"

BITNET_FILE_GLOBS = [
    "bitnet*.gguf",
    "Bitnet*.gguf",
    "BitNet*.gguf",
    "*bitnet*1.58*.gguf",
    "*1bit*1.58*.gguf",
]


def detect_bitnet_models() -> list[dict[str, Any]]:
    """Retourne la liste des GGUF BitNet trouves sous data/llm_models/."""
    if not MODEL_DIR.is_dir():
        return []
    seen: set[Path] = set()
    out: list[dict[str, Any]] = []
    for pattern in BITNET_FILE_GLOBS:
        for f in MODEL_DIR.glob(pattern):
            if f in seen or not f.is_file():
                continue
            seen.add(f)
            sz = f.stat().st_size
            out.append(
                {
                    "name": f.name,
                    "path": str(f),
                    "size_mb": round(sz / 1024 / 1024, 1),
                    "size_gb": round(sz / 1024 / 1024 / 1024, 2),
                }
            )
    out.sort(key=lambda d: d["size_mb"])
    return out


def suggested_llama_args(model_path: str, port: int = 8093, context: int = 8192) -> list[str]:
    """Args llama-server suggested pour BitNet (CPU-only, pas de GPU).

    Note : --n-gpu-layers 0 (CPU-only) — BitNet n'a pas besoin de GPU et
    sature un iGPU rapidement. Le gain RAM est cote CPU.
    Threads = -1 (auto-detect cores).
    """
    return [
        "-m",
        model_path,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "-c",
        str(context),
        "-ngl",
        "0",  # CPU-only — BitNet n'utilise pas GPU
        "-b",
        "512",
        "--threads",
        "-1",
        "--metrics",
        "--slots",
        "--no-mmap",  # BitNet benefice de full RAM load (pas mmap)
        "-a",
        "bitnet,bitnet-coder",
    ]


def summary() -> dict[str, Any]:
    models = detect_bitnet_models()
    return {
        "model_dir": str(MODEL_DIR),
        "model_dir_exists": MODEL_DIR.is_dir(),
        "bitnet_models_found": len(models),
        "models": models,
        "ready_for_supervisor": len(models) > 0,
        "instructions_if_empty": (
            "cd LaForge/data/llm_models && "
            "huggingface-cli download microsoft/bitnet-b1.58-2B-4T --local-dir ."
        ),
    }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "args":
        models = detect_bitnet_models()
        if not models:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "no bitnet model found",
                        "instructions": summary()["instructions_if_empty"],
                    }
                )
            )
            sys.exit(2)
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8093
        print(json.dumps(suggested_llama_args(models[0]["path"], port=port)))
    else:
        print(json.dumps(summary(), indent=2))
