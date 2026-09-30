"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_163726_astdoccerb
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0 docs
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"

"""
forge_hw.py — Lecture hardware.json (Ring 0, zéro import lourd)
================================================================
RÈGLE ABSOLUE : ce module ne fait JAMAIS de detect_hardware() directement.
Il lit uniquement sandbox/hardware.json écrit par hardware_monitor.py au boot.

Usage :
    from forge_hw import hw
    if hw("llama_cpp_vulkan"):
        n_gpu = hw("llamacpp_n_gpu_layers")
"""

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_HWFILE = _ROOT / "sandbox" / "hardware.json"

_CACHE: dict | None = None

# Valeurs par défaut si hardware.json absent (boot froid)
_DEFAULTS = {
    "recommended_ep": "CPU",
    "onnxruntime_version": None,
    "gpu_directml": False,
    "npu_vitisai": False,
    "vulkan_available": False,
    "llama_cpp_version": None,
    "llama_cpp_vulkan": False,
    "llamacpp_n_gpu_layers": 0,
    "ram_total_gb": None,
    "ram_avail_gb": None,
    "warnings": [],
}


def _load() -> dict:
    """load."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        _CACHE = json.loads(_HWFILE.read_text(encoding="utf-8"))
    except Exception:
        _CACHE = dict(_DEFAULTS)
    return _CACHE


def hw(key: str, default: Any = None) -> Any:
    """Lit une clé de hardware.json. Ne lance jamais de scan."""
    data = _load()
    return data.get(key, _DEFAULTS.get(key, default))


def hw_all() -> dict:
    """Retourne tout hardware.json."""
    return dict(_load())


def hw_ready() -> bool:
    """True si hardware.json existe et a été généré."""
    return _HWFILE.exists()


def hw_summary() -> str:
    """Résumé lisible pour les logs."""
    d = _load()
    return (
        f"EP={d.get('recommended_ep', '?')} "
        f"vulkan={d.get('llama_cpp_vulkan', False)} "
        f"dml={d.get('gpu_directml', False)} "
        f"npu={d.get('npu_vitisai', False)} "
        f"ram={d.get('ram_avail_gb', '?')}GB libre"
    )
