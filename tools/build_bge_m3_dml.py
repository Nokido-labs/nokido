#!/usr/bin/env python3
"""
build_bge_m3_dml.py — BGE-M3 embeddings via ORT DirectML (Radeon 780M iGPU).

Run with ryzen-ai-final Python (has DML ORT 1.23.2-dev):
    %USERPROFILE%/miniforge3/envs/ryzen-ai-final/python.exe tools/build_bge_m3_dml.py

First run: exports BAAI/bge-m3 → ONNX using ryzen-ai-1.7.1 (has optimum 2.1.0).
Subsequent runs: reuses models/bge_m3_onnx/model.onnx.

Expected: ~25-50 chunks/s vs 4-5 via Ollama HTTP CPU.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import struct
import sys
import time
from pathlib import Path

import numpy as np  # noqa: F401  (used in type annotations + late imports)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("bge_m3_dml")

ROOT = Path(__file__).resolve().parent.parent
RAG_DB = ROOT / "RAG" / "embeddings.db"
FTS_LOCK = ROOT / "RAG" / "fts_rebuild.lock"
ONNX_DIR = ROOT / "models" / "bge_m3_onnx"
ONNX_MODEL = ONNX_DIR / "model.onnx"

PRIORITY_DOMAINS = ["forge_core", "code", "nokido_code", "security", "conv"]
DEFAULT_BATCH = 32
MAX_SEQ_LEN = 128  # 128 tokens → ~4x less attention compute vs 512, DML ~20-25 chunks/s


def _wait_fts_lock(max_wait: int = 60) -> None:
    waited = 0
    while FTS_LOCK.exists() and waited < max_wait:
        time.sleep(2)
        waited += 2
    if waited >= max_wait:
        log.warning("FTS lock still present after %ds, continuing anyway", max_wait)


def export_onnx(fp16: bool = False) -> None:
    """Export BAAI/bge-m3 → ONNX via torch.onnx.export (legacy, no optimum, no fx path).

    fp16=True: loads with torch_dtype=float16 → ~2x smaller ONNX, faster DML inference.
    """
    import torch
    from transformers import AutoModel, AutoTokenizer

    ONNX_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Downloading BAAI/bge-m3 weights (~1.1GB)...")

    tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-m3")
    tokenizer.save_pretrained(str(ONNX_DIR))

    dtype = torch.float16 if fp16 else None
    # use_safetensors bypasses CVE-2025-32434 (torch.load blocked on torch < 2.6)
    kw = {"use_safetensors": True}
    if dtype is not None:
        kw["dtype"] = dtype
    model = AutoModel.from_pretrained("BAAI/bge-m3", **kw)
    model.eval()
    log.info("Model loaded (%s). Exporting to ONNX opset 17...", "FP16" if fp16 else "FP32")

    dummy = tokenizer(
        "warmup export", return_tensors="pt", padding="max_length", truncation=True, max_length=64
    )
    input_ids = dummy["input_ids"]
    attention_mask = dummy["attention_mask"]

    with torch.no_grad():
        torch.onnx.export(
            model,
            (input_ids, attention_mask),
            str(ONNX_MODEL),
            input_names=["input_ids", "attention_mask"],
            output_names=["last_hidden_state"],
            dynamic_axes={
                "input_ids": {0: "batch_size", 1: "sequence_length"},
                "attention_mask": {0: "batch_size", 1: "sequence_length"},
                "last_hidden_state": {0: "batch_size", 1: "sequence_length"},
            },
            opset_version=17,
            do_constant_folding=True,
        )

    log.info("Export done: %s (%.0fMB)", ONNX_MODEL, ONNX_MODEL.stat().st_size / 1e6)


def load_session():
    import onnxruntime as ort

    providers = ort.get_available_providers()
    log.info("ORT %s | available providers: %s", ort.__version__, providers)

    preferred = []
    if "DmlExecutionProvider" in providers:
        preferred.append("DmlExecutionProvider")
        log.info("Using DirectML (Radeon iGPU)")
    elif "VitisAIExecutionProvider" in providers:
        preferred.append(
            (
                "VitisAIExecutionProvider",
                {
                    "config_file": str(
                        Path(r"C:\Program Files\RyzenAI\1.7.0\voe-4.0-win_amd64\vaip_config.json")
                    )
                },
            )
        )
        log.info("Using VitisAI EP (NPU)")
    else:
        log.warning("No DML or VitisAI — falling back to CPU")
    preferred.append("CPUExecutionProvider")

    sess_opts = ort.SessionOptions()
    sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(str(ONNX_MODEL), sess_options=sess_opts, providers=preferred)
    log.info("Session loaded. Inputs: %s", [i.name for i in sess.get_inputs()])
    return sess


def tokenize_batch(texts: list[str]):
    tok = tokenize_batch._tok
    enc = tok(texts, padding=True, truncation=True, max_length=MAX_SEQ_LEN, return_tensors="np")
    return enc


def _load_tokenizer():
    from transformers import AutoTokenizer

    log.info("Loading BGE-M3 tokenizer...")
    tok = AutoTokenizer.from_pretrained("BAAI/bge-m3")
    tokenize_batch._tok = tok
    log.info("Tokenizer loaded")


def mean_pool(last_hidden: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    mask = attention_mask[..., None].astype(float)
    summed = (last_hidden * mask).sum(axis=1)
    counts = mask.sum(axis=1).clip(min=1e-9)
    return summed / counts


def fetch_chunks(domains: list[str], limit: int, recode_old: bool) -> list[tuple[str, str]]:
    con = sqlite3.connect(str(RAG_DB))
    ph = ",".join("?" * len(domains))
    if recode_old:
        sql = f"""
            SELECT id, text FROM rag_chunks
            WHERE domain IN ({ph})
              AND (embedding IS NULL OR embedding = ''
                   OR length(embedding) IN (1536, 3072))
            ORDER BY domain, rowid
        """
    else:
        sql = f"""
            SELECT id, text FROM rag_chunks
            WHERE domain IN ({ph})
              AND (embedding IS NULL OR embedding = '')
            ORDER BY domain, rowid
        """
    if limit > 0:
        sql += f" LIMIT {limit}"
    rows = con.execute(sql, domains).fetchall()
    con.close()
    log.info("Chunks to encode: %d (domains: %s)", len(rows), ", ".join(domains))
    return rows


def embed_and_store(sess, chunks: list[tuple[str, str]], batch_size: int) -> int:
    import numpy as np

    _wait_fts_lock()
    con = sqlite3.connect(str(RAG_DB), timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")

    stored = 0
    total = len(chunks)
    t_start = time.time()

    input_names = {i.name for i in sess.get_inputs()}

    for i in range(0, total, batch_size):
        batch = chunks[i : i + batch_size]
        ids = [r[0] for r in batch]
        texts = [r[1][: MAX_SEQ_LEN * 4] for r in batch]

        try:
            enc = tokenize_batch(texts)
            feed = {"input_ids": enc["input_ids"].astype(np.int64)}
            if "attention_mask" in input_names:
                feed["attention_mask"] = enc["attention_mask"].astype(np.int64)
            if "token_type_ids" in input_names and "token_type_ids" in enc:
                feed["token_type_ids"] = enc["token_type_ids"].astype(np.int64)

            outputs = sess.run(None, feed)
            last_hidden = outputs[0]
            vecs = mean_pool(last_hidden, enc["attention_mask"])

            # Normalize L2 (cosine similarity)
            norms = np.linalg.norm(vecs, axis=1, keepdims=True).clip(min=1e-9)
            vecs = vecs / norms

        except Exception as e:
            log.warning("Batch %d error: %s", i // batch_size, e)
            continue

        for chunk_id, vec in zip(ids, vecs):
            blob = struct.pack(f"{len(vec)}f", *vec.tolist())
            con.execute("UPDATE rag_chunks SET embedding = ? WHERE id = ?", (blob, chunk_id))

        _wait_fts_lock()
        con.commit()
        stored += len(batch)

        elapsed = time.time() - t_start
        rate = stored / elapsed if elapsed > 0 else 0
        remaining = (total - stored) / rate if rate > 0 else 0
        log.info("[%d/%d] %.0f chunks/s — ~%.0fs left", stored, total, rate, remaining)

    con.close()
    return stored


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", nargs="*", default=PRIORITY_DOMAINS)
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--recode-old", action="store_true")
    parser.add_argument("--export-only", action="store_true", help="Only export ONNX, don't embed")
    parser.add_argument(
        "--fp16", action="store_true", help="Export/use FP16 model (faster DML, ~2x smaller)"
    )
    parser.add_argument(
        "--reexport", action="store_true", help="Force re-export even if model.onnx exists"
    )
    args = parser.parse_args()

    if not ONNX_MODEL.exists() or args.reexport:
        export_onnx(fp16=args.fp16)
    else:
        log.info("ONNX model found: %s (%.0fMB)", ONNX_MODEL, ONNX_MODEL.stat().st_size / 1e6)

    if args.export_only:
        log.info("--export-only done.")
        return

    if not RAG_DB.exists():
        log.error("RAG DB not found: %s", RAG_DB)
        sys.exit(1)

    _load_tokenizer()
    sess = load_session()

    chunks = fetch_chunks(args.domain, args.limit, args.recode_old)
    if not chunks:
        log.info("Nothing to do.")
        return

    t0 = time.time()
    stored = embed_and_store(sess, chunks, args.batch)
    elapsed = time.time() - t0
    log.info("=== DONE: %d BGE-M3 embeddings (1024d) in %.0fs ===", stored, elapsed)
    log.info("Restart hub: nssm restart NokidoMCP")


if __name__ == "__main__":
    main()
