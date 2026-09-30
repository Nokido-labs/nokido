#!/usr/bin/env python3
"""
Direct batch embedder — BGE-M3 ONNX via DirectML (Radeon 780M) or CPU fallback.
Bypasses brain_worker ZMQ, uses models/bge_m3_onnx/ directly.

Pipeline: reader-thread (fetch+tokenize) -> iGPU infer (main) -> writer-thread (SQL)
Dynamic padding: pad to batch max, not fixed 128 — avoids wasted compute on short chunks.
"""

import hashlib
import queue
import sqlite3
import struct
import threading
import time
from pathlib import Path

import numpy as np

print("EMBED_DIRECT START", flush=True)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
MODEL_DIR = ROOT / "models" / "bge_m3_onnx"
MODEL_PATH = MODEL_DIR / "model.onnx"
DOMAINS = None  # None = all domains with NULL embeddings, volume DESC
BATCH_SIZE = 64
MAX_LEN = 128
PREFETCH = 3  # batches pre-tokenized ahead of iGPU


def load_session():
    import onnxruntime as ort

    eps = ort.get_available_providers()
    if "DmlExecutionProvider" in eps:
        providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        backend = "DirectML"
    else:
        providers = ["CPUExecutionProvider"]
        backend = "CPU"
    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opts.intra_op_num_threads = 8
    try:
        opts.add_session_config_entry("onnxruntime.relocatable_mem_type", "1")
    except Exception:
        pass
    sess = ort.InferenceSession(str(MODEL_PATH), sess_options=opts, providers=providers)
    print(f"ONNX session: {backend} | inputs={[i.name for i in sess.get_inputs()]}", flush=True)
    return sess, backend


def make_tokenizer():
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tok.enable_truncation(max_length=MAX_LEN)
    # No fixed-length padding — pad to batch max (dynamic seq len)
    tok.enable_padding(pad_id=1, pad_token="<pad>")
    return tok


def _build_feed(sess, encs):
    input_ids = np.array([e.ids for e in encs], dtype=np.int64)
    attention_mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
    token_type_ids = np.zeros_like(input_ids)
    feed = {}
    for inp in sess.get_inputs():
        n = inp.name.lower()
        if "input_id" in n:
            feed[inp.name] = input_ids
        elif "attention" in n:
            feed[inp.name] = attention_mask
        elif "token_type" in n:
            feed[inp.name] = token_type_ids
    return feed, attention_mask


def infer(sess, encs):
    feed, attn = _build_feed(sess, encs)
    out = sess.run(None, feed)
    hidden = out[0]
    if hidden.ndim == 3:
        mask = attn.astype(np.float32)[..., None]
        vecs = (hidden * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1e-9)
    else:
        vecs = hidden
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return (vecs / np.where(norms == 0, 1, norms)).astype(np.float32)


def _db_connect(fast=False):
    con = sqlite3.connect(str(DB), timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    if fast:
        con.execute("PRAGMA synchronous=OFF")
        con.execute("PRAGMA cache_size=-65536")
    return con


def _write_batch(batch, vecs, retries=8):
    for attempt in range(retries):
        try:
            con = _db_connect(fast=True)
            for row, vec in zip(batch, vecs):
                rid, oid, txt, src = row
                fid = oid or hashlib.sha256((src + txt).encode()).hexdigest()[:16]
                blob = struct.pack(f"{len(vec)}f", *vec.tolist())
                con.execute(
                    "UPDATE rag_chunks SET embedding=?, id=? WHERE rowid=?", (blob, fid, rid)
                )
            con.commit()
            con.close()
            return True
        except sqlite3.OperationalError as e:
            if "locked" in str(e):
                wait = 3 + attempt * 3
                print(f"  [lock retry {attempt + 1}/{retries}] {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise
    # All retries exhausted — skip batch, will be picked up on next run
    print(f"  [SKIP batch size={len(batch)}] lock persists after {retries} retries", flush=True)
    return False


def _run_domain(sess, domain, rows):
    """3-stage pipeline: reader -> iGPU infer -> writer."""
    infer_q = queue.Queue(maxsize=PREFETCH)
    write_q = queue.Queue(maxsize=PREFETCH)
    errors = []

    def reader():
        try:
            tok = make_tokenizer()  # own instance — thread-safe
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                texts = [r[2] for r in batch]
                encs = tok.encode_batch(texts)
                infer_q.put((batch, encs))
        except Exception as e:
            errors.append(("reader", e))
        finally:
            infer_q.put(None)

    def writer():
        while True:
            try:
                item = write_q.get()
                if item is None:
                    break
                batch, vecs = item
                _write_batch(batch, vecs)  # returns False on skip, never raises
            except Exception as e:
                errors.append(("writer", e))
                # Don't die — keep consuming queue to avoid deadlock
                continue

    t_reader = threading.Thread(target=reader, daemon=True)
    t_writer = threading.Thread(target=writer, daemon=True)
    t_reader.start()
    t_writer.start()

    done = 0
    t0 = time.time()
    try:
        while True:
            item = infer_q.get()
            if item is None:
                break
            batch, encs = item
            if errors:
                break
            vecs = infer(sess, encs)
            write_q.put((batch, vecs), timeout=120)  # avoid deadlock if writer stalls
            done += len(batch)
            if done % 256 == 0 or done == len(rows):
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(rows) - done) / rate if rate > 0 else 0
                print(f"  [{domain}] {done}/{len(rows)} ({rate:.0f}/s ETA {eta:.0f}s)", flush=True)
    except Exception as e:
        errors.append(("infer", e))
    finally:
        write_q.put(None)

    t_writer.join()
    t_reader.join(timeout=5)

    if errors:
        for stage, e in errors:
            print(f"  [{domain}] ERROR in {stage}: {e}", flush=True)
            import traceback

            traceback.print_exc()

    print(f"[{domain}] done: {done}/{len(rows)} in {time.time() - t0:.1f}s", flush=True)
    return done


def run():
    t0 = time.time()
    print(f"Loading model from {MODEL_PATH}...", flush=True)
    sess, backend = load_session()

    # Warmup — 3 passes for DML kernel tuning
    tok_w = make_tokenizer()
    dummy = ["warmup sentence for DirectML kernel tuning on RDNA3 iGPU"] * BATCH_SIZE
    for _ in range(3):
        infer(sess, tok_w.encode_batch(dummy))
    print(f"Warmup done x3 ({backend}) in {time.time() - t0:.1f}s", flush=True)

    total_done = 0

    with _db_connect() as con:
        if DOMAINS is None:
            domain_rows = con.execute(
                "SELECT domain, COUNT(*) cnt FROM rag_chunks WHERE embedding IS NULL "
                "GROUP BY domain ORDER BY cnt DESC"
            ).fetchall()
            domains_to_run = [r[0] for r in domain_rows]
            print(
                f"Domaines manquants: {len(domains_to_run)} ({sum(r[1] for r in domain_rows)} chunks)",
                flush=True,
            )
        else:
            domains_to_run = DOMAINS

    for domain in domains_to_run:
        with _db_connect() as con:
            rows = con.execute(
                "SELECT rowid, id, text, source FROM rag_chunks "
                "WHERE domain=? AND embedding IS NULL ORDER BY rowid",
                (domain,),
            ).fetchall()

        if not rows:
            print(f"[{domain}] nothing to embed", flush=True)
            continue

        print(f"[{domain}] {len(rows)} chunks...", flush=True)
        total_done += _run_domain(sess, domain, rows)

    print(f"Total: {total_done} embeddings in {time.time() - t0:.1f}s", flush=True)
    print("EMBED_DIRECT DONE", flush=True)


if __name__ == "__main__":
    run()
