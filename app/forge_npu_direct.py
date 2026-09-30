"""forge_npu_direct.py — Wrapper direct ONNX VitisAI NPU (sans brain_worker ZMQ).

Usage:
  Doit tourner dans env ryzen-ai-1.7.0 (Python avec onnxruntime-vitisai 1.23.2).
  PATH: <user-home>/miniforge3/envs/ryzen-ai-1.7.0/python.exe

API:
  encode(texts: list[str]) -> list[list[float]]
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import List

os.environ.setdefault("XLNX_VART_FIRMWARE", r"C:\Windows\System32\AMD\1x4_3.5.0.0-2044_ipu_2.xclbin")
os.environ.setdefault("XLNX_TARGET_NAME", "AMD_AIE2_Nx4_Overlay")

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "app" / "models" / "npu" / "minilm_int8.onnx"
CACHE = ROOT / ".cache" / "vitis_cache"

_session = None
_tokenizer = None


def _init():
    global _session, _tokenizer
    if _session is not None:
        return
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    providers = [
        (
            "VitisAIExecutionProvider",
            {
                "cache_dir": str(CACHE),
                "cache_key": "minilm_l12",
                "config_file": r"C:\Program Files\RyzenAI\1.7.0\voe-4.0-win_amd64\vaip_config.json",
            },
        ),
        "DmlExecutionProvider",
        "CPUExecutionProvider",
    ]
    _session = ort.InferenceSession(str(MODEL), sess_options=so, providers=providers)
    print(f"[NPU] Active providers: {_session.get_providers()}")
    # Tokenizer Hugging Face
    from transformers import AutoTokenizer

    _tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L12-v2")


def encode(texts: List[str]) -> List[List[float]]:
    """Encode batch via NPU XDNA."""
    _init()
    enc = _tokenizer(texts, padding=True, truncation=True, max_length=128, return_tensors="np")
    out = _session.run(
        None,
        {
            "input_ids": enc["input_ids"].astype("int64"),
            "attention_mask": enc["attention_mask"].astype("int64"),
        },
    )
    # Mean pooling masqué
    import numpy as np

    last_hidden = out[0]  # (batch, seq, hidden)
    mask = enc["attention_mask"][:, :, None].astype(np.float32)
    summed = (last_hidden * mask).sum(axis=1)
    counts = mask.sum(axis=1).clip(min=1e-9)
    pooled = summed / counts
    # L2 normalize
    norms = np.linalg.norm(pooled, axis=1, keepdims=True).clip(min=1e-9)
    normed = pooled / norms
    return normed.tolist()


if __name__ == "__main__":
    import sys, time, json

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) > 1 and sys.argv[1] == "--bench":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        # Warmup (init compile + chauffe session)
        t_warm = time.monotonic()
        encode(["warmup"])
        warm_ms = (time.monotonic() - t_warm) * 1000
        print(f"warmup: {warm_ms:.0f}ms (compile graph + first inference)")
        # Vraie mesure post-warmup
        texts = [f"Nokido NPU embedding bench iter {i}" for i in range(n)]
        t0 = time.monotonic()
        v = encode(texts)
        dt = time.monotonic() - t0
        print(f"NPU bench post-warmup: {n} embeds en {dt * 1000:.0f}ms = {n / dt:.1f} eps  dim={len(v[0])}")
        # Re-bench batch unique
        t1 = time.monotonic()
        encode(texts)
        dt1 = time.monotonic() - t1
        print(f"NPU bench second pass: {n} embeds en {dt1 * 1000:.0f}ms = {n / dt1:.1f} eps")
    elif len(sys.argv) > 1 and sys.argv[1] == "--encode":
        v = encode([sys.argv[2]])[0]
        print(f"dim={len(v)} preview={v[:5]}")
    else:
        # JSON stdin -> JSON stdout (pour subprocess bridge)
        req = json.load(sys.stdin)
        v = encode(req["texts"])
        json.dump({"embeddings": v, "dim": len(v[0]) if v else 0}, sys.stdout)
